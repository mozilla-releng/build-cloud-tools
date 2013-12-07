#!/usr/bin/env python
"""
Watches pending jobs and starts or creates EC2 instances if required
"""
import re
import time
import random
from collections import defaultdict

try:
    import simplejson as json
    assert json
except ImportError:
    import json

import boto.ec2
from boto.exception import BotoServerError
from boto.ec2.networkinterface import NetworkInterfaceCollection, \
    NetworkInterfaceSpecification
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

import requests
import os
import logging
log = logging.getLogger()


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


def find_retries(db, brid):
    """Returns the number of previous builds for this build request id"""
    q = sa.text("SELECT count(*) from builds where brid=:brid")
    return db.execute(q, brid=brid).fetchone()[0]


# Used by aws_connect_to_region to cache connection objects per region
_aws_cached_connections = {}


def aws_connect_to_region(region, secrets):
    """Connect to an EC2 region. Caches connection objects"""
    if region in _aws_cached_connections:
        return _aws_cached_connections[region]
    conn = boto.ec2.connect_to_region(
        region,
        aws_access_key_id=secrets['aws_access_key_id'],
        aws_secret_access_key=secrets['aws_secret_access_key']
    )
    _aws_cached_connections[region] = conn
    return conn


def aws_get_spot_requests(region, secrets, moz_instance_type):
    """retruns a list of all open and active spot requests"""
    conn = aws_connect_to_region(region, secrets)
    filters = {"tag:moz-type": moz_instance_type}
    req = conn.get_all_spot_instance_requests(filters=filters)
    return [r for r in req if r.state in ("open", "active")]


def aws_get_all_instances(regions, secrets):
    """
    Returns a list of all instances in the given regions
    """
    log.debug("fetching all instances for %s", regions)
    retval = []
    for region in regions:
        conn = aws_connect_to_region(region, secrets)
        reservations = conn.get_all_instances()
        for r in reservations:
            retval.extend(r.instances)
    return retval


def aws_filter_instances(all_instances, state=None, tags=None):
    retval = []
    for i in all_instances:
        matched = True
        if state and i.state != state:
            matched = False
            continue
        if tags:
            for k, v in tags.items():
                if i.tags.get(k) != v:
                    matched = False
                    continue
        if matched:
            retval.append(i)
    return retval


def aws_get_reservations(regions, secrets):
    """
    Return a mapping of (availability zone, ec2 instance type) -> count
    """
    log.debug("getting reservations for %s", regions)
    retval = {}
    for region in regions:
        conn = aws_connect_to_region(region, secrets)
        reservations = conn.get_all_reserved_instances(filters={
            'state': 'active',
        })
        for r in reservations:
            az = r.availability_zone
            ec2_instance_type = r.instance_type
            if (az, ec2_instance_type) not in retval:
                retval[az, ec2_instance_type] = 0
            retval[az, ec2_instance_type] += r.instance_count
    return retval


def aws_filter_reservations(reservations, running_instances):
    """
    Filters reservations by reducing the count for reservations by the number
    of running instances of the appropriate type. Removes entries for
    reservations that are fully used.

    Modifies reservations in place
    """
    # Subtract running instances from our reservations
    for i in running_instances:
        if (i.placement, i.instance_type) in reservations:
            reservations[i.placement, i.instance_type] -= 1
    log.debug("available reservations: %s", reservations)

    # Remove reservations that are used up
    for k, count in reservations.items():
        if count <= 0:
            log.debug("all reservations for %s are used; removing", k)
            del reservations[k]


