#!/usr/bin/env python
"""
Watches running EC2 instances and shuts them down when idle
"""
# lint_ignore=E501,C901
import argparse
import logging.handlers
import time
import calendar
import random
import threading
import boto.ec2
import requests
import logging
import json

from Queue import Queue, Empty
from cloudtools.aws import get_impaired_instance_ids, get_buildslave_instances
from cloudtools.buildbot import graceful_shutdown, get_last_activity, \
    ACTIVITY_STOPPED, ACTIVITY_BOOTING
from cloudtools.ssh import SSHClient
import cloudtools.graphite
from cloudtools.log import add_syslog_handler

log = logging.getLogger(__name__)
gr_log = cloudtools.graphite.get_graphite_logger()

# Instances running less than STOP_THRESHOLD_MINS minutes within 1 hour
# boundary won't be stopped.
STOP_THRESHOLD_MINS_SPOT = 45
STOP_THRESHOLD_MINS_ONDEMAND = 30


def aws_safe_stop_instance(i, impaired_ids, user, key_filename, masters_json,
                           dryrun=False):
    "Returns True if stopped"
    # TODO: Check with slavealloc

    ssh_client = SSHClient(instance=i, username=user,
                           key_filename=key_filename).connect()
    stopped = False
    launch_time = calendar.timegm(time.strptime(
        i.launch_time[:19], '%Y-%m-%dT%H:%M:%S'))
    if not ssh_client:
        if i.id in impaired_ids:
            if time.time() - launch_time > 60 * 10:
                stopped = True
                if not dryrun:
                    log.debug(
                        "%s - shut down an instance with impaired status",
                        ssh_client.name)
                    i.terminate()
                    gr_log.add("impaired.{moz_type}".format(
                        ssh_client.instance.tags.get("moz-type", "none")), 1,
                        collect=True)
                else:
                    log.debug("%s - would have stopped", ssh_client.name)
        return stopped

    uptime_min = int((time.time() - launch_time) / 60)
    # Don't try to stop spot instances until after STOP_THRESHOLD_MINS_SPOT
    # minutes into each hour
    if i.spot_instance_request_id:
        threshold = STOP_THRESHOLD_MINS_SPOT
        if uptime_min % 60 < threshold:
            log.debug("Skipping %s, with uptime %s", ssh_client.name,
                      uptime_min)
            return False
    else:
        # On demand instances can be stopped after STOP_THRESHOLD_MINS_ONDEMAND
        threshold = STOP_THRESHOLD_MINS_ONDEMAND
        if uptime_min < threshold:
            log.debug("Skipping %s, with updtime %s", ssh_client.name,
                      uptime_min)
            return False

    last_activity = get_last_activity(ssh_client)
    if last_activity == ACTIVITY_STOPPED:
        stopped = True
        if not dryrun:
            log.debug("%s - stopping instance (launched %s)", ssh_client.name,
                      i.launch_time)
            i.terminate()
        else:
            log.debug("%s - would have stopped", ssh_client.name)
        return stopped

    if last_activity == ACTIVITY_BOOTING:
        # Wait harder
        return stopped

    log.debug("%s - last activity %s", ssh_client.name, last_activity)

    # If it looks like we're idle for more than 8 hours, kill the machine
    if last_activity > 8 * 3600:
        log.debug("%s - last activity more than 8 hours ago; shutting down",
                  ssh_client.name)
        if not dryrun:
            log.debug("%s - starting graceful shutdown", ssh_client.name)
            graceful_shutdown(ssh_client, masters_json)
            # Stop the instance
            log.debug("%s - stopping instance", ssh_client.name)
            i.terminate()
            stopped = True

    # If the machine is idle for more than 5 minutes, shut it down
    elif last_activity > 300:
        if not dryrun:
            # Hit graceful shutdown on the master
            log.debug("%s - starting graceful shutdown", ssh_client.name)
            graceful_shutdown(ssh_client, masters_json)

            # Check if we've exited right away
            if get_last_activity(ssh_client) == ACTIVITY_STOPPED:
                log.debug("%s - stopping instance", ssh_client.name)
                i.terminate()
                stopped = True
            else:
                log.debug(
                    "%s - not stopping, waiting for graceful shutdown",
                    ssh_client.name)
        else:
            log.debug("%s - would have started graceful shutdown",
                      ssh_client.name)
            stopped = True
    else:
        log.debug("%s - not stopping", ssh_client.name)
    return stopped


