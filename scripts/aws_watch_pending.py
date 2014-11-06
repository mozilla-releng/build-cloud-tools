#!/usr/bin/env python
"""
Watches pending jobs and starts or creates EC2 instances if required
"""
# lint_ignore=E501,C901
import time
from collections import defaultdict
import os
import logging

try:
    import simplejson as json
    assert json
except ImportError:
    import json

from boto.exception import BotoServerError, EC2ResponseError
from boto.ec2.networkinterface import NetworkInterfaceCollection, \
    NetworkInterfaceSpecification

import site
site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))

from cloudtools.aws import (get_aws_connection,  aws_get_running_instances,
                            aws_get_all_instances, filter_spot_instances,
                            filter_ondemand_instances, reduce_by_freshness,
                            distribute_in_region, load_instance_config,
                            jacuzzi_suffix)
from cloudtools.aws.spot import get_spot_requests_for_moztype, \
    usable_spot_choice, get_available_slave_name, get_spot_choices
from cloudtools.jacuzzi import filter_instances_by_slaveset
from cloudtools.aws.ami import get_ami
from cloudtools.aws.vpc import get_avail_subnet
from cloudtools.buildbot import find_pending, map_builders
from cloudtools.aws.instance import create_block_device_mapping, \
    user_data_from_template, tag_ondemand_instance
import cloudtools.graphite

log = logging.getLogger()
gr_log = cloudtools.graphite.get_graphite_logger()


def aws_resume_instances(all_instances, moz_instance_type, start_count,
                         regions, region_priorities, dryrun, slaveset):
    """Create up to `start_count` on-demand instances"""

    start_count_per_region = distribute_in_region(start_count, regions,
                                                  region_priorities)

    started = 0
    instance_config = load_instance_config(moz_instance_type)
    for region, count in start_count_per_region.iteritems():
        # TODO: check region limits
        ami = get_ami(region=region, moz_instance_type=moz_instance_type)
        for _ in range(count):
            try:
                r = do_request_instance(
                    region=region,
                    moz_instance_type=moz_instance_type,
                    price=None, availability_zone=None,
                    ami=ami, instance_config=instance_config,
                    instance_type=instance_config[region]["instance_type"],
                    slaveset=slaveset, is_spot=False, dryrun=dryrun,
                    all_instances=all_instances)
                if r:
                    started += 1
            except EC2ResponseError, e:
                # TODO: Handle e.code
                log.warn("On-demand failure: %s; giving up", e.code)
                log.warn("Cannot start", exc_info=True)
                break
            except Exception:
                log.warn("Cannot start", exc_info=True)

    return started


def request_spot_instances(all_instances, moz_instance_type, start_count,
                           regions, region_priorities, spot_config, dryrun,
                           slaveset):
    started = 0
    spot_rules = spot_config.get("rules", {}).get(moz_instance_type)
    if not spot_rules:
        log.warn("No spot rules found for %s", moz_instance_type)
        return 0

    instance_config = load_instance_config(moz_instance_type)
    connections = [get_aws_connection(r) for r in regions]
    spot_choices = get_spot_choices(connections, spot_rules,
                                    "Linux/UNIX (Amazon VPC)")
    if not spot_choices:
        log.warn("No spot choices for %s", moz_instance_type)
        return 0

    to_start = {}
    acitve_instance_ids = set(i.id for i in all_instances)
    for region in regions:
        # Check if spots are enabled in this region for this type
        region_limit = spot_config.get("limits", {}).get(region, {}).get(
            moz_instance_type)
        if not region_limit:
            log.debug("No spot limits defined for %s in %s, skipping...",
                      moz_instance_type, region)
            continue

        # check the limits
        active_requests = get_spot_requests_for_moztype(
            region=region, moz_instance_type=moz_instance_type)
        log.debug("%i active spot requests for %s %s", len(active_requests),
                  region, moz_instance_type)
        # Filter out requests for instances that don't exist
        active_requests = [r for r in active_requests if r.instance_id is not
                           None and r.instance_id in acitve_instance_ids]
        log.debug("%i real active spot requests for %s %s",
                  len(active_requests), region, moz_instance_type)
        active_count = len(active_requests)
        can_be_started = region_limit - active_count
        if can_be_started < 1:
            log.debug("Not starting. Active spot request count in %s region "
                      "hit limit of %s. Active count: %s", region,
                      region_limit, active_count)
            continue

        to_be_started = min(can_be_started, start_count - started)
        ami = get_ami(region=region, moz_instance_type=moz_instance_type)
        to_start[region] = {"ami": ami, "instances": to_be_started}

    if not to_start:
        log.debug("Nothing to start for %s", moz_instance_type)
        return 0

    for choice in spot_choices:
        region = choice.region
        if region not in to_start:
            log.debug("Skipping %s for %s", choice, region)
            continue
        if not usable_spot_choice(choice):
            log.debug("Skipping %s for %s - unusable", choice, region)
            continue
        need = min(to_start[region]["instances"], start_count - started)
        log.debug("Need %s of %s in %s", need, moz_instance_type,
                  choice.availability_zone)

        log.debug("Using %s", choice)
        launched = do_request_spot_instances(
            amount=need,
            region=region,
            moz_instance_type=moz_instance_type,
            ami=to_start[region]["ami"],
            instance_config=instance_config, dryrun=dryrun,
            spot_choice=choice,
            slaveset=slaveset,
            all_instances=all_instances,
        )
        started += launched

        if started >= start_count:
            break

    return started


