#!/usr/bin/env python

import argparse
import json
import logging
from boto.ec2 import connect_to_region

REGIONS = ['us-east-1', 'us-west-2']


if __name__ == '__main__':
    log = logging.getLogger(__name__)
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

        impaired = conn.get_all_instance_status(
            filters={'instance-status.status': 'impaired'})
        if impaired:
            impaired_ids = [i.id for i in impaired]
            res = conn.get_all_instances(instance_ids=impaired_ids)
            instances = reduce(lambda a, b: a + b, [r.instances for r in res])
            log.info("Rebooting the following instances:")
            for name in (i.tags.get('Name', i.id) for i in instances):
                log.info(name)
            conn.reboot_instances(impaired_ids)
