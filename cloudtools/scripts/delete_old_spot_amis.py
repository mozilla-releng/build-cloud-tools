#!/usr/bin/env python
import argparse
import json
import logging

from cloudtools.aws import DEFAULT_REGIONS, INSTANCE_CONFIGS_DIR
from cloudtools.aws.ami import delete_old_amis

log = logging.getLogger(__name__)


def main():
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", dest="regions", action="append",
                        help="optional list of regions")
    parser.add_argument("-c", "--config", dest="configs",
                        action="append", required=True,
                        help="Instance config names")
    parser.add_argument("--keep-last", type=int, default=10,
                        help="Keep last N AMIs, delete others")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    args = parser.parse_args()

    regions = args.regions
    if not regions:
        regions = DEFAULT_REGIONS

    for r in regions:
        log.info("Working in %s", r)
        for cfg in args.configs:
            log.info("Processing %s", cfg)
            moz_type_config = json.load(
                open("%s/%s" % (INSTANCE_CONFIGS_DIR, cfg)))[r]
            for root_device_type in ("ebs", "instance-store"):
                delete_old_amis(region=r, tags=moz_type_config["tags"],
                                keep_last=args.keep_last,
                                root_device_type=root_device_type,
                                dry_run=args.dry_run)


if __name__ == '__main__':
    main()
