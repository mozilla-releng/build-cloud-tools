#!/usr/bin/env python

import argparse
import json
import logging
import time
import calendar
import collections
import re
from boto.ec2 import connect_to_region

log = logging.getLogger(__name__)
REGIONS = ('us-east-1', 'us-west-2')
KNOWN_TYPES = ('puppetmaster', 'buildbot-master', 'dev-linux64', 'bld-linux64',
               'try-linux64', 'tst-linux32', 'tst-linux64', 'tst-win64', 'dev',
               'servo-linux64', 'packager', 'vcssync', 'infra')

EXPECTED_MAX_UPTIME = {
    "puppetmaster": "meh",
    "buildbot-master": "meh",
    "dev": "meh",
    "infra": "meh",
    "vcssync": "meh",
    "dev-linux64": 8,
    "bld-linux64": 24,
    "try-linux64": 12,
    "tst-linux32": 12,
    "tst-linux64": 12,
    "servo-linux64": 8,
    "default": 4
}

EXPECTED_MAX_DOWNTIME = {
    "puppetmaster": 0,
    "buildbot-master": 0,
    "dev": 0,
    "infra": 0,
    "vcssync": 0,
    "dev-linux64": 72,
    "bld-linux64": 72,
    "try-linux64": 72,
    "tst-linux32": 72,
    "tst-linux64": 72,
    "servo-linux64": 72,
    "packager": "meh",
    "default": 24
}


def is_beanstalk_instance(i):
    return i.tags.get("elasticbeanstalk:environment-name") is not None


def get_connection(region, secrets):
    if secrets:
        conn = connect_to_region(
            region,
            aws_access_key_id=secrets['aws_access_key_id'],
            aws_secret_access_key=secrets['aws_secret_access_key']
        )
    else:
        conn = connect_to_region(region)
    return conn


def get_all_instances(conn):
    res = conn.get_all_instances()
    instances = []
    if res:
        instances = reduce(lambda a, b: a + b, [r.instances for r in res])
    # Skip instances managed by Elastic Beanstalk
    return [i for i in instances if not is_beanstalk_instance(i)]


def parse_launch_time(launch_time):
    launch_time = calendar.timegm(time.strptime(
        launch_time[:19], '%Y-%m-%dT%H:%M:%S'))
    return launch_time


def get_bad_type(instances):
    bad_types = []
    for i in instances:
        ins_type = i.tags.get('moz-type')
        if ins_type not in KNOWN_TYPES:
            bad_types.append((i, 'Unknown type "%s"' % ins_type))
    return bad_types


def get_bad_state(instances):
    bad_state = []
    for i in instances:
        ins_state = i.tags.get('moz-state')
        if ins_state != "ready":
            bad_state.append((i, 'Unknown state "%s"' % ins_state))
    return bad_state


def get_loaned(instances):
    ret = []
    loaned = [i for i in instances if i.tags.get("moz-loaned-to")]
    for i in loaned:
        bug_string = "an unknown bug"
        if i.tags.get("moz-bug"):
            bug_string = "bug %s" % i.tags.get("moz-bug")
        if i.state == "running":
            uptime = get_uptime(i)
            ret.append((uptime, i, "Loaned to %s in %s, up for %i hours" % (
                i.tags["moz-loaned-to"], bug_string, uptime)))
        else:
            ret.append((None, i, "Loaned to %s in %s, %s" % (i.tags["moz-loaned-to"],
                                                             bug_string,
                                                             i.state)))
    if ret:
        # sort by uptime, reconstruct ret
        ret = [(e[1], e[2]) for e in reversed(sorted(ret, key=lambda x: x[0]))]
    return ret


def get_uptime(instance):
    return (time.time() - parse_launch_time(instance.launch_time)) / 3600