def do_request_spot_instances(amount, region, moz_instance_type, ami,
                              instance_config, spot_choice, slaveset,
                              all_instances, dryrun):
    started = 0
    for _ in range(amount):
        try:
            r = do_request_instance(
                region=region,
                moz_instance_type=moz_instance_type,
                price=spot_choice.bid_price,
                availability_zone=spot_choice.availability_zone,
                ami=ami, instance_config=instance_config,
                instance_type=spot_choice.instance_type, slaveset=slaveset,
                is_spot=True, dryrun=dryrun, all_instances=all_instances)
            if r:
                started += 1
            else:
                return started
        except EC2ResponseError, e:
            if e.code == "MaxSpotInstanceCountExceeded":
                log.warn("MaxSpotInstanceCountExceeded in %s; giving up", region)
                return started
            log.warn("Cannot start", exc_info=True)
        except Exception:
            log.warn("Cannot start", exc_info=True)
    return started


def do_request_instance(region, moz_instance_type, price, ami, instance_config,
                        instance_type, availability_zone, slaveset, is_spot,
                        all_instances, dryrun):
    name = get_available_slave_name(region, moz_instance_type, slaveset,
                                    is_spot=is_spot,
                                    all_instances=all_instances)
    if not name:
        log.debug("No slave name available for %s, %s, %s" % (
            region, moz_instance_type, slaveset))
        return False

    subnet_id = get_avail_subnet(region, instance_config[region]["subnet_ids"],
                                 availability_zone)
    if not subnet_id:
        log.debug("No free IP available for %s in %s", moz_instance_type,
                  availability_zone)
        return False

    fqdn = "{}.{}".format(name, instance_config[region]["domain"])
    if is_spot:
        log.debug("Spot request for %s (%s)", fqdn, price)
    else:
        log.debug("Starting %s", fqdn)

    if dryrun:
        log.info("Dry run. skipping")
        return True

    spec = NetworkInterfaceSpecification(
        associate_public_ip_address=True, subnet_id=subnet_id,
        delete_on_termination=True,
        groups=instance_config[region].get("security_group_ids"))
    nc = NetworkInterfaceCollection(spec)

    user_data = user_data_from_template(moz_instance_type, fqdn)
    bdm = create_block_device_mapping(
        ami, instance_config[region]['device_map'])
    if is_spot:
        rv = do_request_spot_instance(
            region, price, ami.id, instance_type,
            instance_config[region]["ssh_key"], user_data, bdm, nc,
            instance_config[region].get("instance_profile_name"),
            moz_instance_type, name, fqdn)
    else:
        rv = do_request_ondemand_instance(
            region, price, ami.id, instance_type,
            instance_config[region]["ssh_key"], user_data, bdm, nc,
            instance_config[region].get("instance_profile_name"),
            moz_instance_type, name, fqdn)
    if rv:
        template_values = dict(
            region=region,
            moz_instance_type=moz_instance_type,
            instance_type=instance_type,
            life_cycle_type="spot" if is_spot else "ondemand",
            virtualization=ami.virtualization_type,
            root_device_type=ami.root_device_type,
            jacuzzi_type=jacuzzi_suffix(slaveset),
        )
        name = "started.{region}.{moz_instance_type}.{instance_type}" \
            ".{life_cycle_type}.{virtualization}.{root_device_type}" \
            ".{jacuzzi_type}"
        gr_log.add(name.format(**template_values), 1, collect=True)
    return rv


