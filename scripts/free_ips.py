import os
import site
import random
import argparse
import json
from IPy import IP

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import get_aws_connection, get_vpc


parser = argparse.ArgumentParser()
parser.add_argument("-c", "--config", required=True,
                    type=argparse.FileType('r'),
                    help="instance configuration to use")
parser.add_argument("-r", "--region", help="region to use",
                    default="us-east-1")
parser.add_argument("-n", "--number", type=int, required=True,
                    help="How many IPs you need")
args = parser.parse_args()

try:
    config = json.load(args.config)[args.region]
except KeyError:
    parser.error("unknown configuration")

conn = get_aws_connection(args.region)
vpc = get_vpc(args.region)

interfaces = vpc.get_all_network_interfaces()
used_ips = [i.private_ip_address for i in interfaces]

subnets = vpc.get_all_subnets(subnet_ids=config["subnet_ids"])
blocks = [s.cidr_block for s in subnets]

available_ips = []
for b in blocks:
    # skip first 5 IPs (they are sometimes "reserved") and the last one
    # (broadcast)
    for ip in list(IP(b))[4:-1]:
        if str(ip) not in used_ips:
            available_ips.append(ip)
sample = random.sample(available_ips, args.number)
for ip in sample:
    print ip
