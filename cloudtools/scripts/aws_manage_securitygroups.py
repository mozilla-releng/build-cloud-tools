#!/usr/bin/env python
import re
import logging
import yaml
import boto.ec2
import dns.resolver
import sys
import time

from cloudtools.yaml import process_includes


# see http://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_Appendix_Limits.html
# note that "Rules" in that document actually refers to grants
MAX_GRANTS_PER_SG = 125

log = logging.getLogger(__name__)
port_re = re.compile(r'^(\d+)-(\d+)$')


def get_connection(region):
    return boto.ec2.connect_to_region(region)


def load_config(filename):
    return process_includes(yaml.load(open(filename)))


def get_remote_sg_by_name(groups, name):
    log.info("Looking for sg %s", name)
    for g in groups:
        if g.name == name:
            log.info("Found %s", g)
            return g
    log.info("Didn't find %s; returning None", name)


_dns_cache = {}


def resolve_host(hostname):
    if hostname in _dns_cache:
        return _dns_cache[hostname]
    log.info("resolving host %s", hostname)
    ips = dns.resolver.query(hostname, "A")
    ips = [i.to_text() for i in ips]
    _dns_cache[hostname] = ips
    return ips


def make_rules_for_def(rule):
    """Returns a set of rules for a given config definition. A rule is a
    (proto, from_port, to_port, hosts) tuple
    """
    retval = []
    proto = str(rule['proto'])
    if 'ports' in rule:
        ports = []
        for p in rule['ports']:
            p = str(p)
            mo = port_re.match(p)
            if mo:
                ports.append(tuple(mo.groups()))
            else:
                ports.append((p, p))
    else:
        ports = [(None, None)]
    hosts = rule['hosts']
    # Resolve the hostnames
    log.debug("%s %s %s", proto, ports, hosts)
    log.debug("Resolving hostnames")
    for h in hosts[:]:
        if '/' not in h:
            ips = resolve_host(h)
            hosts.remove(h)
            for ip in ips:
                hosts.append("%s/32" % ip)
    log.debug("%s %s %s", proto, ports, hosts)

    for from_port, to_port in ports:
        retval.append((proto, from_port, to_port, set(hosts)))
    return retval


def make_rules(sg_config):
    rules = {}
    for rule_def in sg_config.get('inbound', []):
        for proto, from_port, to_port, hosts in make_rules_for_def(rule_def):
            rules.setdefault(('inbound', proto, from_port, to_port),
                             set()).update(hosts)

    for rule_def in sg_config.get('outbound', []):
        for proto, from_port, to_port, hosts in make_rules_for_def(rule_def):
            rules.setdefault(('outbound', proto, from_port, to_port),
                             set()).update(hosts)

    return rules


def rules_from_sg(sg):
    rules = {}
    for rule in sg.rules:
        # ignore non-cidr grants (to other sg's)
        cidr_grants = set(g.cidr_ip for g in rule.grants if g.cidr_ip)
        if not cidr_grants:
            continue
        rules.setdefault(('inbound', rule.ip_protocol, rule.from_port,
                          rule.to_port), set()).update(cidr_grants)
    for rule in sg.rules_egress:
        # ignore non-cidr grants (to other sg's)
        cidr_grants = set(g.cidr_ip for g in rule.grants if g.cidr_ip)
        if not cidr_grants:
            continue
        rules.setdefault(
            ('outbound', rule.ip_protocol, rule.from_port, rule.to_port),
            set()).update(set(g.cidr_ip for g in rule.grants if g.cidr_ip))

    return rules


def add_hosts(sg, rule_key, hosts):
    if rule_key[0] == 'inbound':
        auth_func = sg.connection.authorize_security_group
    else:
        auth_func = sg.connection.authorize_security_group_egress

    for h in hosts:
        auth_func(
            group_id=sg.id,
            ip_protocol=rule_key[1],
            from_port=rule_key[2],
            to_port=rule_key[3],
            cidr_ip=h,
        )


def remove_hosts(sg, rule_key, hosts):
    if rule_key[0] == 'inbound':
        auth_func = sg.connection.revoke_security_group
    else:
        auth_func = sg.connection.revoke_security_group_egress

    for h in hosts:
        auth_func(
            group_id=sg.id,
            ip_protocol=rule_key[1],
            from_port=rule_key[2],
            to_port=rule_key[3],
            cidr_ip=h,
        )


def tags_to_filters(tags):
    f = {}
    for tag_name, tag_value in tags:
        f["tag:%s" % tag_name] = tag_value
    return f


