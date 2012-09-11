#!/usr/bin/env python
try:
    import simplejson as json
    assert json
except ImportError:
    import json

import boto.ec2
import boto.route53
import boto.route53.record
import logging
log = logging.getLogger(__name__)


def get_all_instances(conn):
    retval = []
    for r in conn.get_all_instances():
        for i in r.instances:
            retval.append(i)
    return retval


def update_route53(secrets, regions, zoneid):
    r53 = boto.route53.connection.Route53Connection(**secrets)

    if not regions:
        # Look at all regions
        log.debug("loading all regions")
        regions = [r.name for r in boto.ec2.regions(**secrets)]

    existing_dns = {}
    for r in r53.get_all_rrsets(zoneid):
        if r.type == 'A':
            existing_dns[r.name] = r.resource_records

    dns_changes = boto.route53.record.ResourceRecordSets(r53, zoneid)
    seen_hosts = set()
    changed = False

    # Grab a list of all our instances
    for r in regions:
        conn = boto.ec2.connect_to_region(r, **secrets)
        if not conn:
            log.error("couldn't connect to %s", r)
            continue
        log.debug("connected to %s: %s", conn, r)
        instances = get_all_instances(conn)
        for i in instances:
            if 'Name' not in i.tags:
                continue
            if i.state in ('terminated',):
                continue
            if i.ip_address is not None:
                ip = i.ip_address
            elif i.private_ip_address is not None:
                ip = i.private_ip_address
            else:
                log.debug("Skipping %s - no ip address", i.tags['Name'])
                continue

            name = "%s.releng.ec2.mozilla.com." % i.tags['Name']
            seen_hosts.add(name)

            if name in existing_dns:
                if existing_dns[name] != [ip]:
                    log.info("Deleting name for %s", name)
                    change = dns_changes.add_change("DELETE", name, "A")
                    change.add_value(existing_dns[name][0])
                    changed = True
                else:
                    # nothing to do
                    log.debug("Nothing to do for %s", name)
                    continue

            log.info("Adding %s -> '%s'", name, ip)
            change = dns_changes.add_change("CREATE", name, "A")
            change.add_value(ip)
            changed = True

    for name in existing_dns:
        if name not in seen_hosts:
            log.info("Deleting name for %s; doesn't appear to be used", name)
            change = dns_changes.add_change("DELETE", name, "A")
            change.add_value(existing_dns[name][0])
            changed = True

    if changed:
        log.info("Committing...")
        dns_changes.commit()

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.set_defaults(
        regions=[],
        secrets=None,
        loglevel=logging.INFO,
        zoneid=None,
    )

    parser.add_option("-z", "--zoneid", dest="zoneid")
    parser.add_option("-r", "--region", action="append", dest="regions")
    parser.add_option("-k", "--secrets", dest="secrets")
    parser.add_option("-v", "--verbose", action="store_const", dest="loglevel", const=logging.DEBUG)

    options, args = parser.parse_args()

    logging.basicConfig(level=options.loglevel, format="%(asctime)s - %(message)s")
    logging.getLogger("boto").setLevel(logging.INFO)

    if not options.secrets:
        parser.error("secrets are required")

    secrets = json.load(open(options.secrets))

    update_route53(secrets, options.regions, options.zoneid)
