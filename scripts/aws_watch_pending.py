#!/usr/bin/env python
"""
Watches pending jobs and starts or creates EC2 instances if required
"""
import re
import time
import random
from collections import defaultdict
import calendar
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
import iso8601
import requests
from bid import decide as get_spot_choices

import site
site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))

from cloudtools.aws import get_aws_connection, INSTANCE_CONFIGS_DIR
from cloudtools.aws.spot import get_spot_requests_for_moztype, usable_spot_choice

log = logging.getLogger()

# Number of job retries allowed to run on spot instances. We stop using spot
# instances if number of retires a larger than this number. If you update this
# number, you also need to update the same viariable in buildbotcustom/misc.py
MAX_SPOT_RETRIES = 1

# Number of seconds from an instance's launch time for it to be considered
# 'fresh'
FRESH_INSTANCE_DELAY = 20 * 60


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


_aws_instances_cache = {}


def aws_get_all_instances(regions):
    """
    Returns a list of all instances in the given regions
    """
    log.debug("fetching all instances for %s", regions)
    retval = []
    for region in regions:
        if region in _aws_instances_cache:
            log.debug("aws_get_all_instances - cache hit for %s", region)
            retval.extend(_aws_instances_cache[region])
        else:
            conn = get_aws_connection(region)
            reservations = conn.get_all_instances()
            region_instances = []
            for r in reservations:
                region_instances.extend(r.instances)
            log.debug("aws_get_running_instances - caching %s", region)
            _aws_instances_cache[region] = region_instances
            retval.extend(region_instances)
    return retval


def aws_filter_instances(instances, state=None, tags=None):
    retval = []
    for i in instances:
        matched = True
        if state and i.state != state:
            matched = False
            continue
        if tags:
            for k, v in tags.items():
                if i.tags.get(k) != v:
                    matched = False
                    continue
        if i.tags.get("moz-loaned-to"):
            # Skip loaned instances
            matched = False
            continue
        if matched:
            retval.append(i)
    return retval


def aws_get_running_instances(instances, moz_instance_type):
    retval = []
    for i in instances:
        if i.state != 'running':
            continue
        if i.tags.get('moz-type') != moz_instance_type:
            continue
        if i.tags.get('moz-state') != 'ready':
            continue
        retval.append(i)

    return retval


def aws_get_slaveset_instances(instances, slaveset):
    if not slaveset:
        allocated_slaves = get_allocated_slaves(None)

    retval = []
    if not slaveset:
        allocated_slaves = get_allocated_slaves(None)

    for i in instances:
        if slaveset:
            if i.tags.get('Name') in slaveset:
                retval.append(i)
        elif i.tags.get('Name') not in allocated_slaves:
            retval.append(i)

    return retval


def aws_get_spot_instances(instances):
    return [i for i in instances if i.spot_instance_request_id]


def aws_get_ondemand_instances(instances):
    return [i for i in instances if i.spot_instance_request_id is None]


def aws_get_fresh_instances(instances, launched_since):
    "Returns a list of instances that were launched since `launched_since` (a timestamp)"
    retval = []
    for i in instances:
        d = iso8601.parse_date(i.launch_time)
        t = calendar.timegm(d.utctimetuple())
        if t > launched_since:
            retval.append(i)
    return retval


def aws_get_reservations(regions):
    """
    Return a mapping of (availability zone, ec2 instance type) -> count
    """
    log.debug("getting reservations for %s", regions)
    retval = {}
    for region in regions:
        conn = get_aws_connection(region)
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
                         region_priorities, instance_type_changes, dryrun,
                         slaveset):
    """Resume up to `start_count` stopped instances of the given type in the
    given regions"""
    # Fetch all our instance information
    all_instances = aws_get_all_instances(regions)

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

    # Get our current reservations
    reservations = aws_get_reservations(regions)
    log.debug("current reservations: %s", reservations)

    # Get our currently running instances
    running_instances = aws_filter_instances(all_instances, state='running')

    # Filter the reservations
    aws_filter_reservations(reservations, running_instances)
    log.debug("filtered reservations: %s", reservations)

    # List of (instance, is_reserved) tuples
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
            log.info("%s - %s - would start %s", i.placement, i.tags['Name'],
                     r)
            started += 1
        if started >= start_count:
            log.debug("Started %s instaces, breaking early", started)
            break

    return started


