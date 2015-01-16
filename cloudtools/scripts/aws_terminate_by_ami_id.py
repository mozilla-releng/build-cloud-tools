#!/usr/bin/env python
"""
Kills instances with specified AMI IDs
"""
import logging
import argparse
import time

from cloudtools.aws import get_aws_connection, DEFAULT_REGIONS

log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", action="append", dest="regions")
    parser.add_argument("amis", metavar="AMI", nargs="+",
                        help="AMI IDs")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if args.verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)

    regions = args.regions
    if not regions:
        regions = DEFAULT_REGIONS

    instances_to_kill = []
    for r in regions:
        log.debug("working in %s", r)
        conn = get_aws_connection(r)
        instances = conn.get_only_instances(
            filters={"image-id": args.amis, "instance-state-name": "running"})
        log.debug("got %s instances:\n%s", len(instances), instances)
        if instances:
            instances_to_kill.extend(instances)
    if instances_to_kill:
        log.info("Preparing to terminate the following %s instances:",
                 len(instances_to_kill))
        for i in instances_to_kill:
            log.info("%s (%s)", i.id, i.tags.get("Name"))
        yesno = raw_input("Are you sure you want to kill these? ^ y/N >")
        if yesno != "y":
            log.info("Exiting without any changes!")
            return

        yesno = raw_input("ARE YOU SURE YOU WANT TO KILL THESE? ^"
                          " LAST WARNING!!! y/N >")
        if yesno != "y":
            log.info("Exiting without any changes!")
            return
        log.warn("The instances mentioned above are about to be terminated")
        log.warn("Waiting extra 60 seconds to make sure...")
        time.sleep(60)
        log.warn("Starting...")
        for i in instances_to_kill:
            log.warn("Terminating %s...", i)
            i.terminate()
            log.warn("Done.")

if __name__ == '__main__':
    main()
