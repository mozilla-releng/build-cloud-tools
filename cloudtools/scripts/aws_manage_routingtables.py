#!/usr/bin/env python
import boto.vpc
import yaml
import dns.resolver
import logging
import sys
import json
import urllib
from IPy import IP

log = logging.getLogger(__name__)
_dns_cache = {}


def get_connection(region):
    return boto.vpc.connect_to_region(region)


def load_config(filename):
    return yaml.load(open(filename))


def load_aws_ranges():
    url = "https://ip-ranges.amazonaws.com/ip-ranges.json"
    ranges = json.load(urllib.urlopen(url))
    return [p['ip_prefix'] for p in ranges['prefixes'] if
            (p['service'] in ('S3', 'CLOUDFRONT') and p['region'] in ('us-east-1', 'us-west-1', 'us-west-2'))]


def resolve_host(hostname):
    if hostname in _dns_cache:
        return _dns_cache[hostname]
    log.info("resolving host %s", hostname)
    ips = dns.resolver.query(hostname, "A")
    ips = [i.to_text() for i in ips]
    _dns_cache[hostname] = ips
    return ips


def get_nat_gateway(region):
    # development shifted from boto to boto3 before NAT gateways were added to AWS :/
    # https://github.com/boto/boto/issues/3443
    import boto3
    client = boto3.client('ec2', region_name=region)
    return client.describe_nat_gateways()['NatGateways'][0]


def sync_tables(conn, my_tables, remote_tables, aws_ranges):
    # Check that remote tables don't have overlapping names
    seen_names = set()
    for t in remote_tables[:]:
        name = t.tags.get('Name')
        if not name:
            log.warn("table %s has no name", t.id)
            remote_tables.remove(t)
            continue
        if name in seen_names:
            log.warn("table %s has a duplicate name %s; skipping", t.id, name)
            remote_tables.remove(t)
        seen_names.add(name)

    for name in my_tables:
        if name not in seen_names:
            # TODO: Allow multiple VPCs to exist per region
            vpc_id = conn.get_all_vpcs()[0].id
            log.info("remote table %s doesn't exist; creating in vpc %s", name, vpc_id)
            t = conn.create_route_table(vpc_id)
            t.add_tag('Name', name)
            remote_tables.append(t)

    # Sync remote tables
    for t in remote_tables:
        name = t.tags['Name']
        if name not in my_tables:
            if raw_input("table %s doesn't exist in local config; delete? (y/N)" % t.id) == 'y':
                log.warn("DELETING %s", t.id)
                # TODO
            continue

        my_t = my_tables[name]

        # Now look at routes
        remote_routes = set()
        for r in t.routes:
            remote_routes.add((r.destination_cidr_block, r.gateway_id, r.instance_id))

        my_routes = set()
        IGW = None
        VGW = None
        NAT = None

        # Resolve hostnames
        to_delete = set()
        to_add = set()
        # Add Amazon routes if required
        if 'AMAZON' in my_t['routes']:
            log.info('Adding amazon routes to %s', name)
            for prefix in aws_ranges:
                my_t['routes'][prefix] = 'IGW'
            del my_t['routes']['AMAZON']

        for cidr, dest in my_t['routes'].iteritems():
            if "/" not in cidr:
                for ip in resolve_host(cidr):
                    log.info("adding %s for %s", ip, cidr)
                    to_add.add(("%s/32" % ip, dest))
                to_delete.add(cidr)

        for d in to_delete:
            del my_t['routes'][d]

        for cidr, dest in to_add:
            my_t['routes'][cidr] = dest

        for cidr, dest in my_t['routes'].iteritems():
            assert "/" in cidr
            instance_id = None
            gateway_id = None
            if dest == "IGW":
                # Use our VPC's IGW
                if IGW is None:
                    IGW = conn.get_all_internet_gateways()[0]
                gateway_id = IGW.id
            elif dest == "VGW":
                # Use our VPC's IGW
                if VGW is None:
                    VGW = conn.get_all_vpn_gateways()[0]
                gateway_id = VGW.id
            elif dest == "NAT":
                # Use our VPC's NAT gateway
                if NAT is None:
                    log.info('Looking up NAT gateway')
                    NAT = get_nat_gateway(conn.region.name)
                gateway_id = NAT['NatGatewayId']
            elif dest == 'local':
                gateway_id = 'local'
            elif dest and dest.startswith("i-"):
                instance_id = dest
            my_routes.add((cidr, gateway_id, instance_id))

        # Delete extra routes first, in case we need to change the gateway of
        # some route
        extra_routes = remote_routes - my_routes
        for cidr, gateway_id, instance_id in extra_routes:
            log.info("%s - deleting route to %s via %s %s", t.id, cidr, gateway_id, instance_id)

            for my_cidr, my_gw, my_id in my_routes:
                if IP(cidr) in IP(my_cidr) and my_gw == gateway_id:
                    log.info('this route is covered by %s', my_cidr)

            if raw_input("delete? (y/N) ") == 'y':
                conn.delete_route(t.id, cidr)

        # Add missing routes
        missing_routes = my_routes - remote_routes
        for cidr, gateway_id, instance_id in missing_routes:
            log.info("%s - adding route to %s via %s %s", t.id, cidr, gateway_id, instance_id)
            conn.create_route(t.id, cidr, gateway_id=gateway_id, instance_id=instance_id)

        # TODO: Set default, manage subnets


def main():
    logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)

    log.debug("Parsing file")
    rt_defs = load_config(sys.argv[1])

    log.debug("Getting AWS IP ranges")
    aws_ranges = load_aws_ranges()

    regions = set(rt_defs.keys())

    log.info("Working in regions %s", regions)

    for region in regions:
        log.info("Working in %s", region)
        conn = get_connection(region)
        remote_tables = conn.get_all_route_tables()

        # Compare vs. our configs
        my_tables = rt_defs[region]

        sync_tables(conn, my_tables, remote_tables, aws_ranges)


if __name__ == '__main__':
    main()
