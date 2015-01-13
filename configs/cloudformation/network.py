# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from cfn_pyplates.core import CloudFormationTemplate, Resource, Properties
from cfn_pyplates.functions import ref

cft = CloudFormationTemplate(description="Release Engineering network configuration")

cft.resources.vpc = Resource('RelengVPC', 'AWS::EC2::VPC',
        Properties({
            'CidrBlock': '192.168.1.0/24',
        })
    )
