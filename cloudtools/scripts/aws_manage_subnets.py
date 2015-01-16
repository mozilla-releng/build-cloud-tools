#!/usr/bin/env python
import cloudtools.aws
import itertools
import logging
import sys
import yaml

from netaddr import IPNetwork, IPSet

log = logging.getLogger(__name__)


def load_config(filename):
    return yaml.load(open(filename))


def sync_subnets(conn, config):
    log.debug("loading routing tables")
    routing_tables = conn.get_all_route_tables()
    route_tables_by_name = {r.tags.get('Name'): r for r in routing_tables}
    route_tables_by_subnet_id = {}
    for r in routing_tables:
        for a in r.associations:
            route_tables_by_subnet_id[a.subnet_id] = r

    # Get list of AZs
    zones = conn.get_all_zones()

    for vpc_id in config:
        # Get a list of all the remote subnets
        remote_subnets = conn.get_all_subnets(filters={'vpcId': vpc_id})

        seen = set()

        # Go through our config, adjusting or any subnets as appropriate
        for cidr, block_config in config[vpc_id].items():
            cidr_net = IPNetwork(cidr)
            table_name = block_config.get('routing_table')
            if table_name and table_name not in route_tables_by_name:
                log.warn("couldn't find routing table %s for block %s", table_name, cidr)
                log.warn("skipping rest of %s", cidr)
                continue
            my_rt = route_tables_by_name[table_name]

            ip_set = IPSet(cidr_net)

            for s in remote_subnets:
                if IPNetwork(s.cidr_block) in cidr_net:
                    ip_set.remove(s.cidr_block)
                    if s.tags.get('Name') != block_config['name']:
                        log.info("Setting Name of %s to %s", s, block_config['name'])
                        s.add_tag('Name', block_config['name'])

                        if s.id in route_tables_by_subnet_id:
                            remote_rt = route_tables_by_subnet_id[s.id]
                        else:
                            remote_rt = route_tables_by_subnet_id[None]
                        if remote_rt != my_rt:
                            log.info(
                                "Changing routing table for %s (%s) to %s (%s)",
                                s, s.tags.get('Name'), my_rt,
                                my_rt.tags.get('Name'))
                            if raw_input("(y/N) ") == "y":
                                conn.associate_route_table(my_rt.id, s.id)
                    seen.add(s)

            # Are we missing any subnets?
            # If so, create them!
            # TODO: We want to evenly distribute the ip range over the
            # configured availability zones, without dividing smaller than a
            # /25 network (128 ips, at least 2 of which are reserved)
            # For now we'll just split them as small as /24, and then assign
            # them into the subnets
            while ip_set:
                log.info("%s - %s isn't covered by any subnets", cidr, ip_set)
                my_zones = [z for z in zones if z.name not in block_config.get('skip_azs', [])]

                remaining_cidrs = list(ip_set.iter_cidrs())
                remaining_cidrs.sort(key=lambda s: s.size, reverse=True)
                for s in remaining_cidrs[:]:
                    if s.prefixlen < 24:
                        added = list(s.subnet(24))
                        remaining_cidrs.remove(s)
                        remaining_cidrs.extend(added)
                    ip_set.remove(s)

                zg = itertools.cycle(my_zones)
                while remaining_cidrs:
                    c = remaining_cidrs.pop()
                    z = next(zg)
                    log.info("creating subnet %s in %s/%s", c, z.name, vpc_id)
                    if raw_input("(y/N) ") == "y":
                        log.debug("creating subnet")
                        s = conn.create_subnet(vpc_id, c, z.name)
                        log.debug("adding tag")
                        # TODO: sometimes the subnet isn't actually created by
                        # the time we try and add the tag, so get a 400 error
                        s.add_tag('Name', block_config['name'])
                        log.debug("associating routing")
                        conn.associate_route_table(my_rt.id, s.id)

        local_missing = set(remote_subnets) - seen
        for m in local_missing:
            log.info("%s:%s (name: %s) is unmanaged", m.id, m.cidr_block, m.tags.get('Name'))


def main():
    logging.getLogger('boto').setLevel(logging.INFO)
    logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.DEBUG)

    log.debug("parsing file")
    config = load_config(sys.argv[1])

    for region in config.keys():
        log.info("working in %s", region)
        conn = cloudtools.aws.get_vpc(region)
        sync_subnets(conn, config[region])


if __name__ == '__main__':
    main()
