import time
import sqlalchemy as sa
import re
import logging
import requests
from sqlalchemy.engine.reflection import Inspector
from collections import defaultdict

from .jacuzzi import get_allocated_slaves

log = logging.getLogger(__name__)
ACTIVITY_BOOTING, ACTIVITY_STOPPED = ("booting", "stopped")


def find_pending(dburl):
    db = sa.create_engine(dburl)
    inspector = Inspector(db)
    # Newer buildbot has a "buildrequest_claims" table
    if "buildrequest_claims" in inspector.get_table_names():
        query = sa.text("""
        SELECT buildername, id FROM
               buildrequests WHERE
               complete=0 AND
               submitted_at > :yesterday AND
               submitted_at < :toonew AND
               (select count(brid) from buildrequest_claims
                       where brid=id) = 0""")
    # Older buildbot doesn't
    else:
        query = sa.text("""
        SELECT buildername, id FROM
               buildrequests WHERE
               complete=0 AND
               claimed_at=0 AND
               submitted_at > :yesterday AND
               submitted_at < :toonew""")

    result = db.execute(
        query,
        yesterday=time.time() - 86400,
        toonew=time.time() - 10
    )
    retval = result.fetchall()
    return retval


def map_builders(pending, builder_map):
    """Map pending builder names to instance types"""
    type_map = defaultdict(int)
    for pending_buildername, _ in pending:
        for buildername_exp, moz_instance_type in builder_map.items():
            if re.match(buildername_exp, pending_buildername):
                slaveset = get_allocated_slaves(pending_buildername)
                log.debug("%s instance type %s slaveset %s",
                          pending_buildername, moz_instance_type, slaveset)
                type_map[moz_instance_type, slaveset] += 1
                break
        else:
            log.debug("%s has pending jobs, but no instance types defined",
                      pending_buildername)
    return type_map


def get_tacfile(ssh_client):
    return ssh_client.get_stdout("cat /builds/slave/buildbot.tac")


def get_buildbot_master(ssh_client, masters_json):
    tacfile = get_tacfile(ssh_client)
    host = re.search("^buildmaster_host = '(.*?)'$", tacfile, re.M)
    host = host.group(1)
    port = None
    for master in masters_json:
        if master["hostname"] == host:
            port = master["http_port"]
            break
    assert host and port
    return host, port


def graceful_shutdown(ssh_client, masters_json):
    # Find out which master we're attached to by looking at buildbot.tac
    log.debug("%s - looking up which master we're attached to",
              ssh_client.name)
    host, port = get_buildbot_master(ssh_client, masters_json)

    url = "http://{host}:{port}/buildslaves/{name}/shutdown".format(
        host=host, port=port, name=ssh_client.name)
    log.debug("%s - POSTing to %s", ssh_client.name, url)
    requests.post(url, allow_redirects=False)


def get_last_activity(ssh_client):
    slave_time = ssh_client.get_stdout("date +%Y%m%d%H%M%S").strip()
    slave_time = time.mktime(time.strptime(slave_time, "%Y%m%d%H%M%S"))
    uptime = float(ssh_client.get_stdout("cat /proc/uptime").split()[0])

    if uptime < 3 * 60:
        # Assume we're still booting
        log.debug("%s - uptime is %.2f; assuming we're still booting up",
                  ssh_client.name, uptime)
        return ACTIVITY_BOOTING

    stdout = ssh_client.get_stdout(
        "tail -n 100 /builds/slave/twistd.log.1 /builds/slave/twistd.log")

    last_activity = None
    running_command = False
    t = time.time()
    line = ""
    for line in stdout.splitlines():
        m = re.search(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if m:
            t = time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            t = time.mktime(t)
        else:
            # Not sure what to do with this line...
            continue

        # uncomment to dump out ALL the lines
        # log.debug("%s - %s", name, line.strip())

        if "RunProcess._startCommand" in line or "using PTY: " in line:
            log.debug("%s - started command - %s", ssh_client.name,
                      line.strip())
            running_command = True
        elif "commandComplete" in line or "stopCommand" in line:
            log.debug("%s - done command - %s", ssh_client.name, line.strip())
            running_command = False

        if "Shut Down" in line:
            # Check if this happened before we booted, i.e. we're still booting
            # up
            if (slave_time - t) > uptime:
                log.debug(
                    "%s - shutdown line is older than uptime; assuming we're "
                    "still booting %s", ssh_client.name, line.strip())
                last_activity = ACTIVITY_BOOTING
            else:
                last_activity = ACTIVITY_STOPPED
        elif "I have a leftover directory" in line:
            # Ignore this, it doesn't indicate anything
            continue
        elif running_command:
            # We're in the middle of running something, so say that our last
            # activity is now (0 seconds ago)
            last_activity = 0
        else:
            last_activity = slave_time - t

    # If the last lines from the log are over 10 minutes ago, and are from
    # before our reboot, then try rebooting
    if (slave_time - t) > 10 * 60 and (slave_time - t) > uptime:
        log.debug(
            "%s - shut down happened %ss ago, but we've been up for %ss - %s",
            ssh_client.name, slave_time - t, uptime, line.strip())
        # If longer than 30 minutes, try rebooting
        if (slave_time - t) > 30 * 60:
            log.debug("%s - rebooting", ssh_client.name)
            ssh_client.reboot()

    # If there's *no* activity (e.g. no twistd.log files), and we've been up a
    # while, then reboot
    if last_activity is None and uptime > 15 * 60:
        log.debug("%s - no activity; rebooting", ssh_client.name)
        # If longer than 30 minutes, try rebooting
        ssh_client.reboot()

    log.debug("%s - %s - %s", ssh_client.name, last_activity, line.strip())
    return last_activity
