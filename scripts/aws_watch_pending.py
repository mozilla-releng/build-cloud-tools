#!/usr/bin/env python
"""
Watches pending jobs and starts or creates EC2 instances if required
"""
# lint_ignore=E501,C901
import re
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
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

import site
site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))

from cloudtools.aws import get_aws_connection, INSTANCE_CONFIGS_DIR, \
    aws_get_running_instances, aws_get_all_instances, get_user_data_tmpl, \
    aws_filter_instances, aws_get_spot_instances, aws_get_ondemand_instances,\
    aws_get_fresh_instances
from cloudtools.aws.spot import get_spot_requests_for_moztype, \
    usable_spot_choice, get_available_spot_slave_name, get_spot_choices
from cloudtools.jacuzzi import get_allocated_slaves, aws_get_slaveset_instances
from cloudtools.aws.ami import get_ami
from cloudtools.aws.vpc import get_avail_subnet

log = logging.getLogger()

# Number of seconds from an instance's launch time for it to be considered
# 'fresh'
FRESH_INSTANCE_DELAY = 20 * 60
FRESH_INSTANCE_DELAY_JACUZZI = 10 * 60


def find_pending(db):
    inspector = Inspector(db)
    # Newer buildbot has a "buildrequest_claims" table
    if "buildrequest_claims" in inspector.get_table_names():
        query = sa.text("""
        SELECT buildername, id FROM
               buildrequests WHERE
               complete=0 AND
               submitted_at > :yesterday AND
               submitted_at < :toonew AND
               (select count(brid) from buildrequest_claims
                       where brid=id) = 0""")
    # Older buildbot doesn't
    else:
        query = sa.text("""
        SELECT buildername, id FROM
               buildrequests WHERE
               complete=0 AND
               claimed_at=0 AND
               submitted_at > :yesterday AND
               submitted_at < :toonew""")

    result = db.execute(
        query,
        yesterday=time.time() - 86400,
        toonew=time.time() - 10
    )
    retval = result.fetchall()
    return retval


def aws_resume_instances(all_instances, moz_instance_type, start_count,
                         regions, region_priorities, instance_type_changes,
                         dryrun, slaveset):
    """Resume up to `start_count` stopped instances of the given type in the
    given regions"""
    # We'll filter by these tags in general
    tags = {'moz-state': 'ready', 'moz-type': moz_instance_type}

    # Get our list of stopped instances, sorted by region priority, then
    # launch_time. Higher region priorities mean we'll prefer to start those
    # instances first
    def _instance_sort_key(i):
        # Region is (usually?) the placement with the last character dropped
        r = i.placement[:-1]
        if r not in region_priorities:
            log.warning("No region priority for %s; az=%s; "
                        "region_priorities=%s", r, i.placement,
                        region_priorities)
        p = region_priorities.get(r, 0)
        return (p, i.launch_time)
    stopped_instances = list(reversed(sorted(
        aws_filter_instances(all_instances, state='stopped', tags=tags),
        key=_instance_sort_key)))
    log.debug("stopped_instances: %s", stopped_instances)

    to_start = []

    log.debug("filtering by slaveset %s", slaveset)
    # Filter the list of stopped instances by slaveset
    if slaveset:
        stopped_instances = filter(lambda i: i.tags.get('Name') in slaveset, stopped_instances)
    else:
        # Get list of all allocated slaves if we have no specific slaves
        # required
        allocated_slaves = get_allocated_slaves(None)
        stopped_instances = filter(lambda i: i.tags.get('Name') not in allocated_slaves, stopped_instances)

    # Add the rest of the stopped instances
    to_start.extend(stopped_instances)

    # Limit ourselves to start only start_count instances
    log.debug("starting up to %i instances", start_count)
    log.debug("to_start: %s", to_start)

    started = 0
    for i in to_start:
        if not dryrun:
            log.debug("%s - %s - starting", i.placement, i.tags['Name'])
            try:
                # Check if the instance type needs to be changed. See
                # watch_pending.cfg.example's instance_type_changes entry.
                new_instance_type = instance_type_changes.get(
                    i.region.name, {}).get(moz_instance_type)
                if new_instance_type and new_instance_type != i.instance_type:
                    log.warn("Changing %s (%s) instance type from %s to %s",
                             i.tags['Name'], i.id, i.instance_type,
                             new_instance_type)
                    i.connection.modify_instance_attribute(
                        i.id, "instanceType", new_instance_type)
                i.start()
                started += 1
            except BotoServerError:
                log.debug("Cannot start %s", i.tags['Name'], exc_info=True)
                log.warning("Cannot start %s", i.tags['Name'])
        else:
            log.info("%s - %s - would start", i.placement, i.tags['Name'])
            started += 1
        if started >= start_count:
            log.debug("Started %s instaces, breaking early", started)
            break

    return started


