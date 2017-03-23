import logging
import boto
from datetime import datetime, timedelta
from repoze.lru import lru_cache
from . import get_aws_connection, aws_time_to_datetime, retry_aws_request
from ..slavealloc import get_classified_slaves

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
_spot_cache = {}
_spot_requests = {}


def populate_spot_requests_cache(region, request_ids=None):
    log.debug("Caching spot requests in %s", region)
    kwargs = {}
    if request_ids:
        kwargs["request_ids"] = request_ids
    conn = get_aws_connection(region)
    try:
        reqs = conn.get_all_spot_instance_requests(**kwargs)
    except boto.exception.EC2ResponseError:
        log.debug("Some of the requests not found, requesting all")
        reqs = conn.get_all_spot_instance_requests()
    for req in reqs:
        _spot_requests[region, req.id] = req


def get_spot_request(region, request_id):
    if (region, request_id) in _spot_requests:
        return _spot_requests[region, request_id]
    populate_spot_requests_cache(region)
    return _spot_requests.get((region, request_id))


def get_spot_instances(region, state="running"):
    log.info("Processing region %s", region)
    conn = get_aws_connection(region)
    filters = {
        'instance-lifecycle': 'spot',
        'instance-state-name': state,
    }
    return conn.get_only_instances(filters=filters)


def get_instances_to_tag(region):
    rv = []
    log.debug("Getting all spot instances in %s...", region)
    all_spot_instances = get_spot_instances(region)
    log.debug("Total %s instances found", len(all_spot_instances))
    for i in all_spot_instances:
        name = i.tags.get('Name')
        fqdn = i.tags.get('FQDN')
        moz_type = i.tags.get('moz-type')
        moz_state = i.tags.get('moz-state')
        # If one of the tags is unset/empty
        if not all([name, fqdn, moz_type, moz_state]):
            log.debug("Adding %s in %s to queue", i, region)
            rv.append(i)
    log.debug("Done with %s", region)
    return rv


def copy_spot_request_tags(i):
    log.debug("Tagging %s", i)
    req = get_spot_request(i.region.name, i.spot_instance_request_id)
    if not req:
        log.debug("Cannot find spot request for %s", i)
        return
    tags = {}
    for tag_name, tag_value in sorted(req.tags.iteritems()):
        if tag_name not in i.tags:
            log.info("Adding '%s' tag with '%s' value to %s", tag_name,
                     tag_value, i)
            tags[tag_name] = tag_value
    tags["moz-state"] = "ready"
    retry_aws_request(i.connection.create_tags, [i.id], tags)


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
    delta = timedelta(minutes=minutes)
    recent_spot_requests = []
    for r in spot_requests:
        t = aws_time_to_datetime(r.status.update_time)
        tz = t.tzinfo
        now = datetime.now(tz)
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


def get_available_slave_name(region, moz_instance_type, is_spot,
                             all_instances):
    key = (region, moz_instance_type, is_spot)
    if key in _avail_slave_names:
        # cached entry
        if not _avail_slave_names[key]:
            return None

        usable = _avail_slave_names[key]
        if not usable:
            return None
        name = usable.pop()
        _avail_slave_names[key].discard(name)
        return name
    else:
        # populate cache and call again
        all_slave_names = get_classified_slaves(is_spot)
        all_used_names = set(i.tags.get("Name") for i in all_instances if
                             i.state != 'terminated')
        # used_spot_names contains pending too
        used_spot_names = set(r.tags.get("Name") for r in
                              get_active_spot_requests(region))
        used_names = all_used_names.union(used_spot_names)
        _avail_slave_names[key] = all_slave_names[moz_instance_type][region] -\
            used_names
        return get_available_slave_name(region, moz_instance_type,
                                        is_spot, all_instances)


