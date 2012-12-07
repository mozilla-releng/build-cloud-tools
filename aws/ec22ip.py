#!/usr/bin/env python

import re
import json
from boto.ec2 import connect_to_region


if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.set_defaults(
            region="us-west-1",
            secrets=None,
            )
    parser.add_option("-r", "--region", dest="region", help="region to use")
    parser.add_option("-k", "--secrets", dest="secrets", help="file where secrets can be found")

    options, args = parser.parse_args()
    if not args:
        parser.error("at least one instance name is required")

    if not options.secrets:
        parser.error("secrets are required")

    hosts_re = [re.compile(x) for x in args]
    secrets = json.load(open(options.secrets))
    conn = connect_to_region(options.region,
            aws_access_key_id=secrets['aws_access_key_id'],
            aws_secret_access_key=secrets['aws_secret_access_key'])
    res = conn.get_all_instances()
    instances = reduce(lambda a,b: a+b, [r.instances for r in res])
    for i in instances:
        for mask in hosts_re:
            if mask.search(i.tags.get('Name', '')):
                print i.private_ip_address, i.tags.get('Name')