def do_request_spot_instance(region, price, ami_id, instance_type, ssh_key,
                             user_data, bdm, nc, profile, moz_instance_type,
                             name, fqdn):
    conn = get_aws_connection(region)
    sir = conn.request_spot_instances(
        price=str(price),
        image_id=ami_id,
        count=1,
        instance_type=instance_type,
        key_name=ssh_key,
        user_data=user_data,
        block_device_map=bdm,
        network_interfaces=nc,
        instance_profile_name=profile,
    )
    # Sleep for a little bit to prevent us hitting
    # InvalidSpotInstanceRequestID.NotFound right away
    time.sleep(0.5)
    max_tries = 10
    sleep_time = 5
    for i in range(max_tries):
        try:
            sir[0].add_tag("moz-type", moz_instance_type)
            # Name will be used to determine available slave names
            sir[0].add_tag("Name", name)
            sir[0].add_tag("FQDN", fqdn)
            return True
        except EC2ResponseError, e:
            if e.code == "InvalidSpotInstanceRequestID.NotFound":
                if i < max_tries - 1:
                    # Try again
                    log.debug("waiting for spot request")
                    time.sleep(sleep_time)
                    sleep_time = min(30, sleep_time * 1.5)
                    continue
        except BotoServerError, e:
            if e.code == "RequestLimitExceeded":
                if i < max_tries - 1:
                    # Try again
                    log.debug("request limit exceeded; sleeping and trying again")
                    time.sleep(sleep_time)
                    sleep_time = min(30, sleep_time * 1.5)
                    continue
            raise


def do_request_ondemand_instance(region, price, ami_id, instance_type, ssh_key,
                                 user_data, bdm, nc, profile,
                                 moz_instance_type, name, fqdn):
    conn = get_aws_connection(region)
    res = conn.run_instances(
        image_id=ami_id,
        key_name=ssh_key,
        instance_type=instance_type,
        user_data=user_data,
        block_device_map=bdm,
        network_interfaces=nc,
        instance_profile_name=profile,
        # terminate the instances on shutdown
        instance_initiated_shutdown_behavior="terminate",
    )
    return tag_ondemand_instance(res.instances[0], name, fqdn,
                                 moz_instance_type)