def request_spot_instances(moz_instance_type, start_count, regions, secrets,
                           region_priorities, spot_config, dryrun,
                           cached_cert_dir, slaveset):
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
    active_network_ids = {}
    for region in regions:
        # Check if spots are enabled in this region for this type
        region_limit = spot_config.get("limits", {}).get(region, {}).get(
            moz_instance_type)
        if not region_limit:
            log.debug("No spot limits defined for %s in %s, skipping...",
                      moz_instance_type, region)
            continue

        # check the limits
        # Count how many unique network interfaces are active
        # Sometimes we have multiple requests for the same interface
        active_requests = get_spot_requests_for_moztype(region=region, moz_instance_type=moz_instance_type)
        active_network_ids[region] = set(r.launch_specification.networkInterfaceId for r in active_requests)
        active_count = len(active_network_ids[region])
        log.debug("%s: %i active network interfaces for spot requests in %s", moz_instance_type, active_count, region)
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
            region=region, secrets=secrets,
            moz_instance_type=moz_instance_type,
            ami=to_start[region]["ami"],
            instance_config=instance_config, dryrun=dryrun,
            cached_cert_dir=cached_cert_dir,
            spot_choice=choice,
            slaveset=slaveset,
            active_network_ids=active_network_ids[region],
        )
        started += launched

        if started >= start_count:
            break

    return started


def get_puppet_certs(ip, secrets, cached_cert_dir):
    """ reuse or generate certificates"""
    cert_file = os.path.join(cached_cert_dir, ip)
    if os.path.exists(cert_file):
        cert = open(cert_file).read()
        # Make shure that the file is not empty
        if cert:
            return cert

    puppet_server = secrets["getcert_server"]
    url = "https://%s/deploy/getcert.cgi?%s" % (puppet_server, ip)
    auth = (secrets["deploy_username"], secrets["deploy_password"])
    req = requests.get(url, auth=auth, verify=False)
    req.raise_for_status()
    cert_data = req.content
    if not cert_data:
        raise RuntimeError("Cannot retrieve puppet cert")
    with open(cert_file, "wb") as f:
        f.write(cert_data)
    return cert_data


def do_request_spot_instances(amount, region, secrets, moz_instance_type, ami,
                              instance_config, cached_cert_dir, spot_choice,
                              slaveset, active_network_ids, dryrun):
    started = 0
    for _ in range(amount):
        try:
            r = do_request_spot_instance(
                region=region, secrets=secrets,
                moz_instance_type=moz_instance_type,
                price=spot_choice.bid_price,
                availability_zone=spot_choice.availability_zone,
                ami=ami, instance_config=instance_config,
                cached_cert_dir=cached_cert_dir,
                instance_type=spot_choice.instance_type, slaveset=slaveset,
                active_network_ids=active_network_ids, dryrun=dryrun)
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


def do_request_spot_instance(region, secrets, moz_instance_type, price, ami,
                             instance_config, cached_cert_dir, instance_type,
                             availability_zone, slaveset, active_network_ids, dryrun):
    conn = get_aws_connection(region)
    interface = get_available_interface(
        conn=conn, moz_instance_type=moz_instance_type,
        availability_zone=availability_zone,
        slaveset=slaveset,
        active_network_ids=active_network_ids)
    if not interface:
        log.debug("No free network interfaces left in %s" % region)
        return False

    # TODO: check DNS
    fqdn = interface.tags.get("FQDN")
    if not fqdn:
        log.warn("interface %s has no FQDN", interface)
        return False

    log.debug("Spot request for %s (%s)", fqdn, price)

    if dryrun:
        log.info("Dry run. skipping")
        return True

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
    if instance_config[region].get("lvm"):
        user_data += """
mkdir -p /etc/lvm-init/
cat <<EOF > /etc/lvm-init/lvm-init.json
%s
EOF
/sbin/lvm-init
""" % json.dumps(instance_config[region])

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
    max_tries = 10
    for i in range(max_tries):
        try:
            sir[0].add_tag("moz-type", moz_instance_type)
            return True
        except EC2ResponseError, e:
            if e.code == "InvalidSpotInstanceRequestID.NotFound":
                if i < max_tries - 1:
                    # Try again
                    log.debug("waiting for spot request")
                    time.sleep(5)
                    continue
            raise

_cached_interfaces = {}


def get_available_interface(conn, moz_instance_type, availability_zone, slaveset, active_network_ids):
    global _cached_interfaces
    if not _cached_interfaces.get(availability_zone):
        _cached_interfaces[availability_zone] = {}
    if _cached_interfaces[availability_zone].get(moz_instance_type) is None:
        filters = {
            "status": "available",
            "tag:moz-type": moz_instance_type,
            "availability-zone": availability_zone,
        }
        avail_ifs = conn.get_all_network_interfaces(filters=filters)
        if avail_ifs:
            random.shuffle(avail_ifs)
        _cached_interfaces[availability_zone][moz_instance_type] = avail_ifs

    log.debug("%s interfaces in %s",
              len(_cached_interfaces[availability_zone][moz_instance_type]),
              availability_zone)
    if _cached_interfaces[availability_zone][moz_instance_type]:
        # Find one in our slaveset
        if slaveset:
            for i in _cached_interfaces[availability_zone][moz_instance_type]:
                if i.id in active_network_ids:
                    log.debug("skipping %s since it's active", i.id)
                    continue
                if i.tags.get("FQDN").split(".")[0] in slaveset:
                    _cached_interfaces[availability_zone][moz_instance_type].remove(i)
                    log.debug("using %s", i.tags.get("FQDN"))
                    return i
        else:
            allocated_slaves = get_allocated_slaves(None)
            for i in _cached_interfaces[availability_zone][moz_instance_type]:
                if i.id in active_network_ids:
                    log.debug("skipping %s since it's active", i.id)
                if i.tags.get("FQDN").split(".")[0] not in allocated_slaves:
                    _cached_interfaces[availability_zone][moz_instance_type].remove(i)
                    log.debug("using %s", i.tags.get("FQDN"))
                    return i
    return None


