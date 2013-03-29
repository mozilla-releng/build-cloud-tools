#!/usr/bin/env python

import re
import json
from boto.ec2 import connect_to_region


if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option("-r", "--region", dest="region", help="region to use",
                      default="us-east-1")
    parser.add_option("-k", "--secrets", dest="secrets",
                      help="file where secrets can be found")

    options, args = parser.parse_args()
    if not args:
        parser.error("at least one instance name is required")

    hosts_re = [re.compile(x) for x in args]

    if not options.secrets:
        conn = connect_to_region(options.region)
    else:
        secrets = json.load(open(options.secrets))
        conn = connect_to_region(
            options.region, aws_access_key_id=secrets['aws_access_key_id'],
            aws_secret_access_key=secrets['aws_secret_access_key'])

    res = conn.get_all_instances()
    instances = reduce(lambda a, b: a + b, [r.instances for r in res])
    for i in instances:
        for mask in hosts_re:
            hostname = i.tags.get('FQDN', i.tags.get('Name', ''))
            if mask.search(hostname) and i.private_ip_address:
                print i.private_ip_address, hostname
