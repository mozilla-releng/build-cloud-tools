#!/usr/bin/env python

import argparse
import logging
import site
import os

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import DEFAULT_REGIONS
from cloudtools.aws.spot import get_instances_to_tag, \
    populate_spot_requests_cache, copy_spot_request_tags

log = logging.getLogger(__name__)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", dest="regions", action="append",
                        help="optional list of regions")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Supress logging messages")
    parser.add_argument("-j", "--concurrency", type=int, default=4)

    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.quiet:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.ERROR)

    if not args.regions:
        args.regions = DEFAULT_REGIONS

    instances_to_tag = []
    for r in args.regions:
        instances_to_tag.extend(get_instances_to_tag(r))
        if instances_to_tag:
            populate_spot_requests_cache(r, instances_to_tag)
            for i in instances_to_tag:
                log.debug("tagging %s", i)
                copy_spot_request_tags(i)
        # map(tag_it, instances_to_tag)
