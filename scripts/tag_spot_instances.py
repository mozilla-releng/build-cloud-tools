#!/usr/bin/env python

import argparse
import logging
import site
import os
from threading import Thread
from Queue import Queue, Empty

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import DEFAULT_REGIONS
from cloudtools.aws.spot import get_spot_instances, get_spot_request

log = logging.getLogger(__name__)


def tag_it(i):
    log.debug("Tagging %s", i)
    req = get_spot_request(i.region.name, i.spot_instance_request_id)
    if not req:
        log.error("Cannot find spot request for %s", i)
        return
    tags = {}
    for tag_name, tag_value in req.tags.iteritems():
        if not tag_name in i.tags:
            log.info("Adding '%s' tag with '%s' value to %s", tag_name,
                     tag_value, i)
            tags[tag_name] = tag_value
    tags["moz-state"] = "ready"
    i.connection.create_tags([i.id], tags)


def tagging_worker(q):
    while True:
        try:
            i = q.get(timeout=0.1)
        except Empty:
            log.debug("Exiting worker...")
            return
        try:
            tag_it(i)
        except:
            log.debug("Failed to tag %s", i, exc_info=True)


def populate_queue(region, q):
    log.debug("Getting all spot instances in %s...", region)
    all_spot_instances = get_spot_instances(region)
    for i in all_spot_instances:
        name = i.tags.get('Name')
        fqdn = i.tags.get('FQDN')
        moz_type = i.tags.get('moz-type')
        moz_state = i.tags.get('moz-state')
        # If one of the tags is unset/empty
        if not all([name, fqdn, moz_type, moz_state]):
            log.debug("Adding %s in %s to queue", i, region)
            q.put(i)
    log.debug("Done with %s", region)


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

    q = Queue()

    threads = [Thread(target=populate_queue, args=(r, q)) for r in
               args.regions]
    log.debug("Waiting for regions...")
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    if not q.empty():
        num_threads = min(args.concurrency, q.qsize())
        threads = [Thread(target=tagging_worker, args=(q,)) for _ in
                   range(num_threads)]
        log.debug("Waiting for %s workers...", num_threads)
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=240)
