import logging
import datetime
from cloudtools.aws import get_aws_connection, aws_time_to_datetime
from cloudtools.slavealloc import get_slaves
from cloudtools.jacuzzi import get_allocated_slaves
from repoze.lru import lru_cache

CANCEL_STATUS_CODES = ["capacity-oversubscribed", "price-too-low",
                       "capacity-not-available"]
TERMINATED_BY_AWS_STATUS_CODES = [
    "instance-terminated-by-price",
    "instance-terminated-capacity-oversubscribed",
]
IGNORABLE_STATUS_CODES = CANCEL_STATUS_CODES + TERMINATED_BY_AWS_STATUS_CODES \
    + ["bad-parameters", "canceled-before-fulfillment", "fulfilled",
       "instance-terminated-by-user", "pending-evaluation",
       "pending-fulfillment"]

log = logging.getLogger(__name__)


@lru_cache(100)
def get_spot_request(region, request_id):
    log.debug("Getting spot request %s in %s", request_id, region)
    conn = get_aws_connection(region)
    req = conn.get_all_spot_instance_requests(request_ids=[request_id])
    if req:
        return req[0]
    else:
        return None


def get_spot_instances(region, state="running"):
    log.info("Processing region %s", region)
    conn = get_aws_connection(region)
    filters = {
        'instance-lifecycle': 'spot',
        'instance-state-name': state,
    }
    return conn.get_only_instances(filters=filters)


@lru_cache(10)
def get_active_spot_requests(region):
    """Gets open and active spot requests"""
    log.debug("getting all spot requests for %s", region)
    conn = get_aws_connection(region)
    spot_requests = conn.get_all_spot_instance_requests(
        filters={'state': ['open', 'active']})
    return spot_requests


@lru_cache(100)
def get_spot_requests(region, instance_type, availability_zone):
    log.debug("getting filtered spot requests for %s (%s)", availability_zone,
              instance_type)
    all_requests = get_active_spot_requests(region)
    retval = []
    if not all_requests:
        return retval

    for r in all_requests:
        if r.launch_specification.instance_type != instance_type:
            continue
        if r.launched_availability_zone != availability_zone:
            continue
        retval.append(r)
    return retval


def get_spot_requests_for_moztype(region, moz_instance_type):
    """retruns a list of all open and active spot requests"""
    req = get_active_spot_requests(region)
    return [r for r in req if r.tags.get('moz-type') == moz_instance_type]


@lru_cache(100)
def usable_spot_choice(choice, minutes=15):
    """Sanity check recent spot requests"""
    region = choice.region
    az = choice.availability_zone
    instance_type = choice.instance_type
    bid_price = choice.bid_price
    current_price = choice.current_price
    log.debug("Sanity checking %s in %s", instance_type, az)

    # if price is higher than 80% of the bid price do not use the choice
    if current_price > bid_price * 0.8:
        log.debug("Price is higher than 80%% of ours, %s", choice)
        return False

    spot_requests = get_spot_requests(region, instance_type, az)
    if not spot_requests:
        log.debug("No available spot requests in last %sm", minutes)
        return True
    # filter out requests older than 15 min
    # first, get the tzinfo of one of the requests
    delta = datetime.timedelta(minutes=minutes)
    recent_spot_requests = []
    for r in spot_requests:
        t = aws_time_to_datetime(r.status.update_time)
        tz = t.tzinfo
        now = datetime.datetime.now(tz)
        if t > now - delta:
            recent_spot_requests.append(r)

    if not recent_spot_requests:
        log.debug("No recent spot requests in last %sm", minutes)
        return True
    bad_statuses = CANCEL_STATUS_CODES + TERMINATED_BY_AWS_STATUS_CODES
    bad_req = [r for r in spot_requests
               if r.status.code in bad_statuses or
               r.tags.get("moz-cancel-reason") in bad_statuses]
    # Do not try if bad ratio is higher than 10%
    total = len(spot_requests)
    total_bad = len(bad_req)
    log.debug("Found %s recent, %s bad", total, total_bad)
    if float(total_bad / total) > 0.10:
        log.debug("Skipping %s, too many failures (%s out of %s)", choice,
                  total_bad, total)
        return False
    # All good!
    log.debug("Choice %s passes", choice)
    return True


_avail_slave_names = {}


def get_available_spot_slave_name(region, moz_instance_type, slaveset):
    key = (region, moz_instance_type)
    if key in _avail_slave_names:
        # cached entry
        if not _avail_slave_names[key]:
            return None

        if slaveset:
            usable = _avail_slave_names[key].intersection(slaveset)
        else:
            usable = _avail_slave_names[key] - set(get_allocated_slaves(None))
        if not usable:
            return None
        name = usable.pop()
        _avail_slave_names[key].discard(name)
        return name
    else:
        # populate cache and call again
        all_slaves = get_slaves()
        active_req = get_active_spot_requests(region)
        used_names = set(r.tags.get("Name") for r in active_req)
        _avail_slave_names[key] = all_slaves[moz_instance_type][region] - used_names
        return get_available_spot_slave_name(region, moz_instance_type,
                                             slaveset)
