import os
import logging
import time
import calendar
import iso8601
import json
from redo import retrier
from boto.ec2 import connect_to_region
from boto.vpc import VPCConnection
from boto.s3.connection import S3Connection
from boto.exception import BotoServerError
from repoze.lru import lru_cache
from fabric.api import run

log = logging.getLogger(__name__)
AMI_CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "../../ami_configs")
INSTANCE_CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "../../configs")
DEFAULT_REGIONS = ['us-east-1', 'us-west-2']

# Number of seconds from an instance's launch time for it to be considered
# 'fresh'
FRESH_INSTANCE_DELAY = 20 * 60


@lru_cache(10)
def get_aws_connection(region):
    """Connect to an EC2 region. Caches connection objects"""
    return connect_to_region(region)


@lru_cache(10)
def get_s3_connection():
    """Connect to S3. Caches connection objects"""
    return S3Connection()


@lru_cache(10)
def get_vpc(region):
    conn = get_aws_connection(region)
    return VPCConnection(region=conn.region)


def wait_for_status(obj, attr_name, attr_value, update_method):
    log.debug("waiting for %s availability", obj)
    while True:
        try:
            getattr(obj, update_method)()
            if getattr(obj, attr_name) == attr_value:
                break
            else:
                time.sleep(1)
        except:  # noqa: E722
            log.exception('hit error waiting')
            time.sleep(10)


def attach_and_wait_for_volume(volume, aws_dev_name, internal_dev_name,
                               instance_id):
    """Attach a volume to an instance and wait until it is available"""
    wait_for_status(volume, "status", "available", "update")
    while True:
        try:
            volume.attach(instance_id, aws_dev_name)
            break
        except:  # noqa: E722
            log.debug('hit error waiting for volume to be attached')
            time.sleep(10)
    while True:
        try:
            volume.update()
            if volume.status == 'in-use':
                if run('ls %s' % internal_dev_name).succeeded:
                    break
        except:  # noqa: E722
            log.debug('hit error waiting for volume to be attached')
            time.sleep(10)


def mount_device(device, mount_point):
    run('mkdir -p "%s"' % mount_point)
    run('mount "{device}" "{mount_point}"'.format(device=device,
                                                  mount_point=mount_point))


def name_available(conn, name):
    res = conn.get_all_instances()
    instances = reduce(lambda a, b: a + b, [r.instances for r in res])
    names = [i.tags.get("Name") for i in instances if i.state != "terminated"]
    if name in names:
        return False
    else:
        return True


def parse_aws_time(t):
    """Parses ISO8601 time format and returns local epoch time"""
    t = calendar.timegm(time.strptime(t[:19], '%Y-%m-%dT%H:%M:%S'))
    return t


def aws_time_to_datetime(t):
    return iso8601.parse_date(t)


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
            region_instances = conn.get_only_instances()
            log.debug("aws_get_running_instances - caching %s", region)
            _aws_instances_cache[region] = region_instances
            retval.extend(region_instances)
    return retval


@lru_cache(10)
def get_user_data_tmpl(moz_instance_type):
    user_data_tmpl = os.path.join(INSTANCE_CONFIGS_DIR,
                                  "%s.user-data" % moz_instance_type)
    try:
        with open(user_data_tmpl) as f:
            return f.read()
    except Exception:
        return None


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


def filter_spot_instances(instances):
    return [i for i in instances if i.spot_instance_request_id]


def filter_ondemand_instances(instances):
    return [i for i in instances if i.spot_instance_request_id is None]


def filter_instances_launched_since(instances, launched_since):
    """Returns a list of instances that were launched since `launched_since` (a
    timestamp)"""
    retval = []
    for i in instances:
        d = iso8601.parse_date(i.launch_time)
        t = calendar.timegm(d.utctimetuple())
        if t > launched_since:
            retval.append(i)
    return retval


def aws_get_fresh_instances(instances):
    since = time.time() - FRESH_INSTANCE_DELAY
    return filter_instances_launched_since(instances, since)


def reduce_by_freshness(count, instances, moz_instance_type):
    fresh = aws_get_fresh_instances(instances)
    num_fresh = len(fresh)
    log.debug("%i running (%i fresh)", len(instances), num_fresh,)
    # TODO: This logic is probably too simple
    # Reduce the number of required slaves by the number of freshly
    # started instaces, plus 10% of those that have been running a
    # while
    reduce_by = num_fresh
    num_old = len(instances) - num_fresh
    reduce_by += num_old / 10
    # log.debug("reducing required count for %s %s %s "
    log.debug("reducing required count for %s by %i (need: %i, running: %i) ",
              moz_instance_type, reduce_by, count, len(instances))
    return max(0, count - reduce_by)


def distribute_in_region(count, regions, region_priorities):
    """Distributes a number accordong to priorities.
    Returns a dictionary keyed by region."""
    rv = {}
    # filter out not used regions
    region_priorities = dict((k, v) for k, v in region_priorities.iteritems()
                             if k in regions)
    mass = sum(region_priorities.values())
    for r in regions:
        if r not in region_priorities:
            continue
        rv[r] = count * region_priorities[r] / mass
    # rounding leftower goes to the region with highest priority
    total = sum(rv.values())
    if count - total > 0:
        best_region = sorted(region_priorities.items(), key=lambda i: i[1],
                             reverse=True)[0][0]
        rv[best_region] += count - total
    return rv


@lru_cache(10)
def load_instance_config(moz_instance_type):
    return json.load(open(os.path.join(INSTANCE_CONFIGS_DIR,
                                       moz_instance_type)))


def get_buildslave_instances(region, moz_types):
    # Look for running `moz_types` instances with moz-state=ready
    conn = get_aws_connection(region)
    instances = conn.get_only_instances(filters={
        'tag:moz-state': 'ready',
        'instance-state-name': 'running',
    })

    retval = []
    for i in instances:
        if i.tags.get("moz-type") in moz_types and \
                i.tags.get("moz-state") == "ready" and \
                not i.tags.get("moz-loaned-to"):
            retval.append(i)

    return retval


def get_impaired_instance_ids(region):
    conn = get_aws_connection(region)
    impaired = conn.get_all_instance_status(
        filters={'instance-status.status': 'impaired'})
    return [i.id for i in impaired]


def get_region_dns_atom(region):
    """Maps AWS regions to region names used by Mozilla in DNS names"""
    mapping = {
        "us-east-1": "use1",
        "us-west-1": "usw1",
        "us-west-2": "usw2",
    }
    return mapping.get(region)


def retry_aws_request(callable, *args, **kwargs):
    """Calls callable(*args, **kwargs), and sleeps/retries on
    RequestLimitExceeded errors"""
    for _ in retrier():
        try:
            return callable(*args, **kwargs)
        except BotoServerError, e:
            if e.code == 'RequestLimitExceeded':
                # Try again
                log.debug("Got RequestLimitExceeded; retrying", exc_info=True)
                continue
            # Otherwise re-raise
            raise
    else:
        raise Exception("Exceeded retries")
