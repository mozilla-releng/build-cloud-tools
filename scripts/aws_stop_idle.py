#!/usr/bin/env python
"""
Watches running EC2 instances and shuts them down when idle
"""
import re
import time
import calendar
try:
    import simplejson as json
    assert json
except ImportError:
    import json

import random
import threading
import boto.ec2
import requests
import logging
import site
import os
from paramiko import SSHClient
from Queue import Queue, Empty

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import get_aws_connection

log = logging.getLogger()

# Instances running less than STOP_THRESHOLD_MINS minutes within 1 hour
# boundary won't be stopped.
STOP_THRESHOLD_MINS_SPOT = 45
STOP_THRESHOLD_MINS_ONDEMAND = 30


def stop(i, ssh_client=None):
    """Stop or destroy an instances depending on its type. Spot instances do
    not support stop() method."""

    name = i.tags.get("Name")
    # on-demand instances don't have instanceLifecycle attribute
    if hasattr(i, "instanceLifecycle") and i.instanceLifecycle == "spot":
        log.info("Terminating %s (%s)", name, i)
        i.terminate()
    else:
        log.info("Stopping %s (%s)", name, i)
        i.stop()


def get_buildbot_instances(conn, moz_types):
    # Look for running `moz_types` instances with moz-state=ready
    reservations = conn.get_all_instances(filters={
        'tag:moz-state': 'ready',
        'instance-state-name': 'running',
    })

    retval = []
    for r in reservations:
        for i in r.instances:
            if i.tags.get("moz-type") in moz_types and \
                    not i.tags.get("moz-loaned-to"):
                retval.append(i)

    return retval


class IgnorePolicy:

    def missing_host_key(self, client, hostname, key):
        pass


def get_ssh_client(name, ip, credentials):
    client = SSHClient()
    client.set_missing_host_key_policy(IgnorePolicy())
    for u, passwords in credentials.iteritems():
        for p in passwords:
            try:
                client.connect(hostname=ip, username=u, password=p)
                return client
            except Exception:
                pass

    log.warning("Couldn't log into %s at %s with any known passwords",
                name, ip)
    return None