def aws_watch_pending(dburl, regions, builder_map, region_priorities,
                      spot_config, ondemand_config, dryrun):
    # First find pending jobs in the db
    pending = find_pending(dburl)

    if not pending:
        gr_log.add("pending", 0)
        log.debug("no pending jobs! all done!")
        return

    log.debug("processing %i pending jobs", len(pending))
    gr_log.add("pending", len(pending))

    # Mapping of (instance types, slaveset) to # of instances we want to
    # creates
    # Map pending builder names to instance types
    pending_builder_map = map_builders(pending, builder_map)
    gr_log.add("aws_pending", sum(pending_builder_map.values()))
    if not pending_builder_map:
        log.debug("no pending jobs we can do anything about! all done!")
        return

    to_create_spot = pending_builder_map
    to_create_ondemand = defaultdict(int)

    # For each moz_instance_type, slaveset, find how many are currently
    # running, and scale our count accordingly
    all_instances = aws_get_all_instances(regions)
    cloudtools.graphite.generate_instance_stats(all_instances)

    # Reduce the requirements, pay attention to freshess and running instances
    to_delete = set()
    for (moz_instance_type, slaveset), count in to_create_spot.iteritems():
        running = filter_instances_by_slaveset(
            aws_get_running_instances(all_instances, moz_instance_type),
            slaveset)
        spot_running = filter_spot_instances(running)

        to_create_spot[moz_instance_type, slaveset] = reduce_by_freshness(
            count, spot_running, moz_instance_type, slaveset)

        if to_create_spot[moz_instance_type, slaveset] == 0:
            log.debug("removing requirement for %s %s %s", "spot",
                      moz_instance_type, slaveset)
            to_delete.add((moz_instance_type, slaveset))

        # If slaveset is not None, and all our slaves are running, we should
        # remove it from the set of things to try and start instances for
        if slaveset and \
                slaveset.issubset(
                    set(i.tags.get('Name') for i in spot_running)):
            log.debug("removing %s %s since all the slaves are running",
                      moz_instance_type, slaveset)
            to_delete.add((moz_instance_type, slaveset))

    for moz_instance_type, slaveset in to_delete:
        del to_create_spot[moz_instance_type, slaveset]

    for (moz_instance_type, slaveset), count in to_create_spot.iteritems():
        log.debug("need %i spot %s for slaveset %s", count, moz_instance_type, slaveset)
        # Cap by our global limits if applicable
        if spot_config and 'global' in spot_config.get('limits', {}):
            global_limit = spot_config['limits']['global'].get(moz_instance_type)
            # How many of this type of spot instance are running?
            n = len(filter_spot_instances(aws_get_running_instances(all_instances, moz_instance_type)))
            log.debug("%i %s spot instances running globally", n, moz_instance_type)
            if global_limit and n + count > global_limit:
                new_count = max(0, global_limit - n)
                log.debug("decreasing requested number of %s from %i to %i (%i out of %i running)", moz_instance_type, count, new_count, n, global_limit)
                count = new_count
                if count <= 0:
                    continue

        started = request_spot_instances(
            all_instances,
            moz_instance_type=moz_instance_type, start_count=count,
            regions=regions, region_priorities=region_priorities,
            spot_config=spot_config, dryrun=dryrun, slaveset=slaveset)
        count -= started
        log.info("%s - started %i spot instances for slaveset %s; need %i",
                 moz_instance_type, started, slaveset, count)
        gr_log.add("need.{moz_instance_type}.{jacuzzi_type}".format(
            moz_instance_type=moz_instance_type,
            jacuzzi_type=jacuzzi_suffix(slaveset)), count, collect=True)

        # Add leftover to ondemand
        to_create_ondemand[moz_instance_type, slaveset] += count

    for (moz_instance_type, slaveset), count in to_create_ondemand.iteritems():
        log.debug("need %i ondemand %s for slaveset %s", count,
                  moz_instance_type, slaveset)
        # Cap by our global limits if applicable
        if ondemand_config and 'global' in ondemand_config.get('limits', {}):
            global_limit = ondemand_config['limits']['global'].get(moz_instance_type)
            # How many of this type of ondemand instance are running?
            n = len(filter_ondemand_instances(aws_get_running_instances(all_instances, moz_instance_type)))
            log.debug("%i %s ondemand instances running globally", n, moz_instance_type)
            if global_limit and n + count > global_limit:
                new_count = max(0, global_limit - n)
                log.debug("decreasing requested number of %s from %i to %i (%i out of %i running)", moz_instance_type, count, new_count, n, global_limit)
                count = new_count
                if count <= 0:
                    continue
        if count < 1:
            continue

        # Check for stopped instances in the given regions and start them if
        # there are any
        started = aws_resume_instances(all_instances, moz_instance_type, count,
                                       regions, region_priorities,
                                       dryrun, slaveset)
        count -= started
        log.info("%s - started %i instances for slaveset %s; need %i",
                 moz_instance_type, started, slaveset, count)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", action="append", dest="regions",
                        required=True)
    parser.add_argument("-k", "--secrets", type=argparse.FileType('r'),
                        required=True)
    parser.add_argument("-c", "--config", type=argparse.FileType('r'),
                        required=True)
    parser.add_argument("-v", "--verbose", action="store_const",
                        dest="loglevel", const=logging.DEBUG,
                        default=logging.INFO)
    parser.add_argument("-n", "--dryrun", dest="dryrun", action="store_true",
                        help="don't actually do anything")
    parser.add_argument("-l", "--logfile", dest="logfile",
                        help="log file for full debug log")

    args = parser.parse_args()

    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("boto").setLevel(logging.INFO)
    logging.getLogger("requests").setLevel(logging.WARN)
    logging.getLogger("iso8601").setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(args.loglevel)
    logging.getLogger().addHandler(handler)
    if args.logfile:
        fhandler = logging.handlers.RotatingFileHandler(
            args.logfile, maxBytes=10 * (1024 ** 2), backupCount=100)
        fhandler.setLevel(logging.DEBUG)
        fhandler.setFormatter(formatter)
        logging.getLogger().addHandler(fhandler)

    config = json.load(args.config)
    secrets = json.load(args.secrets)

    aws_watch_pending(
        dburl=secrets['db'],
        regions=args.regions,
        builder_map=config['buildermap'],
        region_priorities=config['region_priorities'],
        dryrun=args.dryrun,
        spot_config=config.get("spot"),
        ondemand_config=config.get("ondemand"),
    )
    if config.get("graphite_host") and config.get("graphite_port"):
        gr_log.connect(host=config.get("graphite_host"),
                       port=config.get("graphite_port"))
        gr_log.sendall(prefix=config.get("graphite_prefix",
                                         "aws_watch_pending"))
    log.debug("done")
