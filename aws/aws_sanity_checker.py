#!/usr/bin/env python

import argparse
import json
import logging
import time
import calendar
from boto.ec2 import connect_to_region

log = logging.getLogger(__name__)
REGIONS = ('us-east-1', 'us-west-2')
KNOWN_TYPES = ('puppetmaster', 'buildbot-master', 'dev-linux64', 'bld-linux64',
               'try-linux64', 'tst-linux32', 'tst-linux64', 'dev')

EXPECTED_MAX_UPTIME = {
    "puppetmaster": "meh",
    "buildbot-master": "meh",
    "dev": "meh",
    "dev-linux64": 8,
    "bld-linux64": 12,
    "try-linux64": 12,
    "tst-linux32": 12,
    "tst-linux64": 12,
    "default": 4
}


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
    instances = reduce(lambda a, b: a + b, [r.instances for r in res])
    return instances


def parse_launch_time(launch_time):
    launch_time = calendar.timegm(time.strptime(
        launch_time[:19], '%Y-%m-%dT%H:%M:%S'))
    return launch_time


def get_bad_type(instances):
    bad_types = []
    for i in instances:
        ins_type = i.tags.get('moz-type')
        if ins_type not in KNOWN_TYPES:
            bad_types.append((i, 'Uknown type "%s"' % ins_type))
    return bad_types


def get_bad_state(instances):
    bad_state = []
    for i in instances:
        ins_state = i.tags.get('moz-state')
        if ins_state != "ready":
            bad_state.append((i, 'Uknown state "%s"' % ins_state))
    return bad_state


def get_uptime(instance):
    return (time.time() - parse_launch_time(instance.launch_time)) / 3600


def get_long_running(instances, expected_max_uptime):
    long_running = []
    for i in instances:
        if i.state == "stopped":
            continue
        uptime = get_uptime(i)
        moz_type = i.tags.get('moz-type', 'default')
        expected_max = expected_max_uptime.get(moz_type)
        if expected_max == "meh":
            continue
        if uptime > expected_max:
            long_running.append((i, "up for %i hours" % uptime))
    return long_running


def format_instance_list(instances):
    for n, (i, msg) in enumerate(instances):
        print n, "{name} ({id}, {region}): {msg}".format(
            name=i.tags.get('Name'), id=i.id, region=i.region.name,
            msg=msg)


def instance_sanity_check(instances):
    bad_type = get_bad_type(instances=instances)
    bad_state = get_bad_state(instances=instances)
    long_running = get_long_running(instances=instances,
                                    expected_max_uptime=EXPECTED_MAX_UPTIME)
    if bad_type:
        print "==== Instances with uknown type ===="
        format_instance_list(sorted(bad_type, key=lambda x: x[0].region.name))
        print
    if bad_state:
        print "==== Instances with uknown state ===="
        format_instance_list(sorted(bad_state, key=lambda x: x[0].region.name))
        print
    if long_running:
        print "==== Long running instances ===="
        format_instance_list(sorted(long_running, reverse=True,
                                    key=lambda x: get_uptime(x[0])))
        print


def get_not_attached(volumes):
    bad_volumes = []
    for v in volumes:
        if v.status != "in-use":
            bad_volumes.append((v, "Not attached"))
    return bad_volumes


def volume_sanity_check(volumes):
    not_attached = get_not_attached(volumes)
    if not_attached:
        print "==== Not attached volumes ===="
        for i, (v, msg) in enumerate(sorted(not_attached,
                                     key=lambda x: x[0].region.name)):
            print i, "%s %s: %s" % (v.id, v.region.name, msg)
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
    instance_sanity_check(all_instances)
    volume_sanity_check(all_volumes)