def aws_resume_instances(moz_instance_type, start_count, regions, secrets,
                         region_priorities, dryrun):
    """Resume up to `start_count` stopped instances of the given type in the
    given regions"""
    # Fetch all our instance information
    all_instances = aws_get_all_instances(regions, secrets)
    # We'll filter by these tags in general
    tags = {'moz-state': 'ready', 'moz-type': moz_instance_type}

    # If our instance config specifies a maximum number of running instances,
    # apply that now. This may mean that we reduce start_count, or return early
    # if we're already running >= max_running
    instance_config = json.load(open("configs/%s" % moz_instance_type))
    max_running = instance_config.get('max_running')
    if max_running is not None:
        running = len(aws_filter_instances(all_instances, state='running',
                                           tags=tags))
        if running + start_count > max_running:
            start_count = max_running - running
            if start_count <= 0:
                log.info("max_running limit hit (%s - %i)",
                         moz_instance_type, max_running)
                return 0

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

    # Get our current reservations
    reservations = aws_get_reservations(regions, secrets)
    log.debug("current reservations: %s", reservations)

    # Get our currently running instances
    running_instances = aws_filter_instances(all_instances, state='running')

    # Filter the reservations
    aws_filter_reservations(reservations, running_instances)
    log.debug("filtered reservations: %s", reservations)

    # List of (instance, is_reserved) tuples
    to_start = []

    # While we still have reservations, start instances that can use those
    # reservations first
    for i in stopped_instances[:]:
        k = (i.placement, i.instance_type)
        if k not in reservations:
            continue
        stopped_instances.remove(i)
        to_start.append((i, True))
        reservations[k] -= 1
        if reservations[k] <= 0:
            del reservations[k]

    # Add the rest of the stopped instances
    to_start.extend((i, False) for i in stopped_instances)

    # Limit ourselves to start only start_count instances
    log.debug("starting up to %i instances", start_count)
    log.debug("to_start: %s", to_start)

    started = 0
    for i, is_reserved in to_start:
        r = "reserved instance" if is_reserved else "instance"
        if not dryrun:
            log.debug("%s - %s - starting %s", i.placement, i.tags['Name'], r)
            try:
                i.start()
                started += 1
            except BotoServerError:
                log.debug("Cannot start %s", i.tags['Name'], exc_info=True)
                log.warning("Cannot start %s", i.tags['Name'])
        else:
            log.info("%s - %s - would start %s", i.placement, i.tags['Name'],
                     r)
            started += 1
        if started >= start_count:
            log.debug("Started %s instaces, breaking early", started)
            break

    return started


def request_spot_instances(moz_instance_type, start_count, regions, secrets,
                           region_priorities, spot_limits, dryrun,
                           cached_cert_dir):
    started = 0
    instance_config = json.load(open("configs/%s" % moz_instance_type))

    # sort regions by their priority
    for region in sorted(regions, key=lambda k: region_priorities.get(k, 0),
                         reverse=True):
        # Check if spots are enabled in this region for this type
        region_limit = spot_limits.get(region, {}).get(
            moz_instance_type, {}).get("instances")
        if not region_limit:
            log.debug("No spot limits defined for %s in %s, skipping...",
                      moz_instance_type, region)
            continue

        # check the limits
        active_count = len(aws_get_spot_requests(
            region=region, secrets=secrets,
            moz_instance_type=moz_instance_type))
        can_be_started = region_limit - active_count
        if can_be_started < 1:
            log.debug("Not starting. Active spot request count in %s region "
                      "hit limit of %s. Active count: %s", region,
                      region_limit, active_count)
            continue

        to_be_started = min(can_be_started, start_count - started)
        ami = get_ami(region=region, secrets=secrets,
                      moz_instance_type=moz_instance_type)

        for _ in range(to_be_started):
            # FIXME: failed requests increment the iterator
            try:
                # FIXME:use dynamic pricing
                price = spot_limits[region][moz_instance_type]["price"]
                do_request_spot_instances(
                    region=region, secrets=secrets,
                    moz_instance_type=moz_instance_type, price=price,
                    ami=ami, instance_config=instance_config, dryrun=dryrun,
                    cached_cert_dir=cached_cert_dir)
                started += 1
            except (RuntimeError, KeyError):
                log.warning("Spot request failed", exc_info=True)

        if started >= start_count:
            break

    return started


def get_puppet_certs(ip, secrets, cached_cert_dir):
    """ reuse or generate certificates"""
    cert_file = os.path.join(cached_cert_dir, ip)
    if os.path.exists(cert_file):
        return open(cert_file).read()

    puppet_server = secrets["getcert_server"]
    url = "https://%s/deploy/getcert.cgi?%s" % (puppet_server, ip)
    auth = (secrets["deploy_username"], secrets["deploy_password"])
    req = requests.get(url, auth=auth, verify=False)
    req.raise_for_status()
    cert_data = req.content
    with open(cert_file, "wb") as f:
        f.write(cert_data)
    return cert_data


