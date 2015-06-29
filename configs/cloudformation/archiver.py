# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from cfn_pyplates.core import CloudFormationTemplate, Resource
from cfn_pyplates.core import Properties, options
from utils import nametag

cft = CloudFormationTemplate(description="Archiver Infrastructure")

rgn = options['region']

# production

cft.resources.add(Resource(
    'FileBucket', 'AWS::S3::Bucket',
    Properties({
        "AccessControl": "Private",
        "BucketName": "mozilla-releng-%s-archiver" % (rgn,),
        'Tags': [nametag('Archiver Archive Storage - %s' % (rgn,))],
    })
))

# staging

cft.resources.add(Resource(
    'StagingFileBucket', 'AWS::S3::Bucket',
    Properties({
        "AccessControl": "Private",
        "BucketName": "mozilla-releng-staging-%s-archiver" % (rgn,),
        'Tags': [nametag('Archiver Archive Storage - Staging - %s' % (rgn,))],
    })
))
