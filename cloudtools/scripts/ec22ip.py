#!/usr/bin/env python

import re

from cloudtools.aws import get_aws_connection


def main():
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option("-r", "--region", dest="region", help="region to use",
                      default="us-east-1")

    options, args = parser.parse_args()
    if not args:
        parser.error("at least one instance name is required")

    hosts_re = [re.compile(x) for x in args]

    conn = get_aws_connection(options.region)

    res = conn.get_all_instances()
    if res:
        instances = reduce(lambda a, b: a + b, [r.instances for r in res])
        for i in instances:
            for mask in hosts_re:
                hostname = i.tags.get('FQDN', i.tags.get('Name', ''))
                if mask.search(hostname) and i.private_ip_address:
                    print i.private_ip_address, hostname

if __name__ == '__main__':
    main()