def request_spot_instances(all_instances, moz_instance_type, start_count,
                           regions, region_priorities, spot_config, dryrun,
                           slaveset):
    started = 0
    spot_rules = spot_config.get("rules", {}).get(moz_instance_type)
    if not spot_rules:
        log.warn("No spot rules found for %s", moz_instance_type)
        return 0

    instance_config = json.load(open(os.path.join(INSTANCE_CONFIGS_DIR, moz_instance_type)))
    connections = []
    for region in regions:
        conn = get_aws_connection(region)
        connections.append(conn)
    spot_choices = get_spot_choices(connections, spot_rules, "Linux/UNIX (Amazon VPC)")
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
        active_requests = get_spot_requests_for_moztype(region=region, moz_instance_type=moz_instance_type)
        log.debug("%i active spot requests for %s %s", len(active_requests), region, moz_instance_type)
        # Filter out requests for instances that don't exist
        active_requests = [r for r in active_requests if r.instance_id is not None and r.instance_id in acitve_instance_ids]
        log.debug("%i real active spot requests for %s %s", len(active_requests), region, moz_instance_type)
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
        )
        started += launched

        if started >= start_count:
            break

    return started


def do_request_spot_instances(amount, region, moz_instance_type, ami,
                              instance_config, spot_choice, slaveset,
                              dryrun):
    started = 0
    for _ in range(amount):
        try:
            r = do_request_spot_instance(
                region=region,
                moz_instance_type=moz_instance_type,
                price=spot_choice.bid_price,
                availability_zone=spot_choice.availability_zone,
                ami=ami, instance_config=instance_config,
                instance_type=spot_choice.instance_type, slaveset=slaveset,
                dryrun=dryrun)
            if r:
                started += 1
        except EC2ResponseError, e:
            if e.code == "MaxSpotInstanceCountExceeded":
                log.warn("MaxSpotInstanceCountExceeded in %s; giving up", region)
                return started
            log.warn("Cannot start", exc_info=True)
        except Exception:
            log.warn("Cannot start", exc_info=True)
    return started


