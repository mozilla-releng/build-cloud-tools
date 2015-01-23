# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import dns.resolver
import itertools
import re
from IPy import IP
from cfn_pyplates.core import CloudFormationTemplate, Resource
from cfn_pyplates.core import Properties, options, DependsOn
from cfn_pyplates.functions import ref
from utils import nametag

# Parameters

region_prefixes = {
    'usw1': '10.130',
}

# Fn::GetAZs is great, but there's no Fn::Len or modulus operation.
# So we just hard-code it here.
availability_zones = {
    'usw1': ['us-west-1a', 'us-west-1b'],
}

# Subnets that belong to Amazon.  We get much better performance if these are
# routed via the internet gateway.  `whois` is useful for checking netblock
# sizes when you spot a new IP range.

amazon_cidrs = [
    "50.16.0.0/14",
    "54.230.0.0/15",
    "54.239.0.0/17",
    "54.240.0.0/12",
    "72.21.192.0/19",
    "176.32.96.0/21",
    "178.236.0.0/21",
    "205.251.192.0/18",
    "207.171.160.0/19",
]

# all A records corresponding to these hosts should be
# routed via the internet gateway, saving bandwidth
igw_routed_hosts = [
    'ftp-ssl.mozilla.org',
    'hg.mozilla.org',
    'git.mozilla.org',
    'carbon.hostedgraphite.com',
    'mozilla.carbon.hostedgraphite.com',
]

# Utility Functions


def subnet_cidr(suffix, length):
    prefix = region_prefixes[options['region']]
    return '{}.{}/{}'.format(prefix, suffix, length)


def subnet_az(index):
    azs = availability_zones[options['region']]
    return azs[index % len(azs)]


def resolve_host(hostname):
    ips = dns.resolver.query(hostname, "A")
    # sort these so that we deterministically set up the same route
    # resources (until DNS changes)
    ips = sorted([i.to_text() for i in ips])
    return ips

# VPC

cft = CloudFormationTemplate(description="Release Engineering network configuration")

cft.resources.add(Resource(
    'RelengVPC', 'AWS::EC2::VPC',
    Properties({
        'CidrBlock': subnet_cidr('0.0', 16),
        'Tags': [nametag('Releng Network')],
    })
))

# DHCP options

cft.resources.add(Resource(
    'DHCPOptions', 'AWS::EC2::DHCPOptions',
    Properties({
        # point to the onsite, IT-managed DNS servers
        'DomainNameServers': [
            "10.26.75.40",
            "10.26.75.41"
        ],
        'Tags': [nametag('Releng Network Options')],
    })
))

cft.resources.add(Resource(
    'DHCPOptionsAssociation', 'AWS::EC2::VPCDHCPOptionsAssociation',
    Properties({
        'VpcId': ref('RelengVPC'),
        'DhcpOptionsId': ref('DHCPOptions'),
    })
))

# Internet Gateway

cft.resources.add(Resource(
    'IGW', 'AWS::EC2::InternetGateway',
    Properties({
        'Tags': [nametag('IGW for Releng VPC')],
    })
))

cft.resources.add(Resource(
    'IGWAttachment', 'AWS::EC2::VPCGatewayAttachment',
    Properties({
        'VpcId': ref('RelengVPC'),
        'InternetGatewayId': ref('IGW'),
    })
))

# Customer Gateway (tunnel to scl3)

cft.resources.add(Resource(
    'Scl3CustomerGateway', 'AWS::EC2::CustomerGateway',
    Properties({
        'Type': 'ipsec.1',
        'IpAddress': '63.245.214.82',
        'BgpAsn': '65026',
    })
))

cft.resources.add(Resource(
    'Scl3VPNGateway', 'AWS::EC2::VPNGateway',
    Properties({
        'Type': 'ipsec.1',
    })
))

cft.resources.add(Resource(
    'Scl3VPNConnection', 'AWS::EC2::VPNConnection',
    Properties({
        'Type': 'ipsec.1',
        'VpnGatewayId': ref('Scl3VPNGateway'),
        'CustomerGatewayId': ref('Scl3CustomerGateway'),
    })
))

cft.resources.add(Resource(
    'Scl3VPCGatewayAttachment', 'AWS::EC2::VPCGatewayAttachment',
    Properties({
        'VpnGatewayId': ref('Scl3VPNGateway'),
        'VpcId': ref('RelengVPC'),
    })
))


# Subnets

# `ip_space` is a list of (suffix, length) tuples.  suffix octet is appended to
# the region prefix, so for example ('72.0', 23) in usw1 would generate
# 10.130.72.0/23.  `split_to_length` says that multiple subnets should be
# created distributed over the available AZ's, each with that subnet length.

