# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from cfn_pyplates.core import CloudFormationTemplate, Resource
from cfn_pyplates.core import Properties, options
from utils import nametag
from utils import sgcidr

cft = CloudFormationTemplate(description="IT Resources")

cft.resources.add(Resource(
    'NagiosSG', 'AWS::EC2::SecurityGroup',
    Properties({
        'GroupDescription': 'Nagios Servers',
        'Tags': [nametag('nagios')],
        'VpcId': options['vpcid'],
        'SecurityGroupIngress': [
            sgcidr('10.22.8.128/32', -1, -1),
            sgcidr('10.22.20.0/25', -1, -1),
            sgcidr('10.22.72.136/32', -1, -1),
            sgcidr('10.22.72.155/32', -1, -1),
            sgcidr('10.22.72.158/32', -1, -1),
            sgcidr('10.22.72.159/32', -1, -1),
            sgcidr('10.22.75.5/32', -1, -1),
            sgcidr('10.22.75.6/31', -1, -1),
            sgcidr('10.22.240.0/20', -1, -1),
            sgcidr('10.22.74.22/32', -1, -1),
            sgcidr('10.22.75.30/32', -1, -1),
            sgcidr('10.22.75.36/32', 'tcp', 22),
            sgcidr('10.22.75.136/32', 'udp', 161),
            sgcidr('0.0.0.0/0', 'icmp', -1),
        ],
    }),
))
