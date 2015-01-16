#!/usr/bin/env python

import argparse
import logging

from cloudtools.aws import get_aws_connection, DEFAULT_REGIONS
from time import gmtime, strftime

log = logging.getLogger(__name__)


def start(i, dry_run):
    name = i.tags.get('Name', '')
    log.info("Starting %s..." % name)
    if dry_run:
        log.info("Dry run mode, skipping...")
    else:
        i.start()


def stop(i, dry_run):
    name = i.tags.get('Name', '')
    log.info("Stopping %s..." % name)
    if dry_run:
        log.info("Dry run mode, skipping...")
    else:
        i.stop()


def restart(i, dry_run):
    name = i.tags.get('Name', '')
    log.info("Restarting %s..." % name)
    if dry_run:
        log.info("Dry run mode, skipping...")
    else:
        i.reboot()


def enable(i, dry_run):
    name = i.tags.get('Name', '')
    log.info("Enabling %s..." % name)
    if dry_run:
        log.info("Dry run mode, skipping...")
    else:
        # .add_tag overwrites existing tag
        i.add_tag("moz-state", "ready")


def disable(i, dry_run, comments=None):
    name = i.tags.get('Name', '')
    moz_state = "disabled at %s" % strftime("%Y-%m-%d %H:%M:%S +0000",
                                            gmtime())
    if comments:
        moz_state += ". %s" % comments
    log.info("Disabling %s, setting moz-state tag to '%s'..." % (name,
                                                                 moz_state))
    if dry_run:
        log.info("Dry run mode, skipping...")
    else:
        i.add_tag("moz-state", moz_state)


def terminate(i, dry_run, force=None):
    name = i.tags.get('Name', '')
    log.info("Terminating %s..." % name)

    if dry_run:
        log.info("Dry run mode, skipping...")
        return

    if force:
        yesno = "y"
    else:
        yesno = raw_input("WARNING: you are about to terminate %s! "
                          "Are you sure? [y/N] " % name)
    if yesno == "y":
        i.terminate()
        log.info("%s terminated" % name)
    else:
        log.info("%s NOT terminated" % name)


def status(i):
    instance_id = i.id
    name = i.tags.get('Name', '')
    ip = i.private_ip_address
    state = i.state
    moz_state = i.tags.get('moz-state', '')
    enabled = bool(moz_state == "ready")

    print "Name:".rjust(8), name
    print "ID:".rjust(8), instance_id
    print "IP:".rjust(8), ip
    print "Enabled:".rjust(8), enabled
    print "State:".rjust(8), state
    print "Tags:".rjust(8), ", ".join(["%s -> %s" % (k, v)
                                       for k, v in i.tags.iteritems()])
    print "=" * 72


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", dest="regions", action="append",
                        help="optional list of regions")
    parser.add_argument("action", choices=["stop", "start", "restart",
                                           "enable", "disable", "terminate",
                                           "status"],
                        help="action to be performed")
    parser.add_argument("-m", "--comments", help="reason to disable")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Dry run mode")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Supress logging messages")
    parser.add_argument("hosts", metavar="host", nargs="+",
                        help="hosts to be processed")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Force action without prompting")

    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.quiet:
        log.setLevel(logging.INFO)
    else:
        log.setLevel(logging.ERROR)

    if not args.regions:
        args.regions = DEFAULT_REGIONS

    for region in args.regions:
        conn = get_aws_connection(region)
        instances = conn.get_only_instances()
        for i in instances:
            name = i.tags.get('Name', '')
            instance_id = i.id
            if not i.private_ip_address:
                # Terminated instances has no IP address assinged
                log.debug("Skipping (terminated?) %s (%s)..." % (name,
                                                                 instance_id))
                continue
            if name in args.hosts or instance_id in args.hosts:
                log.info("Found %s (%s)..." % (name, instance_id))

                if args.action == "start":
                    start(i, args.dry_run)
                elif args.action == "stop":
                    stop(i, args.dry_run)
                elif args.action == "restart":
                    restart(i, args.dry_run)
                elif args.action == "enable":
                    enable(i, args.dry_run)
                elif args.action == "disable":
                    disable(i, args.dry_run, args.comments)
                elif args.action == "terminate":
                    terminate(i, args.dry_run, args.force)
                elif args.action == "status":
                    status(i)

if __name__ == '__main__':
    main()
