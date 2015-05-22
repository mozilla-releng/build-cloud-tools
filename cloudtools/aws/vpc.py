import logging
from collections import namedtuple
from IPy import IP
from repoze.lru import lru_cache
from . import get_vpc, get_aws_connection
from .spot import get_active_spot_requests

log = logging.getLogger(__name__)


def get_subnet_id(vpc, ip):
    subnets = vpc.get_all_subnets()
    for s in subnets:
        if IP(ip) in IP(s.cidr_block):
            return s.id
    return None


def ip_available(region, ip):
    conn = get_aws_connection(region)
    instances = conn.get_only_instances()
    ips = [i.private_ip_address for i in instances]
    interfaces = conn.get_all_network_interfaces()
    ips.extend(i.private_ip_address for i in interfaces)
    if ip in ips:
        return False
    else:
        return True


@lru_cache(100)
def get_all_subnets(region, subnet_ids):
    vpc = get_vpc(region)
    return vpc.get_all_subnets(subnet_ids=subnet_ids)


def get_avail_subnet(region, subnet_ids, availability_zone):
    # Minimum IPs in a subnet to qualify it as usable
    min_ips = 2
    subnets = [s for s in get_all_subnets(region, tuple(subnet_ids))
               if s.available_ip_address_count > min_ips and
               s.availability_zone == availability_zone]
    pending_spot_req = [sr for sr in get_active_spot_requests(region) if
                        sr.state == 'open']
    usable_subnets = []
    UsableSubnet = namedtuple("UsableSubnet", ["subnet", "usable_ips"])
    for s in subnets:
        # Subtract pending requests from available IP count
        pending_req = [sr for sr in pending_spot_req if
                       sr.launch_specification.subnet_id == s.id]
        usable_ips = s.available_ip_address_count - len(pending_req)
        if usable_ips > min_ips:
            usable_subnets.append(UsableSubnet(s, usable_ips))

    if not usable_subnets:
        log.debug("No free IP available in %s for subnets %s",
                  availability_zone, subnet_ids)
        return None
    # sort by usable IP address count
    usable_subnets.sort(key=lambda x: x.usable_ips, reverse=True)
    return usable_subnets[0].subnet.id
