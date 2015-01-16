#!/usr/bin/env python

import argparse
import logging
import time

from cloudtools.aws import get_aws_connection, DEFAULT_REGIONS, \
    parse_aws_time, aws_get_all_instances
from cloudtools.aws.spot import CANCEL_STATUS_CODES, IGNORABLE_STATUS_CODES

log = logging.getLogger(__name__)


def sanity_check(regions):
    spot_requests = []
    for r in regions:
        conn = get_aws_connection(r)
        region_spot_requests = conn.get_all_spot_instance_requests()
        if region_spot_requests:
            spot_requests.extend(region_spot_requests)
    all_spot_instances = aws_get_all_instances(regions)
    instance_ids = [i.id for i in all_spot_instances]

    for req in spot_requests:
        if req.state in ["open", "failed"]:
            if req.status.code in CANCEL_STATUS_CODES:
                log.info("Cancelling request %s", req)
                req.add_tag("moz-cancel-reason", req.status.code)
                req.cancel()
            elif req.status.code not in IGNORABLE_STATUS_CODES:
                log.error("Uknown status for request %s: %s", req,
                          req.status.code)
        # Cancel all active request older than 30 mins without runing instances
        elif req.state == "active" and \
                parse_aws_time(req.create_time) + 30 * 60 < time.time() and \
                req.instance_id not in instance_ids:
            log.info("Cancelling request %s: %s is not running", req,
                     req.instance_id)
            req.add_tag("moz-cancel-reason", "no-running-instances")
            req.cancel()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", dest="regions", action="append",
                        help="optional list of regions")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Supress logging messages")

    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.quiet:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.WARNING)

    regions = args.regions or DEFAULT_REGIONS
    sanity_check(regions)

if __name__ == '__main__':
    main()