def aws_stop_idle(user, key_filename, regions, masters_json, moz_types,
                  dryrun=False, concurrency=8):
    if not regions:
        # Look at all regions
        log.debug("loading all regions")
        regions = [r.name for r in boto.ec2.regions()]

    min_running_by_type = 0

    all_instances = []
    impaired_ids = []

    for r in regions:
        log.debug("looking at region %s", r)
        instances = get_buildslave_instances(r, moz_types)
        log.debug("Got %s buildslave instances", len(instances))
        impaired_ids.extend(get_impaired_instance_ids(r))
        log.debug("Got %s impaired instances", len(impaired_ids))
        instances_by_type = {}
        for i in instances:
            # TODO: Check if launch_time is too old, and terminate the instance
            # if it is
            # NB can't turn this on until aws_create_instance is working
            # properly (with ssh keys)
            instances_by_type.setdefault(i.tags['moz-type'], []).append(i)

        # Make sure min_running_by_type are kept running
        for t in instances_by_type:
            to_remove = instances_by_type[t][:min_running_by_type]
            for i in to_remove:
                log.debug("%s - keep running (min %s instances of type %s)",
                          i.tags['Name'], min_running_by_type,
                          i.tags['moz-type'])
                instances.remove(i)

        all_instances.extend(instances)

    random.shuffle(all_instances)

    q = Queue()
    to_stop = Queue()

    def worker():
        while True:
            try:
                i = q.get(timeout=0.1)
            except Empty:
                return
            try:
                if aws_safe_stop_instance(i, impaired_ids, user, key_filename,
                                          masters_json, dryrun=dryrun):
                    to_stop.put(i)
            except Exception:
                log.debug("%s - unable to stop" % i.tags.get('Name'),
                          exc_info=True)

    for i in all_instances:
        q.put(i)

    # Workaround for http://bugs.python.org/issue11108
    time.strptime("19000102030405", "%Y%m%d%H%M%S")
    threads = []
    for i in range(concurrency):
        t = threading.Thread(target=worker)
        t.start()
        threads.append(t)

    while threads:
        for t in threads[:]:
            try:
                if t.is_alive():
                    t.join(timeout=0.5)
                else:
                    t.join()
                    threads.remove(t)
            except KeyboardInterrupt:
                raise SystemExit(1)

    total_stopped = {}
    while not to_stop.empty():
        i = to_stop.get()
        if not dryrun:
            i.update()
        if 'moz-type' not in i.tags:
            log.debug("%s - has no moz-type! (%s)" % (i.tags.get('Name'),
                                                      i.id))

        t = i.tags.get('moz-type', 'none')
        if t not in total_stopped:
            total_stopped[t] = 0
        total_stopped[t] += 1

    for t, c in sorted(total_stopped.items()):
        log.debug("%s - stopped %s", t, c)
        gr_log.add("stopped.%s" % t, c)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", action="append", dest="regions",
                        required=True)
    parser.add_argument("-v", "--verbose", action="store_const",
                        dest="loglevel", const=logging.DEBUG,
                        default=logging.WARNING)
    parser.add_argument("-k", "--secrets", type=argparse.FileType('r'),
                        required=True)
    parser.add_argument("-u", "--user", required=True, help="SSH user name")
    parser.add_argument("--ssh-key", required=True,
                        help="Private SSH key path")
    parser.add_argument("-t", "--moz-type", action="append", dest="moz_types",
                        required=True,
                        help="moz-type tag values to be checked")
    parser.add_argument("-j", "--concurrency", type=int, default=8)
    parser.add_argument(
        "--masters-json",
        default="https://hg.mozilla.org/build/tools/raw-file/default/buildfarm"
        "/maintenance/production-masters.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-l", "--logfile", dest="logfile",
                        help="log file for full debug log")

    args = parser.parse_args()

    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("boto").setLevel(logging.WARN)
    logging.getLogger("paramiko").setLevel(logging.WARN)
    logging.getLogger('requests').setLevel(logging.WARN)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s -  %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(args.loglevel)
    logging.getLogger().addHandler(handler)

    if args.logfile:
        handler = logging.handlers.RotatingFileHandler(
            args.logfile, maxBytes=10 * (1024 ** 2), backupCount=100)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)

    log.debug("starting")

    masters_json = requests.get(args.masters_json).json()
    secrets = json.load(args.secrets)

    aws_stop_idle(user=args.user, key_filename=args.ssh_key,
                  regions=args.regions, masters_json=masters_json,
                  moz_types=args.moz_types, dryrun=args.dry_run,
                  concurrency=args.concurrency)
    for entry in secrets.get("graphite_hosts", []):
        host = entry.get("host")
        port = entry.get("port")
        prefix = "{}.releng.aws.aws_stop_idle".format(entry.get("prefix"))
        if all([host, port, prefix]):
            gr_log.add_destination(host, port, prefix)

    if secrets.get("syslog_address"):
        add_syslog_handler(log, address=secrets["syslog_address"],
                           app="aws_stop_idle")

    gr_log.sendall()
    log.debug("done")

if __name__ == '__main__':
    main()