def apply_to_object(sg, filters, get_func, set_func, prompt):
    # TODO: handle more than 1 security groups
    if not filters:
        log.warn("No interface filters to apply, skipping.")
        return
    elements = get_func(filters=tags_to_filters(filters.get("tags")))
    for e in elements:
        if sg.id not in [g.id for g in e.groups]:
            if prompt and \
                    raw_input("Add %s (%s) to %s (%s)? (y/N) " %
                              (sg.name, sg.id, e.tags.get("Name"),
                               e.id)) != 'y':
                continue
            log.info("Adding %s (%s) to %s (%s)" %
                     (sg.name, sg.id, e.tags.get("Name"), e.id))
            set_func(e.id, "groupset", [sg.id])


def sync_security_group(remote_sg, sg_config, prompt):
    rules = make_rules(sg_config)
    remote_rules = rules_from_sg(remote_sg)

    # Check if we need to add any rules
    for rule_key, hosts in rules.items():
        new_hosts = hosts - remote_rules.get(rule_key, set())
        if new_hosts:
            if prompt and \
                    raw_input("%s - Add rule for %s to %s? (y/N) " %
                              (remote_sg.name, rule_key, new_hosts)) != 'y':
                continue
            log.info("%s - adding rule for %s to %s", remote_sg.name, rule_key,
                     new_hosts)
            add_hosts(remote_sg, rule_key, new_hosts)

    # Now check if we should delete any rules
    for rule_key, hosts in remote_rules.items():
        old_hosts = hosts - rules.get(rule_key, set())
        if old_hosts:
            if prompt and \
                    raw_input("%s - Delete rule %s to %s (y/N) " %
                              (remote_sg.name, rule_key, old_hosts)) != 'y':
                continue
            log.info("%s - removing rule for %s to %s", remote_sg.name,
                     rule_key, old_hosts)
            remove_hosts(remote_sg, rule_key, old_hosts)
    apply_to_object(remote_sg, sg_config.get("apply-to", {}).get("instances"),
                    remote_sg.connection.get_only_instances,
                    remote_sg.connection.modify_instance_attribute,
                    prompt)
    apply_to_object(remote_sg, sg_config.get("apply-to", {}).get("interfaces"),
                    remote_sg.connection.get_all_network_interfaces,
                    remote_sg.connection.modify_network_interface_attribute,
                    prompt)


def main():
    logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)

    log.debug("Parsing file")
    sg_defs = load_config(sys.argv[1])

    # Get the security groups for all affected regions
    regions = set()
    for sg_name, sg_config in sg_defs.items():
        regions.update(sg_config['regions'])

    log.info("Working in regions %s", regions)

    security_groups_by_region = {}
    conns_by_region = {}
    for region in regions:
        log.info("Loading groups for %s", region)
        conn = get_connection(region)
        all_groups = conn.get_all_security_groups()
        conns_by_region[region] = conn
        security_groups_by_region[region] = all_groups

    prompt = True

    # look for too-big security groups
    ok = True
    for sg_name, sg_config in sg_defs.iteritems():
        rules = make_rules(sg_config)
        total_grants = sum([len(hosts) for hosts in rules.itervalues()])
        if total_grants > MAX_GRANTS_PER_SG:
            log.warning("Group %s has %d rules, more than the allowed %d",
                        sg_name, total_grants, MAX_GRANTS_PER_SG)
            ok = False
    if not ok:
        exit(1)

    # Now compare vs. our configs
    for sg_name, sg_config in sg_defs.items():
        for region in sg_config['regions']:
            log.info("Working in %s", region)
            remote_sg = get_remote_sg_by_name(
                security_groups_by_region[region], sg_name)
            if not remote_sg:
                if prompt:
                    if raw_input('Create security group %s in %s? (y/N) ' %
                                 (sg_name, region)) != 'y':
                        log.info("Exiting")
                        exit(0)
                log.info("Creating group %s", sg_name)
                remote_sg = conns_by_region[region].create_security_group(
                    sg_name,
                    vpc_id=sg_config['regions'][region],
                    description=sg_config['description'],
                )
                log.info("New group has id %s", remote_sg.id)
                log.info("Waiting for group to propagate")
                time.sleep(5)
                # Fetch it again so we get all the rules
                log.info("Re-loading group %s", sg_name)
                remote_sg = conns_by_region[region].get_all_security_groups(
                    group_ids=[remote_sg.id])[0]

            sync_security_group(remote_sg, sg_config, prompt=prompt)


if __name__ == '__main__':
    main()
