#!/usr/bin/env python
"""
Watches running EC2 instances and shuts them down when idle
"""
import re
import time
try:
    import simplejson as json
except ImportError:
    import json

import random
import threading
from Queue import Queue, Empty

import boto.ec2
from paramiko import SSHClient
import requests

import logging
log = logging.getLogger()


def get_buildbot_instances(conn):
    # Look for instances with moz-state=ready and hostname *-ec2-000
    reservations = conn.get_all_instances(filters={
        'tag:moz-state': 'ready',
        'instance-state-name': 'running',
    })

    retval = []
    for r in reservations:
        for i in r.instances:
            name = i.tags['Name']
            if not re.match(".*-ec2-\d+", name):
                continue
            retval.append(i)

    return retval


class IgnorePolicy:
    def missing_host_key(self, client, hostname, key):
        pass


def get_ssh_client(name, ip, passwords):
    client = SSHClient()
    client.set_missing_host_key_policy(IgnorePolicy())
    for p in passwords:
        try:
            client.connect(hostname=ip, username='cltbld', password=p)
            return client
        except:
            pass

    log.warning("Couldn't log into {name} at {ip} with any known passwords".format(name=name, ip=ip))
    return None


def get_last_activity(name, client):
    stdin, stdout, stderr = client.exec_command("date +%Y%m%d%H%M%S")
    slave_time = stdout.read().strip()
    slave_time = time.mktime(time.strptime(slave_time, "%Y%m%d%H%M%S"))

    stdin, stdout, stderr = client.exec_command("cat /proc/uptime")
    uptime = float(stdout.read().split()[0])

    if uptime < 3*60:
        # Assume we're still booting
        log.debug("%s - uptime is %.2f; assuming we're still booting up", name, uptime)
        return "booting"

    stdin, stdout, stderr = client.exec_command("tail -n 100 /builds/slave/twistd.log.1 /builds/slave/twistd.log")
    stdin.close()

    last_activity = None
    running_command = False
    t = time.time()
    line = ""
    for line in stdout:
        m = re.search("^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
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
            # Check if this happened before we booted, i.e. we're still booting up
            if (slave_time - t) > uptime:
                log.debug("%s - shutdown line is older than uptime; assuming we're still booting %s", name, line.strip())
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
    if (slave_time - t) > 10*60 and (slave_time - t) > uptime:
        log.warning("%s - shut down happened %ss ago, but we've been up for %ss - %s", name, slave_time-t, uptime, line.strip())
        # If longer than 30 minutes, try rebooting
        if (slave_time - t) > 30*60:
            log.warning("%s - rebooting", name)
            stdin, stdout, stderr = client.exec_command("sudo reboot")
            stdin.close()

    # If there's *no* activity (e.g. no twistd.log files), and we've been up a while, then reboot
    if last_activity is None and uptime > 15*60:
        log.warning("%s - no activity; rebooting", name)
        # If longer than 30 minutes, try rebooting
        stdin, stdout, stderr = client.exec_command("sudo reboot")
        stdin.close()

    log.debug("%s - %s - %s", name, last_activity, line.strip())
    return last_activity


def get_tacfile(client):
    stdin, stdout, stderr = client.exec_command("cat /builds/slave/buildbot.tac")
    stdin.close()
    data = stdout.read()
    return data


def get_buildbot_master(client):
    tacfile = get_tacfile(client)
    host = re.search("^buildmaster_host = '(.*?)'$", tacfile, re.M)
    port = re.search("^port = (\d+)", tacfile, re.M)
    assert host and port
    host = host.group(1)
    port = int(port.group(1))
    return host, port


def graceful_shutdown(name, ip, client):
    # Find out which master we're attached to by looking at buildbot.tac
    log.debug("%s - looking up which master we're attached to", name)
    host, port = get_buildbot_master(client)
    # http port is pb port -1000
    port -= 1000

    url = "http://{host}:{port}/buildslaves/{name}/shutdown".format(host=host, port=port, name=name)
    log.debug("%s - POSTing to %s", name, url)
    requests.post(url, allow_redirects=False)


def aws_safe_stop_instance(i, impaired_ids, passwords, dryrun=False):
    name = i.tags['Name']
    # TODO: Check with slavealloc

    ip = i.private_ip_address
    ssh_client = get_ssh_client(name, ip, passwords)
    if not ssh_client:
        if i.id in impaired_ids:
            launch_time = time.mktime(time.strptime(
                i.launch_time[:19], '%Y-%m-%dT%H:%M:%S'))
            if time.time() - launch_time > 60 * 10:
                log.warning("%s - shut down an instance with impaired status" % name)
                i.stop()
        return
    last_activity = get_last_activity(name, ssh_client)
    if last_activity == "stopped":
        # TODO: could be that the machine is just starting up....
        if not dryrun:
            log.info("%s - stopping instance (launched %s)", name, i.launch_time)
            i.stop()
        else:
            log.info("%s - would have stopped", name)
        return

    if last_activity == "booting":
        # Wait harder
        return

    log.debug("%s - last activity %is ago", name, last_activity)
    # Determine if the machine is idle for more than 10 minutes
    if last_activity > 300:
        if not dryrun:
            # Hit graceful shutdown on the master
            log.debug("%s - starting graceful shutdown", name)
            graceful_shutdown(name, ip, ssh_client)

            # Check if we've exited right away
            if get_last_activity(name, ssh_client) == "stopped":
                log.debug("%s - stopping instance", name)
                i.stop()
            else:
                log.info("%s - not stopping, waiting for graceful shutdown", name)
        else:
            log.info("%s - would have started graceful shutdown", name)
    else:
        log.debug("%s - not stopping", name)


def aws_stop_idle(secrets, passwords, regions, dryrun=False, concurrency=8):
    if not regions:
        # Look at all regions
        log.debug("loading all regions")
        regions = [r.name for r in boto.ec2.regions(**secrets)]

    min_running_by_type = 0

    all_instances = []
    impaired_ids = []

    for r in regions:
        log.debug("looking at region %s", r)
        conn = boto.ec2.connect_to_region(r, **secrets)

        instances = get_buildbot_instances(conn)
        impaired = conn.get_all_instance_status(
            filters={'instance-status.status': 'impaired'})
        impaired_ids.extend(i.id for i in impaired)
        instances_by_type = {}
        for i in instances:
            # TODO: Check if launch_time is too old, and terminate the instance
            # if it is
            # NB can't turn this on until aws_create_instance is working properly (with ssh keys)
            instances_by_type.setdefault(i.tags['moz-type'], []).append(i)

        # Make sure min_running_by_type are kept running
        for t in instances_by_type:
            to_remove = instances_by_type[t][:min_running_by_type]
            for i in to_remove:
                log.debug("%s - keep running (min %i instances of type %s)", i.tags['Name'], min_running_by_type, i.tags['moz-type'])
                instances.remove(i)

        all_instances.extend(instances)

    random.shuffle(all_instances)

    q = Queue()

    def worker():
        while True:
            try:
                i = q.get(timeout=0.1)
            except Empty:
                return
            aws_safe_stop_instance(i, impaired_ids, passwords, dryrun=dryrun)

    for i in all_instances:
        q.put(i)

    threads = []
    for i in range(concurrency):
        t = threading.Thread(target=worker)
        t.start()

    while threads:
        for t in threads[:]:
            if t.is_alive():
                t.join(timeout=0.5)
            else:
                t.join()
                threads.remove(t)

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.set_defaults(
        regions=[],
        secrets=None,
        passwords=None,
        loglevel=logging.INFO,
        dryrun=False,
        concurrency=8,
    )

    parser.add_option("-r", "--region", action="append", dest="regions")
    parser.add_option("-k", "--secrets", dest="secrets")
    parser.add_option("-s", "--key-name", dest="key_name")
    parser.add_option("-v", "--verbose", action="store_const", dest="loglevel", const=logging.DEBUG)
    parser.add_option("-p", "--passwords", dest="passwords")
    parser.add_option("-j", "--concurrency", dest="concurrency", type="int")
    parser.add_option("--dry-run", action="store_true", dest="dryrun")

    options, args = parser.parse_args()

    logging.basicConfig(level=options.loglevel, format="%(asctime)s - %(message)s")
    logging.getLogger("boto").setLevel(logging.WARN)
    logging.getLogger("paramiko").setLevel(logging.WARN)
    logging.getLogger('requests').setLevel(logging.WARN)

    if not options.regions:
        parser.error("at least one region is required")

    if not options.secrets:
        parser.error("secrets are required")

    if not options.passwords:
        parser.error("passwords are required")

    secrets = json.load(open(options.secrets))
    passwords = json.load(open(options.passwords))

    aws_stop_idle(secrets, passwords, options.regions, dryrun=options.dryrun, concurrency=options.concurrency)
