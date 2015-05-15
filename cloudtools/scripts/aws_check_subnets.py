#!/usr/bin/env python
"""
Nagios check for checking that there are enough free IP addresses in AWS subnets.

Return codes:
    0 - everything OK!
    1 - some availability zones below warning threshold
    2 - some availability zones below critical threshold

Sample nagios output:

    CRITICAL: subnet us-east-1c/test has only 2 free ips (threshold is 5)
    OK: us-west-1c/try has 3 free ips
"""
from __future__ import print_function
from cloudtools.aws import get_vpc
from collections import defaultdict

import logging
log = logging.getLogger(__name__)


def get_subnets(regions):
    """
    Returns all subnet objects from the specified regions
    """
    subnets = []
    for r in regions:
        log.debug('getting subnets for %s', r)
        vpc = get_vpc(r)
        subnets.extend(vpc.get_all_subnets())
    return subnets


def filter_subnets_by_name(subnets, names):
    """
    Returns a generator that yields subnets whose 'Name' tag is in `names`
    """
    return (s for s in subnets if s.tags.get('Name') in names)


def group_subnets_by_type(subnets):
    """
    Return a dictionary mapping (subnet AZ, subnet name) to the list of subnets
    in that AZ with that name.
    """
    # Group by availability_zone, Name
    grouped_subnets = defaultdict(list)

    for s in subnets:
        # Ignore stuff without a name
        if 'Name' not in s.tags:
            log.debug('skipping %s in %s - no name', s, s.region)
            continue

        grouped_subnets[s.availability_zone, s.tags['Name']].append(s)
    return grouped_subnets


def count_free_ips(grouped_subnets):
    """
    Return a dictionary mapping (subnet AZ, subnet name) to count of free IP addresses
    """
    count_by_group = {}
    for (az, name), subnets in grouped_subnets.iteritems():
        count_by_group[az, name] = sum(s.available_ip_address_count for s in subnets)
    return count_by_group


def report_free_ips(grouped_subnets, warn_threshold, crit_threshold):
    """
    Generate a report of free IP addresses and print to stdout.

    Returns an exit code suitable for use as the process status of a nagios check. i.e.
    0 - OK
    1 - WARNING
    2 - CRITICAL
    """
    exit_code = 0
    count_by_group = count_free_ips(grouped_subnets)

    for (az, name), count in sorted(count_by_group.items(), key=lambda x: x[1]):
        if count <= crit_threshold:
            print('CRITICAL: subnet {}/{} has only {} free ips (threshold is {})'.format(
                az, name, count, crit_threshold))
            exit_code = max(2, exit_code)
        elif count <= warn_threshold:
            print('WARNING: subnet {}/{} has only {} free ips (threshold is {})'.format(
                az, name, count, warn_threshold))
            exit_code = max(1, exit_code)
        else:
            print('OK: subnet {}/{} has {} free ips'.format(
                az, name, count))

    return exit_code


def main():
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.set_defaults(
        loglevel=logging.INFO,
        regions=[],
        subnet_names=[],
        warn_threshold=10,
        crit_threshold=5,
    )
    parser.add_argument('-v', '--verbose', dest='loglevel', action='store_const', const=logging.DEBUG)
    parser.add_argument('-q', '--quiet', dest='loglevel', action='store_const', const=logging.WARN)
    parser.add_argument('-r', '--region', dest='regions', action='append', required=True)
    parser.add_argument('-s', '--subnet-name', dest='subnet_names', action='append', required=True)

    # Nagios options
    parser.add_argument('-w', '--warn-threshold', dest='warn_threshold',
                        help='threshold at which to emit nagios warning', type=int)
    parser.add_argument('-c', '--crit-threshold', dest='crit_threshold',
                        help='threshold at which to emit nagios critical alert', type=int)

    args = parser.parse_args()

    all_subnets = get_subnets(args.regions)
    my_subnets = filter_subnets_by_name(all_subnets, args.subnet_names)
    grouped_subnets = group_subnets_by_type(my_subnets)

    exit_code = report_free_ips(grouped_subnets, args.warn_threshold, args.crit_threshold)
    exit(exit_code)

if __name__ == '__main__':
    main()