def do_request_spot_instances(region, secrets, moz_instance_type, price, ami,
                              instance_config, cached_cert_dir, dryrun):
    conn = aws_connect_to_region(region, secrets)
    interface = get_avalable_interface(
        conn=conn, moz_instance_type=moz_instance_type)
    if not interface:
        raise RuntimeError("No free network interfaces left in %s" % region)

    # TODO: check DNS
    fqdn = interface.tags.get("FQDN")
    if not fqdn:
        raise RuntimeError("Skipping %s without FQDN" % interface)

    log.debug("Spot request for %s", fqdn)

    if dryrun:
        log.info("Dry run. skipping")
        return

    spec = NetworkInterfaceSpecification(
        network_interface_id=interface.id)
    nc = NetworkInterfaceCollection(spec)
    ip = interface.private_ip_address
    certs = get_puppet_certs(ip, secrets, cached_cert_dir)
    user_data = """
FQDN="%(fqdn)s"
cd /var/lib/puppet/ssl || exit 1
%(certs)s
cd -
""" % dict(fqdn=fqdn, certs=certs)
    bdm = BlockDeviceMapping()
    for device, device_info in instance_config[region]['device_map'].items():
        bdm[device] = BlockDeviceType(size=device_info['size'],
                                      delete_on_termination=True)

    sir = conn.request_spot_instances(
        price=price,
        image_id=ami.id,
        count=1,
        instance_type=instance_config[region]["instance_type"],
        key_name=instance_config[region]["ssh_key"],
        user_data=user_data,
        block_device_map=bdm,
        network_interfaces=nc)
    sir[0].add_tag("moz-type", moz_instance_type)


def get_avalable_interface(conn, moz_instance_type):
    # TODO: find a way to reserve interfaces to reduce collision
    avail_ifs = conn.get_all_network_interfaces(
        filters={"status": "available", "tag:moz-type": moz_instance_type})
    # TODO: sort by AZ?
    if avail_ifs:
        return random.choice(avail_ifs)
    else:
        return None


def get_ami(region, secrets, moz_instance_type):
    conn = aws_connect_to_region(region, secrets)
    avail_amis = conn.get_all_images(
        filters={"tag:moz-type": moz_instance_type})
    last_ami = sorted(avail_amis,
                      key=lambda ami: ami.tags.get("moz-created"))[-1]
    return last_ami


def aws_watch_pending(dburl, regions, secrets, builder_map, region_priorities,
                      spot_limits, dryrun, cached_cert_dir):
    # First find pending jobs in the db
    db = sa.create_engine(dburl)
    pending = find_pending(db)

    # Mapping of instance types to # of instances we want to creates
    to_create_ondemand = defaultdict(int)
    to_create_spot = defaultdict(int)
    # Then match them to the builder_map
    for pending_buildername, brid in pending:
        for buildername_exp, instance_type in builder_map.items():
            if re.match(buildername_exp, pending_buildername):
                if find_retries(db, brid) == 0:
                    to_create_spot[instance_type] += 1
                else:
                    to_create_ondemand[instance_type] += 1
                break
        else:
            log.debug("%s has pending jobs, but no instance types defined",
                      pending_buildername)

    for instance_type, count in to_create_spot.items():
        log.debug("need %i spot %s", count, instance_type)
        started = request_spot_instances(
            moz_instance_type=instance_type, start_count=count,
            regions=regions, secrets=secrets,
            region_priorities=region_priorities, spot_limits=spot_limits,
            dryrun=dryrun, cached_cert_dir=cached_cert_dir)
        count -= started
        log.info("%s - started %i spot instances; need %i",
                 instance_type, started, count)

        # Add leftover to ondemand
        to_create_ondemand[instance_type] += count

    for instance_type, count in to_create_ondemand.items():
        log.debug("need %i ondemand %s", count, instance_type)
        if count < 1:
            continue

        # Check for stopped instances in the given regions and start them if
        # there are any
        started = aws_resume_instances(instance_type, count, regions, secrets,
                                       region_priorities, dryrun)
        count -= started
        log.info("%s - started %i instances; need %i",
                 instance_type, started, count)

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
    parser.add_argument("--cached-cert-dir", required=True,
                        help="Directory for cached puppet certificates")
    parser.add_argument("-n", "--dryrun", dest="dryrun", action="store_true",
                        help="don't actually do anything")

    args = parser.parse_args()

    logging.basicConfig(level=args.loglevel,
                        format="%(asctime)s - %(message)s")
    logging.getLogger("boto").setLevel(logging.INFO)
    logging.getLogger("requests").setLevel(logging.WARN)

    config = json.load(args.config)
    secrets = json.load(args.secrets)

    aws_watch_pending(
        dburl=secrets['db'],
        regions=args.regions,
        secrets=secrets,
        builder_map=config['buildermap'],
        region_priorities=config['region_priorities'],
        dryrun=args.dryrun,
        spot_limits=config.get("spot_limits"),
        cached_cert_dir=args.cached_cert_dir
    )
