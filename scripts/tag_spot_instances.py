#!/usr/bin/env python

import argparse
import json
import logging
import site
import os

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import get_aws_connection, get_vpc

log = logging.getLogger(__name__)
REGIONS = ['us-east-1', 'us-west-2']


def tag_it(i, vpc):
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
        secrets = {}

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.quiet:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.ERROR)

    if not args.regions:
        args.regions = REGIONS
    for region in args.regions:
        conn = get_aws_connection(region, secrets.get("aws_access_key_id"),
                                  secrets.get("aws_secret_access_key"))
        vpc = get_vpc(region, secrets.get("aws_access_key_id"),
                      secrets.get("aws_secret_access_key"))

        spot_requests = conn.get_all_spot_instance_requests() or []
        for req in spot_requests:
            if req.tags.get("moz-tagged"):
                log.debug("Skipping already processed spot request %s", req)
                continue
            i_id = req.instance_id
            if not i_id:
                log.debug("Skipping spot request %s without instance_id", req)
                continue
            res = conn.get_all_instances(instance_ids=[i_id])
            try:
                for r in res:
                    for i in r.instances:
                        log.info("Processing %s", i)
                        name = i.tags.get('Name')
                        fqdn = i.tags.get('FQDN')
                        moz_type = i.tags.get('moz-type')
                        # If one of the tags is unset/empty
                        if not all([name, fqdn, moz_type]):
                            tag_it(i, vpc)
            except IndexError:
                # tag it next time
                log.debug("Failed to tag %s", req)
                pass
            else:
                req.add_tag("moz-tagged", "1")
