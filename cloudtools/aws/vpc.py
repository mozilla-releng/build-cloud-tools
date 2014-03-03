from IPy import IP


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
