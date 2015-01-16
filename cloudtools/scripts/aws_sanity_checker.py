#!/usr/bin/env python
"""Generates a report of the AWS instance status"""

import argparse
import logging
import collections
import re

from cloudtools.aws.sanity import AWSInstance, aws_instance_factory, SLAVE_TAGS
from cloudtools.aws import get_aws_connection, DEFAULT_REGIONS

log = logging.getLogger(__name__)


def is_beanstalk_instance(i):
    """returns True if this is a beanstalk instance"""
    return i.tags.get("elasticbeanstalk:environment-name") is not None


def get_all_instances(connection):
    """gets all the instances from a connection"""
    res = connection.get_all_instances()
    instances = []
    if res:
        instances = reduce(lambda a, b: a + b, [r.instances for r in res])
    # Skip instances managed by Elastic Beanstalk
    return [i for i in instances if not is_beanstalk_instance(i)]


def report(items, message):
    """prints out the sanity check message"""
    if items:
        print "==== {message} ====".format(message=message)
        for num, item in enumerate(items):
            print "{num} {item}".format(num=num, item=item)
        print


def kill_and_filter_out_lazy_spot_instances(lazy):
    """ Terminate and filter out spot instances """
    if lazy.instance.spot_instance_request_id:
        lazy.instance.terminate()
        return False
    else:
        return True


def _report_lazy_running_instances(lazy):
    """reports the lazy long running instances"""
    lazy = [l for l in lazy if kill_and_filter_out_lazy_spot_instances(l)]
    if lazy:
        message = 'Lazy long running instances'
        lazy = sorted(lazy, reverse=True, key=lambda x: x.get_uptime())
        lazy = [i.longrunning_message() for i in lazy]
        report(lazy, message)


def _report_long_running_instances(long_running):
    """reports the long running instances"""
    message = 'Long running instances'
    # remove lazy instances...
    long_running = [i for i in long_running if not i.is_lazy()]
    if long_running:
        items = sorted(long_running, reverse=True,
                       key=lambda x: x.get_uptime())
        items = [i.longrunning_message() for i in items]
        report(items, message)
    else:
        print "==== No long running instances ===="
        print


def _report_loaned(loaned):
    """reports the loaned instances"""
    if loaned:
        items = [i.loaned_message() for i in loaned]
        message = "Loaned"
        report(items, message)
    else:
        print "==== No loaned instances ===="
        print


def _report_bad_type(bad_type):
    """reports the instances with a bad type"""
    if bad_type:
        message = "Instances with unknown type"
        # sort the instances by region
        items = sorted(bad_type, key=lambda x: x.get_region())
        # we need the unknown_type_message...
        items = [i.unknown_type_message() for i in items]
        report(items, message)
    else:
        print "==== No instances with unknown type ===="
        print


def _report_bad_state(bad_state):
    """reports the instances with a bad state"""
    if bad_state:
        message = "Instances with unknown state"
        items = sorted(bad_state, key=lambda x: x.get_region())
        items = [i.unknown_state_message() for i in items]
        report(items, message)
    else:
        print "==== No instances with unknown state ===="
        print


def _report_long_stopped(long_stopped):
    """reports the instances stopped for a while"""
    if long_stopped:
        message = "Instances stopped for a while"
        items = sorted(long_stopped, reverse=True,
                       key=lambda x: x.get_uptime())
        items = [i.stopped_message() for i in items]
        items = [i for i in items if i]
        report(items, message)
    else:
        print "==== No long stopped instances ===="
        print


def _report_impaired(impaired):
    """reports the impaired instances"""
    if impaired:
        print "=== Impaired instances ===="
        for num, instance in enumerate(impaired):
            print "{0} {1}".format(num, instance)
        print


def get_all_instance_status(connection, filters=None):
    """wrapper fot get_all_instance_status"""
    return connection.get_all_instance_status(filters=filters)


def get_impaired(connection, instances):
    """get the impaired instances"""
    # this method uses a filter and does not iterate all_instances
    impaired = []
    filters = {'instance-status.status': 'impaired'}
    impaired_ids = [i.id for i in get_all_instance_status(connection, filters)]
    for instance in instances:
        if instance.id in impaired_ids:
            aws_instance = AWSInstance(instance)
            if not aws_instance.get_instance_type() in SLAVE_TAGS:
                # just report impaired non slave instances
                impaired.append(aws_instance)
    return impaired


def _report_volume_sanity_check(volumes):
    """prints the Volume info"""
    total = sum(v.size for v in volumes)
    not_attached = get_not_attached(volumes)
    print "Volume usage: %sG" % total
    if not_attached:
        print "==== Not attached volumes ===="
        for instance, (volume, msg) in enumerate(
                sorted(not_attached, key=lambda x: x[0].region.name)):
            print instance, "%s %s: %s" % (volume.id, volume.region.name, msg)
        print


def _report_instance_stats(instances, regions):
    """prints the instances stats"""
    states = collections.defaultdict(int)
    types = collections.defaultdict(list)
    type_regexp = re.compile(r"(.*?)-?\d+$")
    state = {}
    for reg in regions:
        states[reg] = collections.defaultdict(int)
    for instance in instances:
        states[instance.region.name][instance.state] += 1
        name = instance.tags.get("Name")
        # Try to remove trailing digits or use the whole name
        if name:
            m = type_regexp.match(name)
            if m:
                type_name = m.group(1)
            else:
                type_name = name
        else:
            type_name = "unknown"
        running = bool(instance.state != "stopped")
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


def generate_report(connection, regions, instances, volumes, events_dir):
    """creates the final report"""
    aws_instances = []
    for instance in instances:
        aws_instances.append(aws_instance_factory(instance, events_dir))
    bad_type = [i for i in aws_instances if i.bad_type()]
    bad_state = [i for i in aws_instances if i.bad_state()]
    long_running = [i for i in aws_instances if i.is_long_running()]
    long_stopped = [i for i in aws_instances if i.is_long_stopped()]
    lazy = [i for i in long_running if i.is_lazy()]
    loaned = [i for i in aws_instances if i.is_loaned()]
    impaired = get_impaired(connection, instances)

    # create the report
    # lazy first!
    _report_lazy_running_instances(lazy)
    # some stats
    _report_instance_stats(instances, regions)
    # everything else
    _report_long_running_instances(long_running)
    _report_loaned(loaned)
    _report_bad_type(bad_type)
    _report_bad_state(bad_state)
    _report_long_stopped(long_stopped)
    _report_impaired(impaired)
    # one last thing, Volumes!
    _report_volume_sanity_check(volumes)


def get_not_attached(volumes):
    """gets a list of volumes not attached"""
    bad_volumes = []
    for volume in volumes:
        if volume.status != "in-use":
            bad_volumes.append((volume, "Not attached"))
    return bad_volumes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", dest="regions", action="append",
                        help="optional list of regions")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Supress logging messages")
    parser.add_argument("--events-dir", dest="events_dir",
                        help="cloudtrail logs event directory")
    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if args.verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.ERROR)

    if not args.regions:
        args.regions = DEFAULT_REGIONS
    all_instances = []
    all_volumes = []
    for region in args.regions:
        conn = get_aws_connection(region)
        all_instances.extend(get_all_instances(conn))
        all_volumes.extend(conn.get_all_volumes())

    generate_report(connection=conn,
                    regions=args.regions,
                    instances=all_instances,
                    volumes=all_volumes,
                    events_dir=args.events_dir)

if __name__ == '__main__':
    main()
