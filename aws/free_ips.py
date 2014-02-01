from boto.ec2 import connect_to_region
from boto.vpc import VPCConnection
from IPy import IP
import random
import argparse
import json


parser = argparse.ArgumentParser()
parser.add_argument("-c", "--config", required=True,
                    type=argparse.FileType('r'),
                    help="instance configuration to use")
parser.add_argument("-r", "--region", help="region to use",
                    default="us-east-1")
parser.add_argument("-k", "--secrets", type=argparse.FileType('r'),
                    help="optional file where secrets can be found")
parser.add_argument("-n", "--number", type=int, required=True,
                    help="How many IPs you need")
args = parser.parse_args()

try:
    config = json.load(args.config)[args.region]
except KeyError:
    parser.error("unknown configuration")

if args.secrets:
    secrets = json.load(args.secrets)
    conn = connect_to_region(
        args.region,
        aws_access_key_id=secrets['aws_access_key_id'],
        aws_secret_access_key=secrets['aws_secret_access_key']
    )
    vpc = VPCConnection(
        aws_access_key_id=secrets['aws_access_key_id'],
        aws_secret_access_key=secrets['aws_secret_access_key'],
        region=conn.region
    )
else:
    conn = connect_to_region(args.region)
    vpc = VPCConnection(region=conn.region)

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
