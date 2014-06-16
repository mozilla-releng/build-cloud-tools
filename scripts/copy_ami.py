#!/usr/bin/env python
import argparse
import logging
import os
import site

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import get_aws_connection
from cloudtools.aws.ami import copy_ami

log = logging.getLogger(__name__)


def main():
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    log.setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--from-region", required=True,
                        help="Region to copy from")
    parser.add_argument("-t", "--to-region", action="append", required=True,
                        dest="to_regions", help="Regions to copy to")
    parser.add_argument("amis", metavar="AMI", nargs="+",
                        help="AMI IDs to be copied")
    args = parser.parse_args()

    conn_from = get_aws_connection(args.from_region)
    amis_to_copy = conn_from.get_all_images(image_ids=args.amis)
    for ami in amis_to_copy:
        for r in args.to_regions:
            log.info("Copying %s (%s) to %s", ami.id, ami.tags.get("Name"), r)
            new_ami = copy_ami(ami, r)
            log.info("New AMI created. AMI ID: %s", new_ami.id)

if __name__ == '__main__':
    main()
