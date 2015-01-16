#!/usr/bin/env python

import argparse
import logging
import json
import boto

from collections import defaultdict
from cloudtools.aws import get_aws_connection, DEFAULT_REGIONS

log = logging.getLogger(__name__)
BUCKET = "mozilla-releng-amis"
KEY = "amis.json"
# A list of attributes with optional function to be used to convert them to
# thir JSON representation
AMI_ATTRS = ("architecture", ("block_device_mapping", lambda o: o.keys()),
             "description", "hypervisor", "id", "is_public", "kernel_id",
             "location", "name", "owner_alias", "owner_id", "platform",
             "ramdisk_id", ("region", lambda o: o.name), "root_device_name",
             "root_device_type", "state", "tags", "type",
             "virtualization_type")


def amis_to_dict(images):
    """Convert collection of AMIs into their JSON prepresenation.  Uses
    AMI_ATTRS to get the list of attributes to be converted.  Optionally can
    use a function to conver objects into their JSON compatible representation.
    """
    data = defaultdict(dict)
    for img in images:
        for attr in AMI_ATTRS:
            if isinstance(attr, tuple):
                name, func = attr
                data[img.id][name] = func(getattr(img, name))
            else:
                data[img.id][attr] = getattr(img, attr)
    return json.dumps(data)


def update_ami_status(data):
    """Publish JSON to S3. It can be accessed from the following URL:
       https://s3.amazonaws.com/{BUCKET}/{KEY},
       https://s3.amazonaws.com/mozilla-releng-amis/amis.json in our case"""
    conn = boto.connect_s3()
    bucket = conn.get_bucket(BUCKET)
    key = bucket.get_key(KEY)
    key.set_contents_from_string(data)
    key.set_acl("public-read")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", dest="regions", action="append",
                        help="optional list of regions")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Supress logging messages")

    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.quiet:
        log.setLevel(logging.INFO)
    else:
        log.setLevel(logging.ERROR)

    if not args.regions:
        args.regions = DEFAULT_REGIONS
    images = []
    for region in args.regions:
        conn = get_aws_connection(region)
        images.extend(conn.get_all_images(owners=["self"],
                                          filters={"state": "available"}))
    update_ami_status(amis_to_dict(images))

if __name__ == '__main__':
    main()
