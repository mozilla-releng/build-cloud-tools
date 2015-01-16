#!/usr/bin/env python
import argparse
import logging

from cloudtools.aws.ami import get_ami, copy_ami

log = logging.getLogger(__name__)


def main():
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    log.setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--from-region", required=True,
                        help="Region to copy from")
    parser.add_argument("-t", "--to-region", action="append", required=True,
                        dest="to_regions", help="Regions to copy to")
    parser.add_argument("moz_instance_types", metavar="moz_type", nargs="+",
                        help="moz_instance_types to be copied")
    args = parser.parse_args()

    amis_to_copy = [get_ami(region=args.from_region, moz_instance_type=t)
                    for t in args.moz_instance_types]
    for ami in amis_to_copy:
        for r in args.to_regions:
            log.info("Copying %s (%s) to %s", ami.id, ami.tags.get("Name"), r)
            new_ami = copy_ami(ami, r)
            log.info("New AMI created. AMI ID: %s", new_ami.id)

if __name__ == '__main__':
    main()
