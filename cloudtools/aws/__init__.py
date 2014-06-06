import os
import logging
import time
import calendar
import iso8601
from boto.ec2 import connect_to_region
from boto.vpc import VPCConnection
from repoze.lru import lru_cache
from fabric.api import run

log = logging.getLogger(__name__)
AMI_CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "../../ami_configs")
INSTANCE_CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "../../configs")
DEFAULT_REGIONS = ['us-east-1', 'us-west-2']


@lru_cache(10)
def get_aws_connection(region):
    """Connect to an EC2 region. Caches connection objects"""
    return connect_to_region(region)


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
        except:
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
        except:
            log.debug('hit error waiting for volume to be attached')
            time.sleep(10)
    while True:
        try:
            volume.update()
            if volume.status == 'in-use':
                if run('ls %s' % internal_dev_name).succeeded:
                    break
        except:
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
    cloud_init_config = os.path.join(INSTANCE_CONFIGS_DIR,
                                     "%s.cloud-init" % moz_instance_type)
    try:
        with open(cloud_init_config) as f:
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


def aws_get_spot_instances(instances):
    return [i for i in instances if i.spot_instance_request_id]


def aws_get_ondemand_instances(instances):
    return [i for i in instances if i.spot_instance_request_id is None]


def aws_get_fresh_instances(instances, launched_since):
    """Returns a list of instances that were launched since `launched_since` (a
    timestamp)"""
    retval = []
    for i in instances:
        d = iso8601.parse_date(i.launch_time)
        t = calendar.timegm(d.utctimetuple())
        if t > launched_since:
            retval.append(i)
    return retval