def get_ami(region, moz_instance_type):
    conn = get_aws_connection(region)
    avail_amis = conn.get_all_images(
        owners=["self"],
        filters={"tag:moz-type": moz_instance_type})
    last_ami = sorted(avail_amis,
                      key=lambda ami: ami.tags.get("moz-created"))[-1]
    return last_ami


JACUZZI_BASE_URL = "http://jacuzzi-allocator.pub.build.mozilla.org/v1"


_jacuzzi_allocated_cache = {}


def get_allocated_slaves(buildername):
    if buildername in _jacuzzi_allocated_cache:
        return _jacuzzi_allocated_cache[buildername]

    if buildername is None:
        log.debug("getting set of all allocated slaves")
        r = requests.get("{0}/allocated/all".format(JACUZZI_BASE_URL))
        _jacuzzi_allocated_cache[buildername] = frozenset(r.json()['machines'])
        return _jacuzzi_allocated_cache[buildername]

    log.debug("getting slaves allocated to %s", buildername)
    r = requests.get("{0}/builders/{1}".format(JACUZZI_BASE_URL, buildername))
    # Handle 404 specially
    if r.status_code == 404:
        _jacuzzi_allocated_cache[buildername] = None
        return None
    _jacuzzi_allocated_cache[buildername] = frozenset(r.json()['machines'])
    return _jacuzzi_allocated_cache[buildername]


def aws_watch_pending(dburl, regions, secrets, builder_map, region_priorities,
                      spot_config, ondemand_config, dryrun, cached_cert_dir,
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

    # Then match them to the builder_map
    for pending_buildername, brid in pending:
        for buildername_exp, moz_instance_type in builder_map.items():
            if re.match(buildername_exp, pending_buildername):
                slaveset = get_allocated_slaves(pending_buildername)
                log.debug("%s instance type %s slaveset %s", pending_buildername, moz_instance_type, slaveset)
                if find_retries(db, brid) > MAX_SPOT_RETRIES:
                    to_create_ondemand[moz_instance_type, slaveset] += 1
                else:
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
            fresh = aws_get_fresh_instances(running, time.time() - FRESH_INSTANCE_DELAY)
            log.info("%i running for %s %s %s (%i fresh)", len(running), create_type, moz_instance_type, slaveset, len(fresh))
            # TODO: This logic is probably too simple
            # Reduce the number of required slaves by the number of freshly
            # started instaces, plus 10% of those that have been running a
            # while
            num_fresh = len(fresh)
            num_old = len(running) - num_fresh
            delta = num_fresh + (num_old / 10)
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
            moz_instance_type=moz_instance_type, start_count=count,
            regions=regions, secrets=secrets,
            region_priorities=region_priorities, spot_config=spot_config,
            dryrun=dryrun, cached_cert_dir=cached_cert_dir,
            slaveset=slaveset)
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
        started = aws_resume_instances(moz_instance_type, count, regions, secrets,
                                       region_priorities,
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
    parser.add_argument("--cached-cert-dir", default="certs",
                        help="Directory for cached puppet certificates")
    parser.add_argument("-n", "--dryrun", dest="dryrun", action="store_true",
                        help="don't actually do anything")

    args = parser.parse_args()

    logging.basicConfig(level=args.loglevel,
                        format="%(asctime)s - %(levelname)s - %(message)s")
    logging.getLogger("boto").setLevel(logging.INFO)
    logging.getLogger("requests").setLevel(logging.WARN)
    logging.getLogger("iso8601").setLevel(logging.INFO)

    config = json.load(args.config)
    secrets = json.load(args.secrets)

    aws_watch_pending(
        dburl=secrets['db'],
        regions=args.regions,
        secrets=secrets,
        builder_map=config['buildermap'],
        region_priorities=config['region_priorities'],
        dryrun=args.dryrun,
        spot_config=config.get("spot"),
        ondemand_config=config.get("ondemand"),
        cached_cert_dir=args.cached_cert_dir,
        instance_type_changes=config.get("instance_type_changes", {})
    )
    log.debug("done")
