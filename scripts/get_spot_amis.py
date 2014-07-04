#!/usr/bin/env python
"""
Lists AMIs used by spot instances
"""

import site
import os

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import DEFAULT_REGIONS

from cloudtools.aws.ami import get_ami

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", action="append", dest="regions")
    parser.add_argument("-t", "--type", action="append",
                        dest="moz_instance_types")

    args = parser.parse_args()
    regions = args.regions
    moz_instance_types = args.moz_instance_types
    if not args.regions:
        regions = DEFAULT_REGIONS
    if not moz_instance_types:
        moz_instance_types = ["bld-linux64", "try-linux64", "tst-linux64",
                              "tst-linux32", "tst-emulator64"]

    for region in regions:
        for moz_instance_type in moz_instance_types:
            ami = get_ami(region=region, moz_instance_type=moz_instance_type)
            print "%s, %s: %s (%s)" % (moz_instance_type, region, ami.id,
                                       ami.tags.get("Name"))
