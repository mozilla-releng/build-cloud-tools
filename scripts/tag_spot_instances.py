#!/usr/bin/env python

import argparse
import logging
import site
import os

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import get_aws_connection, get_vpc, DEFAULT_REGIONS
from cloudtools.aws.spot import get_spot_instances

log = logging.getLogger(__name__)


def tag_it(i):
    log.debug("Tagging %s", i)
    vpc = get_vpc(i.region.name)
    netif = i.interfaces[0]
    # network interface needs to be reloaded usin VPC to get the tags
    interface = vpc.get_all_network_interfaces(
        filters={"network-interface-id": netif.id})[0]
    # copy interface tags over
    for tag_name, tag_value in interface.tags.iteritems():
        log.info("Adding '%s' tag with '%s' value to %s", tag_name, tag_value,
                 i)
        i.add_tag(tag_name, tag_value)
    i.add_tag("moz-state", "ready")


if __name__ == '__main__':
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
        log.setLevel(logging.ERROR)

    if not args.regions:
        args.regions = DEFAULT_REGIONS

    for region in args.regions:
        conn = get_aws_connection(region)
        all_spot_instances = get_spot_instances(region)
        for i in all_spot_instances:
            log.info("Processing %s", i)
            name = i.tags.get('Name')
            fqdn = i.tags.get('FQDN')
            moz_type = i.tags.get('moz-type')
            # If one of the tags is unset/empty
            if not all([name, fqdn, moz_type]):
                try:
                    tag_it(i)
                except IndexError:
                    log.debug("Failed to tag %s", i)