subnets = [
    {
        'name': 'srv',
        'ip_space': [('48.0', 22)],
        'split_to_length': 24,
    },
    {
        'name': 'build',
        'ip_space': [('52.0', 22)],
        'split_to_length': 24,
    },
    {
        'name': 'test',
        'ip_space': [('56.0', 22), (156, 22)],
        'split_to_length': 24,
    },
    {
        'name': 'try',
        'ip_space': [('64.0', 22)],
        'split_to_length': 24,
    },
    {
        'name': 'bb',
        'ip_space': [('68.0', 24)],
        'split_to_length': 26,  # only a /24, so split to /26
    },
    {
        'name': 'private',
        'ip_space': [('75.0', 24)],
        'split_to_length': 24,  # no splitting (it's not a cloudy subnet)
    },
]

for subnet in subnets:
    # split down to the right length
    ip_prefix = region_prefixes[options['region']]
    split_to_length = subnet['split_to_length']
    # figure out the IP count of a subnet of the given size
    split_to_increment = 2 ** (32 - split_to_length)
    azs = iter(itertools.cycle(availability_zones[options['region']]))
    counter = iter(itertools.count(1))
    for ip_suffix, length in subnet['ip_space']:
        ip_space = IP(subnet_cidr(ip_suffix, length))
        subnet_space = IP(subnet_cidr(ip_suffix, split_to_length))
        while subnet_space in ip_space:
            subnet_name = 'Subnet{}{}'.format(subnet['name'].title(),
                                              counter.next())
            cft.resources.add(Resource(
                subnet_name, 'AWS::EC2::Subnet',
                Properties({
                    'AvailabilityZone': azs.next(),
                    'CidrBlock': str(subnet_space),
                    'VpcId': ref('RelengVPC'),
                    'Tags': [nametag(subnet['name'])],
                })
            ))

            cft.resources.add(Resource(
                subnet_name + 'RouteTableAssoc',
                'AWS::EC2::SubnetRouteTableAssociation',
                Properties({
                    'SubnetId': ref(subnet_name),
                    'RouteTableId': ref('VpcRouteTable'),
                })
            ))

            # move to the next subnet space
            subnet_space = IP('{}/{}'.format(
                subnet_space.int() + split_to_increment,
                split_to_length))

# Route Table

cft.resources.add(Resource(
    'VpcRouteTable', 'AWS::EC2::RouteTable',
    Properties({
        'VpcId': ref('RelengVPC'),
        'Tags': [nametag('Releng VPC Route Table')],
    })
))

cft.resources.add(Resource(
    'VPCToScl3', 'AWS::EC2::Route',
    Properties({
        'DestinationCidrBlock': '0.0.0.0/0',
        'GatewayId': ref('Scl3VPNGateway'),
        'RouteTableId': ref('VpcRouteTable'),
    }),
    DependsOn(['Scl3VPNConnection', 'Scl3VPCGatewayAttachment']),
))

for n, cidr in enumerate(amazon_cidrs, 1):
    cft.resources.add(Resource(
        'VPCToAWS{}'.format(n), 'AWS::EC2::Route',
        Properties({
            'DestinationCidrBlock': cidr,
            'GatewayId': ref('IGW'),
            'RouteTableId': ref('VpcRouteTable'),
        }),
        DependsOn(['IGW', 'IGWAttachment']),
    ))

cft.resources.add(Resource(
    'VPCToGitHub', 'AWS::EC2::Route',
    Properties({
        # GitHub's subnet, per
        # https://help.github.com/articles/what-ip-addresses-does-github-use-that-i-should-whitelist/
        'DestinationCidrBlock': '192.30.252.0/22',
        'GatewayId': ref('IGW'),
        'RouteTableId': ref('VpcRouteTable'),
    }),
    DependsOn('IGW'),
))

for hostname in igw_routed_hosts:
    camelcaps = ''.join(a.title() for a in re.split('[^a-z0-9]', hostname))
    for ip in resolve_host(hostname):
        ip_digits = ip.replace('.', '')
        # build a resource name out of the hostname and IP.  It's ugly, but
        # fairly unique.
        cft.resources.add(Resource(
            camelcaps + ip_digits, 'AWS::EC2::Route',
            Properties({
                'DestinationCidrBlock': '{}/32'.format(ip),
                'GatewayId': ref('IGW'),
                'RouteTableId': ref('VpcRouteTable'),
            }),
            DependsOn('IGW'),
        ))
