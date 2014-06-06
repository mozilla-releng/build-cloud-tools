import logging
from IPy import IP
from . import get_vpc

log = logging.getLogger(__name__)


def get_subnet_id(vpc, ip):
    subnets = vpc.get_all_subnets()
    for s in subnets:
        if IP(ip) in IP(s.cidr_block):
            return s.id
    return None


def ip_available(conn, ip):
    res = conn.get_all_instances()
    instances = reduce(lambda a, b: a + b, [r.instances for r in res])
    ips = [i.private_ip_address for i in instances]
    interfaces = conn.get_all_network_interfaces()
    ips.extend(i.private_ip_address for i in interfaces)
    if ip in ips:
        return False
    else:
        return True


def get_avail_subnet(region, subnet_ids, availability_zone):
    vpc = get_vpc(region)
    subnets = vpc.get_all_subnets(subnet_ids=subnet_ids)
    subnets = [s for s in subnets if s.available_ip_address_count > 0 and
               s.availability_zone == availability_zone]
    subnets.sort(key=lambda s: s.available_ip_address_count)
    if not subnets:
        log.debug("No free IP available in %s for subnets %s",
                  availability_zone, subnet_ids)
        return None
    return subnets[-1].id