def do_request_spot_instance(region, moz_instance_type, price, ami,
                             instance_config, instance_type, availability_zone,
                             slaveset, dryrun):
    name = get_available_spot_slave_name(region, moz_instance_type, slaveset)
    if not name:
        log.warn("No slave name available for %s, %s, %s" % (
            region, moz_instance_type, slaveset))
        return False

    conn = get_aws_connection(region)
    subnet_id = get_avail_subnet(region, instance_config[region]["subnet_ids"],
                                 availability_zone)
    if not subnet_id:
        log.debug("No free IP available for %s in %s", moz_instance_type,
                  availability_zone)
        return False

    fqdn = "{}.{}".format(name, instance_config[region]["domain"])
    log.debug("Spot request for %s (%s)", fqdn, price)

    if dryrun:
        log.info("Dry run. skipping")
        return True

    spec = NetworkInterfaceSpecification(
        associate_public_ip_address=True, subnet_id=subnet_id,
        groups=instance_config[region].get("security_group_ids"))
    nc = NetworkInterfaceCollection(spec)

    user_data = get_user_data_tmpl(moz_instance_type)
    if user_data:
        user_data = user_data.format(fqdn=fqdn,
                                     moz_instance_type=moz_instance_type,
                                     is_spot=True)

    bdm = BlockDeviceMapping()
    for device, device_info in instance_config[region]['device_map'].items():
        bd = BlockDeviceType()
        if device_info.get('size'):
            bd.size = device_info['size']
        if ami.root_device_name == device:
            ami_size = ami.block_device_mapping[device].size
            if ami.virtualization_type == "hvm":
                # Overwrite root device size for HVM instances, since they
                # cannot be resized online
                bd.size = ami_size
            elif device_info.get('size'):
                # make sure that size is enough for this AMI
                assert ami_size <= device_info['size'], \
                    "Instance root device size cannot be smaller than AMI " \
                    "root device"
        if device_info.get("delete_on_termination") is not False:
            bd.delete_on_termination = True
        if device_info.get("ephemeral_name"):
            bd.ephemeral_name = device_info["ephemeral_name"]
        if device_info.get("volume_type"):
            bd.volume_type = device_info["volume_type"]

        bdm[device] = bd

    sir = conn.request_spot_instances(
        price=str(price),
        image_id=ami.id,
        count=1,
        instance_type=instance_type,
        key_name=instance_config[region]["ssh_key"],
        user_data=user_data,
        block_device_map=bdm,
        network_interfaces=nc,
        instance_profile_name=instance_config[region].get("instance_profile_name"),
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


def aws_watch_pending(dburl, regions, builder_map, region_priorities,
                      spot_config, ondemand_config, dryrun,
                      instance_type_changes):
    # First find pending jobs in the db
    db = sa.create_engine(dburl)
    pending = find_pending(db)

    if not pending:
        log.debug("no pending jobs! all done!")
        return
    log.debug("processing %i pending jobs", len(pending))

    # Mapping of (instance types, slaveset) to # of instances we want to
    # creates
    to_create = {
        'spot': defaultdict(int),
        'ondemand': defaultdict(int),
    }
    to_create_ondemand = to_create['ondemand']
    to_create_spot = to_create['spot']

    # Map pending builder names to instance types
    for pending_buildername, brid in pending:
        for buildername_exp, moz_instance_type in builder_map.items():
            if re.match(buildername_exp, pending_buildername):
                slaveset = get_allocated_slaves(pending_buildername)
                log.debug("%s instance type %s slaveset %s", pending_buildername, moz_instance_type, slaveset)
                to_create_spot[moz_instance_type, slaveset] += 1
                break
        else:
            log.debug("%s has pending jobs, but no instance types defined",
                      pending_buildername)

    if not to_create_spot and not to_create_ondemand:
        log.debug("no pending jobs we can do anything about! all done!")
        return

    # For each moz_instance_type, slaveset, find how many are currently running,
    # and scale our count accordingly
    all_instances = aws_get_all_instances(regions)

    for create_type, d in to_create.iteritems():
        to_delete = set()
        for (moz_instance_type, slaveset), count in d.iteritems():
            running = aws_get_running_instances(all_instances, moz_instance_type)
            running = aws_get_slaveset_instances(running, slaveset)
            # Filter by create_type
            if create_type == 'spot':
                running = aws_get_spot_instances(running)
            else:
                running = aws_get_ondemand_instances(running)

            # Get instances launched recently
            if slaveset:
                # jaccuzied slaves, use shorter delay
                fresh = aws_get_fresh_instances(running, time.time() - FRESH_INSTANCE_DELAY_JACUZZI)
            else:
                fresh = aws_get_fresh_instances(running, time.time() - FRESH_INSTANCE_DELAY)
            log.info("%i running for %s %s %s (%i fresh)", len(running), create_type, moz_instance_type, slaveset, len(fresh))
            # TODO: This logic is probably too simple
            # Reduce the number of required slaves by the number of freshly
            # started instaces, plus 10% of those that have been running a
            # while
            num_fresh = len(fresh)
            # reduce number of required slaves by number of fresh instances
            delta = num_fresh
            if not slaveset:
                # if not in jacuzzi, reduce by 10% of already running instances
                num_old = len(running) - num_fresh
                delta += num_old / 10
            log.info("reducing required count for %s %s %s by %i (%i running; need %i)", create_type, moz_instance_type, slaveset, delta, len(running), count)
            d[moz_instance_type, slaveset] = max(0, count - delta)
            if d[moz_instance_type, slaveset] == 0:
                log.info("removing requirement for %s %s %s", create_type, moz_instance_type, slaveset)
                to_delete.add((moz_instance_type, slaveset))

            # If slaveset is not None, and all our slaves are running, we should
            # remove it from the set of things to try and start instances for
            if slaveset and set(i.tags.get('Name') for i in running) == slaveset:
                log.info("removing %s %s since all the slaves are running", moz_instance_type, slaveset)
                to_delete.add((moz_instance_type, slaveset))

        for moz_instance_type, slaveset in to_delete:
            del d[moz_instance_type, slaveset]

    for (moz_instance_type, slaveset), count in to_create_spot.iteritems():
        log.debug("need %i spot %s for slaveset %s", count, moz_instance_type, slaveset)
        # Cap by our global limits if applicable
        if spot_config and 'global' in spot_config.get('limits', {}):
            global_limit = spot_config['limits']['global'].get(moz_instance_type)
            # How many of this type of spot instance are running?
            n = len(aws_get_spot_instances(aws_get_running_instances(all_instances, moz_instance_type)))
            log.debug("%i %s spot instances running globally", n, moz_instance_type)
            if global_limit and n + count > global_limit:
                new_count = max(0, global_limit - n)
                log.info("decreasing requested number of %s from %i to %i (%i out of %i running)", moz_instance_type, count, new_count, n, global_limit)
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

        # Add leftover to ondemand
        to_create_ondemand[moz_instance_type, slaveset] += count

    for (moz_instance_type, slaveset), count in to_create_ondemand.iteritems():
        log.debug("need %i ondemand %s for slaveset %s", count, moz_instance_type, slaveset)
        # Cap by our global limits if applicable
        if ondemand_config and 'global' in ondemand_config.get('limits', {}):
            global_limit = ondemand_config['limits']['global'].get(moz_instance_type)
            # How many of this type of ondemand instance are running?
            n = len(aws_get_ondemand_instances(aws_get_running_instances(all_instances, moz_instance_type)))
            log.debug("%i %s ondemand instances running globally", n, moz_instance_type)
            if global_limit and n + count > global_limit:
                new_count = max(0, global_limit - n)
                log.info("decreasing requested number of %s from %i to %i (%i out of %i running)", moz_instance_type, count, new_count, n, global_limit)
                count = new_count
                if count <= 0:
                    continue
        if count < 1:
            continue

        # Check for stopped instances in the given regions and start them if
        # there are any
        started = aws_resume_instances(all_instances, moz_instance_type, count,
                                       regions, region_priorities,
                                       instance_type_changes, dryrun, slaveset)
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
        instance_type_changes=config.get("instance_type_changes", {})
    )
    log.debug("done")
