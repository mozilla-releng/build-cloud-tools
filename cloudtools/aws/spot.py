import logging
from cloudtools.aws import get_aws_connection

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


def get_spot_instances(region, state="running"):
    log.info("Processing region %s", region)
    conn = get_aws_connection(region)
    filters = {
        'instance-lifecycle': 'spot',
        'instance-state-name': state,
    }
    return conn.get_only_instances(filters=filters)