def get_current_spot_prices(connection, product_description, start_time=None,
                            instance_type=None, ignored_availability_zones=None,
                            ignore_cache=False):
    """
    Get the current spot prices for the region associated with the given
    connection. This may return cached results. Pass ignore_cache=True to
    bypass the cache

    Args:
        connection (boto.ec2.Connection): connection to a region
        product_description (str): which products to restrict the spot prices
            for, e.g. "Linux/UNIX (Amazon VPC)"
        start_time (iso8601 str): get spot prices starting from this time
        instance_type (str): restrict results to this instance type, e.g.
            "m1.medium"
        ignored_availability_zones (list of str): zones where we don't try to get a price
        ignore_cache (bool): ignore cached results

    Returns:
        A dict mapping region to a mapping of instance type to a mapping of
        availability zone to price. (phew!)
        For example:
            {'us-east-1': {'m1.medium': {'us-east-1a': 0.01}}}

    """
    next_token = None
    region = connection.region.name
    current_prices = {}
    cache_key = (region, product_description, start_time, instance_type)
    if not ignore_cache and cache_key in _spot_cache:
        log.debug("using cached pricing for %s in %s", instance_type, region)
        return _spot_cache[cache_key]

    if not start_time:
        # Default to 24 hours
        now = datetime.utcnow()
        yesterday = now - timedelta(hours=24)
        start_time = yesterday.isoformat() + "Z"

    if ignored_availability_zones is None:
        ignored_availability_zones = []
    all_zones = set([az.name for az in connection.get_all_zones()])
    useful_zones = all_zones - set(ignored_availability_zones)
    remaining = useful_zones
    log.debug("getting spot prices for instance_type %s in %s, from %s",
              instance_type, sorted(remaining), start_time)
    while remaining:
        all_prices = connection.get_spot_price_history(
            product_description=product_description,
            instance_type=instance_type,
            start_time=start_time,
            max_results=50,
            next_token=next_token,
        )
        next_token = all_prices.next_token
        # make sure to sort them by the timestamp, so we don't process the same
        # entry twice
        all_prices = sorted(all_prices, key=lambda x: x.timestamp,
                            reverse=True)
        for price in all_prices:
            az = price.availability_zone
            if az not in remaining:
                continue
            inst_type = price.instance_type
            if not current_prices.get(inst_type):
                current_prices[inst_type] = {}
            if not current_prices[inst_type].get(az):
                current_prices[inst_type][az] = price.price
                remaining.remove(az)

        if remaining:
            log.debug("getting more prices for %s", sorted(remaining))
        if not next_token:
            log.debug("ran out of prices, need an earlier start time than %s",
                      start_time)
            break

    retval = {region: current_prices}
    _spot_cache[cache_key] = retval
    return retval


class Spot:
    def __init__(self, instance_type, region, availability_zone, current_price,
                 bid_price, performance_constant):
        self.instance_type = instance_type
        self.region = region
        self.availability_zone = availability_zone
        self.current_price = current_price
        self.bid_price = bid_price
        self.performance_constant = performance_constant

    def __repr__(self):
        return "%s (%s, %s) %g (value: %g) < %g" % (
            self.instance_type, self.region, self.availability_zone,
            self.current_price, self.value, self.bid_price)

    def __str__(self):
        return self.__repr__()

    def __hash__(self):
        return hash(self.__repr__())

    @property
    def value(self):
        return self.current_price / float(self.performance_constant)

    def __cmp__(self, other):
        return cmp(self.value, other.value)


def get_spot_choices(connections, rules, product_description, start_time=None):
    choices = []
    prices = {}
    for rule in rules:
        instance_type = rule["instance_type"]
        bid_price = rule["bid_price"]
        performance_constant = rule["performance_constant"]
        ignored_availability_zones = rule.get("ignored_azs", [])
        for connection in connections:
            prices.update(get_current_spot_prices(connection, product_description,
                                                  start_time, instance_type,
                                                  ignored_availability_zones))

        for region, region_prices in prices.iteritems():
            for az, price in region_prices.get(instance_type, {}).iteritems():
                if az in ignored_availability_zones:
                    log.debug("Ignoring AZ %s for %s because it is listed in "
                              " ignored_azs: %s", az, instance_type,
                              ignored_availability_zones)
                    continue
                if price > bid_price * 0.8:
                    log.debug("%s (in %s) too expensive for %s", price, az,
                              instance_type)
                else:
                    choices.append(
                        Spot(instance_type=instance_type, region=region,
                             availability_zone=az, current_price=price,
                             bid_price=bid_price,
                             performance_constant=performance_constant))
    # sort by self.value
    choices.sort()
    return choices
