from boto.ec2 import connect_to_region
from datetime import datetime, timedelta
import logging

log = logging.getLogger(__name__)


_spot_cache = {}


def get_current_spot_prices(connection, product_description, start_time=None, instance_type=None, ignore_cache=False):
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
        log.debug("returning cached results")
        return _spot_cache[cache_key]

    if not start_time:
        # Default to 24 hours
        now = datetime.utcnow()
        yesterday = now - timedelta(hours=24)
        start_time = yesterday.isoformat() + "Z"

    while True:
        log.debug("getting spot prices for instance_type %s from %s (next_token %s)", instance_type, start_time, next_token)
        all_prices = connection.get_spot_price_history(
            product_description=product_description,
            instance_type=instance_type,
            start_time=start_time,
            next_token=next_token,
        )
        next_token = all_prices.next_token
        # make sure to sort them by the timestamp, so we don't process the same
        # entry twice
        all_prices = sorted(all_prices, key=lambda x: x.timestamp, reverse=True)
        log.debug("got %i results", len(all_prices))
        for price in all_prices:
            az = price.availability_zone
            inst_type = price.instance_type
            if not current_prices.get(inst_type):
                current_prices[inst_type] = {}
            if not current_prices[inst_type].get(az):
                current_prices[inst_type][az] = price.price
        if not next_token:
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
        return self.current_price / self.performance_constant

    def __cmp__(self, other):
        return cmp(self.value, other.value)


def decide(connections, rules, product_description, start_time=None, instance_type=None):
    choices = []
    prices = {}
    for connection in connections:
        prices.update(get_current_spot_prices(connection, product_description, start_time, instance_type))
    for rule in rules:
        instance_type = rule["instance_type"]
        bid_price = rule["bid_price"]
        performance_constant = rule["performance_constant"]
        for region, region_prices in prices.iteritems():
            for az, price in region_prices.get(instance_type, {}).iteritems():
                if price > bid_price:
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

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    logging.getLogger("boto").setLevel(logging.INFO)
    connections = []
    for region in ['us-west-2', 'us-east-1']:
        # FIXME: user secrets
        connections.append(connect_to_region(region))
    rules = [
        {
            "instance_type": "m3.large",
            "performance_constant": 0.5,
            "bid_price": 0.10
        },
        {
            "instance_type": "c3.xlarge",
            "performance_constant": 1,
            "bid_price": 0.25
        },
        {
            "instance_type": "m3.xlarge",
            "performance_constant": 1.1,
            "bid_price": 0.25
        },
        {
            "instance_type": "m3.2xlarge",
            "performance_constant": 1.4,
            "bid_price": 0.25
        },
        {
            "instance_type": "c3.2xlarge",
            "performance_constant": 1.5,
            "bid_price": 0.25
        },
    ]
    ret = decide(connections, rules)
    print "\n".join(map(str, ret))