def get_last_activity(name, client):
    stdin, stdout, stderr = client.exec_command("date +%Y%m%d%H%M%S")
    slave_time = stdout.read().strip()
    slave_time = time.mktime(time.strptime(slave_time, "%Y%m%d%H%M%S"))

    stdin, stdout, stderr = client.exec_command("cat /proc/uptime")
    uptime = float(stdout.read().split()[0])

    if uptime < 3 * 60:
        # Assume we're still booting
        log.debug("%s - uptime is %.2f; assuming we're still booting up", name,
                  uptime)
        return "booting"

    stdin, stdout, stderr = client.exec_command(
        "tail -n 100 /builds/slave/twistd.log.1 /builds/slave/twistd.log")
    stdin.close()

    last_activity = None
    running_command = False
    t = time.time()
    line = ""
    for line in stdout:
        m = re.search(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if m:
            t = time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            t = time.mktime(t)
        else:
            # Not sure what to do with this line...
            continue

        # uncomment to dump out ALL the lines
        #log.debug("%s - %s", name, line.strip())

        if "RunProcess._startCommand" in line or "using PTY: " in line:
            log.debug("%s - started command - %s", name, line.strip())
            running_command = True
        elif "commandComplete" in line or "stopCommand" in line:
            log.debug("%s - done command - %s", name, line.strip())
            running_command = False

        if "Shut Down" in line:
            # Check if this happened before we booted, i.e. we're still booting
            # up
            if (slave_time - t) > uptime:
                log.debug(
                    "%s - shutdown line is older than uptime; assuming we're still booting %s", name, line.strip())
                last_activity = "booting"
            else:
                last_activity = "stopped"
        elif running_command:
            # We're in the middle of running something, so say that our last
            # activity is now (0 seconds ago)
            last_activity = 0
        else:
            last_activity = slave_time - t

    # If this was over 10 minutes ago
    if (slave_time - t) > 10 * 60 and (slave_time - t) > uptime:
        log.warning(
            "%s - shut down happened %ss ago, but we've been up for %ss - %s",
            name, slave_time - t, uptime, line.strip())
        # If longer than 30 minutes, try rebooting
        if (slave_time - t) > 30 * 60:
            log.warning("%s - rebooting", name)
            stdin, stdout, stderr = client.exec_command("sudo reboot")
            stdin.close()

    # If there's *no* activity (e.g. no twistd.log files), and we've been up a
    # while, then reboot
    if last_activity is None and uptime > 15 * 60:
        log.warning("%s - no activity; rebooting", name)
        # If longer than 30 minutes, try rebooting
        stdin, stdout, stderr = client.exec_command("sudo reboot")
        stdin.close()

    log.debug("%s - %s - %s", name, last_activity, line.strip())
    return last_activity


def get_tacfile(client):
    stdin, stdout, stderr = client.exec_command(
        "cat /builds/slave/buildbot.tac")
    stdin.close()
    data = stdout.read()
    return data


def get_buildbot_master(client, masters_json):
    tacfile = get_tacfile(client)
    host = re.search("^buildmaster_host = '(.*?)'$", tacfile, re.M)
    host = host.group(1)
    port = None
    for master in masters_json:
        if master["hostname"] == host:
            port = master["http_port"]
            break
    assert host and port
    return host, port


def graceful_shutdown(name, ip, client, masters_json):
    # Find out which master we're attached to by looking at buildbot.tac
    log.debug("%s - looking up which master we're attached to", name)
    host, port = get_buildbot_master(client, masters_json)

    url = "http://{host}:{port}/buildslaves/{name}/shutdown".format(
        host=host, port=port, name=name)
    log.debug("%s - POSTing to %s", name, url)
    requests.post(url, allow_redirects=False)


def aws_safe_stop_instance(i, impaired_ids, credentials, masters_json,
                           dryrun=False):
    "Returns True if stopped"
    name = i.tags['Name']
    # TODO: Check with slavealloc

    ip = i.private_ip_address
    ssh_client = get_ssh_client(name, ip, credentials)
    stopped = False
    launch_time = calendar.timegm(time.strptime(
        i.launch_time[:19], '%Y-%m-%dT%H:%M:%S'))
    if not ssh_client:
        if i.id in impaired_ids:
            if time.time() - launch_time > 60 * 10:
                stopped = True
                if not dryrun:
                    log.warning(
                        "%s - shut down an instance with impaired status", name)
                    stop(i)
                else:
                    log.info("%s - would have stopped", name)
        return stopped

    # skip instances running not close to 1hr boundary
    uptime_min = int((time.time() - launch_time) / 60)
    if i.spot_instance_request_id:
        threshold = STOP_THRESHOLD_MINS_SPOT
    else:
        threshold = STOP_THRESHOLD_MINS_ONDEMAND
    if uptime_min % 60 < threshold:
        log.debug("Skipping %s, with uptime %s", name, uptime_min)
        return False

    last_activity = get_last_activity(name, ssh_client)
    if last_activity == "stopped":
        stopped = True
        if not dryrun:
            log.info("%s - stopping instance (launched %s)", name,
                     i.launch_time)
            stop(i, ssh_client)
        else:
            log.info("%s - would have stopped", name)
        return stopped

    if last_activity == "booting":
        # Wait harder
        return stopped

    log.debug("%s - last activity %s", name, last_activity)
    # Determine if the machine is idle for more than 10 minutes
    if last_activity > 300:
        if not dryrun:
            # Hit graceful shutdown on the master
            log.debug("%s - starting graceful shutdown", name)
            graceful_shutdown(name, ip, ssh_client, masters_json)

            # Check if we've exited right away
            if get_last_activity(name, ssh_client) == "stopped":
                log.debug("%s - stopping instance", name)
                stop(i, ssh_client)
                stopped = True
            else:
                log.info(
                    "%s - not stopping, waiting for graceful shutdown", name)
        else:
            log.info("%s - would have started graceful shutdown", name)
            stopped = True
    else:
        log.debug("%s - not stopping", name)
    return stopped


def aws_stop_idle(credentials, regions, masters_json, moz_types,
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
        conn = get_aws_connection(r)
        instances = get_buildbot_instances(conn, moz_types)
        impaired = conn.get_all_instance_status(
            filters={'instance-status.status': 'impaired'})
        impaired_ids.extend(i.id for i in impaired)
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
                if aws_safe_stop_instance(i, impaired_ids, credentials,
                                          masters_json, dryrun=dryrun):
                    to_stop.put(i)
            except Exception:
                log.warning("%s - unable to stop" % i.tags.get('Name'),
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
            log.info("%s - has no moz-type! (%s)" % (i.tags.get('Name'), i.id))

        t = i.tags.get('moz-type', 'notype')
        if t not in total_stopped:
            total_stopped[t] = 0
        total_stopped[t] += 1

    for t, c in sorted(total_stopped.items()):
        log.info("%s - stopped %s", t, c)

if __name__ == '__main__':
    import argparse
    import logging.handlers
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", action="append", dest="regions",
                        required=True)
    parser.add_argument("-v", "--verbose", action="store_const",
                        dest="loglevel", const=logging.DEBUG,
                        default=logging.INFO)
    parser.add_argument("-c", "--credentials", type=argparse.FileType('r'),
                        required=True)
    parser.add_argument("-t", "--moz-type", action="append", dest="moz_types",
                        required=True,
                        help="moz-type tag values to be checked")
    parser.add_argument("-j", "--concurrency", type=int, default=8)
    parser.add_argument("--masters-json",
                        default="https://hg.mozilla.org/build/tools/raw-file/default/buildfarm/maintenance/production-masters.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-l", "--logfile", dest="logfile",
                        help="log file for full debug log")

    args = parser.parse_args()

    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("boto").setLevel(logging.WARN)
    logging.getLogger("paramiko").setLevel(logging.WARN)
    logging.getLogger('requests').setLevel(logging.WARN)

    formatter = logging.Formatter("%(asctime)s - %(message)s")
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
    credentials = json.load(args.credentials)

    try:
        masters_json = json.load(open(args.masters_json))
    except IOError:
        masters_json = requests.get(args.masters_json).json()

    aws_stop_idle(credentials, args.regions, masters_json,
                  args.moz_types, dryrun=args.dry_run,
                  concurrency=args.concurrency)
    log.debug("done")
