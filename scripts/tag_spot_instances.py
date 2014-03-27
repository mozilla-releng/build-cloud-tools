#!/usr/bin/env python

import argparse
import logging
import site
import os
import threading
from Queue import Queue

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import get_vpc, DEFAULT_REGIONS
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
    tags = {}
    for tag_name, tag_value in interface.tags.iteritems():
        if not tag_name in i.tags:
            log.info("Adding '%s' tag with '%s' value to %s", tag_name,
                     tag_value, i)
            tags[tag_name] = tag_value
    tags["moz-state"] = "ready"
    i.connection.create_tags([i.id], tags)


def tagging_worker(q):
    while True:
        # Handle shutdown, don't try to use q
        if q is None:
            return
        i = q.get(timeout=30)
        try:
            tag_it(i)
        except:
            log.debug("Failed to tag %s", i, exc_info=True)
        finally:
            q.task_done()


def populate_queue(region, q):
    log.debug("Connecting to %s", region)
    log.debug("Getting all spot instances in %s...", region)
    all_spot_instances = get_spot_instances(region)
    log.debug("Done with %s", region)
    for i in all_spot_instances:
        name = i.tags.get('Name')
        fqdn = i.tags.get('FQDN')
        moz_type = i.tags.get('moz-type')
        # If one of the tags is unset/empty
        if not all([name, fqdn, moz_type]):
            log.debug("Adding %s in %s to queue", i, region)
            q.put(i)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", dest="regions", action="append",
                        help="optional list of regions")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Supress logging messages")
    parser.add_argument("-j", "--concurrency", type=int, default=8)

    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.quiet:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.ERROR)

    if not args.regions:
        args.regions = DEFAULT_REGIONS

    q = Queue()

    for _ in range(args.concurrency):
        t = threading.Thread(target=tagging_worker, args=(q,))
        # daemonize tagging threads to make so we can simplify the code by
        # joining the queue instead of joining all threads
        t.daemon = True
        t.start()

    threads = []
    for region in args.regions:
        t = threading.Thread(target=populate_queue, args=(region, q))
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout=30)
    log.debug("Waiting for workers")
    q.join()