def get_stale(instances, expected_stale_time, running_only=True):
    long_running = []
    for i in instances:
        if running_only:
            if i.state == "stopped":
                continue
        else:
            if i.state != "stopped":
                continue

        # Ignore Loaned (we have a separate section in report for that)
        if i.tags.get("moz-loaned-to"):
            continue

        uptime = get_uptime(i)
        moz_type = i.tags.get('moz-type', 'default')
        expected_max = expected_stale_time.get(moz_type)
        if expected_max == "meh":
            continue
        if uptime > expected_max:
            up_down = "up"
            if not running_only:
                up_down = "down"
            long_running.append((i, "%s for %i hours" % (up_down, uptime)))
    return long_running


def format_instance_list(instances):
    for n, (i, msg) in enumerate(instances):
        print n, "{name} ({id}, {region}): {msg}".format(
            name=i.tags.get('Name'), id=i.id, region=i.region.name,
            msg=msg)


def instance_sanity_check(instances):
    bad_type = get_bad_type(instances=instances)
    bad_state = get_bad_state(instances=instances)
    long_running = get_stale(instances=instances,
                             expected_stale_time=EXPECTED_MAX_UPTIME)
    long_stopped = get_stale(instances=instances,
                             expected_stale_time=EXPECTED_MAX_DOWNTIME,
                             running_only=False)
    loaned = get_loaned(instances)
    if long_running:
        print "==== Long running instances ===="
        format_instance_list(sorted(long_running, reverse=True,
                                    key=lambda x: get_uptime(x[0])))
        print
    if loaned:
        print "==== Loaned ===="
        format_instance_list(loaned)
        print
    if bad_type:
        print "==== Instances with unknown type ===="
        format_instance_list(sorted(bad_type, key=lambda x: x[0].region.name))
        print
    if bad_state:
        print "==== Instances with unknown state ===="
        format_instance_list(sorted(bad_state, key=lambda x: x[0].region.name))
        print
    if long_stopped:
        print "==== Instances stopped for a while ===="
        format_instance_list(sorted(long_stopped, reverse=True,
                                    key=lambda x: get_uptime(x[0])))
        print


def get_not_attached(volumes):
    bad_volumes = []
    for v in volumes:
        if v.status != "in-use":
            bad_volumes.append((v, "Not attached"))
    return bad_volumes


def volume_sanity_check(volumes):
    total = sum(v.size for v in volumes)
    not_attached = get_not_attached(volumes)
    print "Volume usage: %sG" % total
    if not_attached:
        print "==== Not attached volumes ===="
        for i, (v, msg) in enumerate(sorted(not_attached,
                                     key=lambda x: x[0].region.name)):
            print i, "%s %s: %s" % (v.id, v.region.name, msg)
        print


def instance_stats(instances, regions):
    states = collections.defaultdict(int)
    types = collections.defaultdict(list)
    type_regexp = re.compile(r"(.*?)-?\d+$")
    state = {}
    for r in regions:
        states[r] = collections.defaultdict(int)
    for i in instances:
        states[i.region.name][i.state] += 1
        name = i.tags.get("Name")
        # Try to remove trailing digits or use the whole name
        if name:
            m = type_regexp.match(name)
            if m:
                type_name = m.group(1)
            else:
                type_name = name
        else:
            type_name = "unknown"
        running = bool(i.state != "stopped")
        # type: [True, True, False, ...]
        types[type_name].append(running)

    print "==== %s instances in total ====" % len(instances)
    for r in sorted(regions):
        print r
        for state, n in states[r].iteritems():
            print "  %s: %s" % (state, n)
    print
    print "==== Type breakdown ===="
    # Sort by amount of running instances
    for t, n in sorted(types.iteritems(), key=lambda x: x[1].count(True),
                       reverse=True):
        print "%s: running: %s, stopped: %s" % (t, n.count(True),
                                                n.count(False))
    print

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
        secrets = None

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.quiet:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.ERROR)

    if not args.regions:
        args.regions = REGIONS
    all_instances = []
    all_volumes = []
    for region in args.regions:
        conn = get_connection(region, secrets)
        all_instances.extend(get_all_instances(conn))
        all_volumes.extend(conn.get_all_volumes())
    instance_stats(all_instances, args.regions)
    instance_sanity_check(all_instances)
    volume_sanity_check(all_volumes)
