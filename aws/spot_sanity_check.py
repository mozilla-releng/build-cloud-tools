#!/usr/bin/env python

import argparse
import json
import logging
from boto.ec2 import connect_to_region

log = logging.getLogger(__name__)
REGIONS = ['us-east-1', 'us-west-2']

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", "--secrets", type=argparse.FileType('r'),
                        help="optional file where secrets can be found")
    parser.add_argument("-r", "--region", dest="regions", action="append",
                        help="optional list of regions")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Supress logging messages")

    args = parser.parse_args()
    if args.secrets:
        secrets = json.load(args.secrets)
    else:
        secrets = None

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.quiet:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.ERROR)

    if not args.regions:
        args.regions = REGIONS
    for region in args.regions:
        if secrets:
            conn = connect_to_region(
                region,
                aws_access_key_id=secrets['aws_access_key_id'],
                aws_secret_access_key=secrets['aws_secret_access_key']
            )
        else:
            conn = connect_to_region(region)

        spot_requests = conn.get_all_spot_instance_requests() or []
        for req in spot_requests:
            if req.state == "open" and req.status.code == "price-too-low":
                log.warning("Cancelling price-too-low request %s", req)
                req.cancel()
