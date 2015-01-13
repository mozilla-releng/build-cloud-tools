#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import datetime
import sys
import time
import os
import logging
import boto.cloudformation
import boto.s3

from cfn_pyplates.cli import _find_cloudformationtemplate
from cfn_pyplates.cli import _load_pyplate
from cfn_pyplates.options import OptionsMapping

import site
site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))

log = logging.getLogger(__name__)
BUCKET_NAME = 'mozilla-releng-cloudformation-templates-{}'

def main():
    parser = argparse.ArgumentParser(description='deploy a cloudformation template')
    parser.add_argument('template',
            help='cft_pyplates template to deploy')
    parser.add_argument('--region', type=str,
            help='AWS region to deploy to',
            required=True)
    parser.add_argument('--stack', type=str,
            help='CloudFormation stack to create or update',
            required=True)
    parser.add_argument('--create', action='store_true',
            help='Create a new stack, instead of updating')
    parser.add_argument('--noop', action='store_true',
            help='Just parse and output the template, without updating')
    parser.add_argument('--wait', action='store_true',
            help='Wait for the create or update operation to complete')

    args = parser.parse_args()

    template = args.template
    log.debug("converting template %r to JSON", template)
    
    # see https://github.com/seandst/cfn-pyplates/issues/27 for the
    # solution to using these private functions
    sys.path.insert(0, os.path.dirname(template))
    options_mapping = OptionsMapping({})
    pyplate = _load_pyplate(open(template), options_mapping)
    cft = _find_cloudformationtemplate(pyplate)
    if args.noop:
        print unicode(cft)
        return

    if not deploy_template(args, unicode(cft)):
        sys.exit(1)

class EventLoop(object):

    def __init__(self, conn, stackid):
        self.conn = conn
        self.stackid = stackid
        self.seen = set()
        self.next_token = None

    def iterate(self, log_events=True):
        evts = self.conn.describe_stack_events(
                self.stackid, next_token=self.next_token)
        self.next_token = evts.next_token
        for evt in evts:
            if evt.event_id in self.seen:
                continue
            self.seen.add(evt.event_id)
            if log_events:
                msg = "{} - {} {} -> {}".format(
                    evt.timestamp, evt.resource_type, evt.logical_resource_id,
                    evt.resource_status)
                if evt.resource_status_reason:
                    msg += ' ({})'.format(evt.resource_status_reason)
                log.info(msg)


def deploy_template(args, template_body):
    cf = boto.cloudformation.connect_to_region(args.region)
    if args.create:
        stackid = cf.create_stack(stack_name=args.stack,
                                  template_body=template_body)
        event_loop = EventLoop(cf, stackid)
    else:
        # flush all of the pre-existing events before starting the
        # update
        event_loop = EventLoop(cf, args.stack)
        event_loop.iterate(log_events=False)
        stackid = cf.update_stack(stack_name=args.stack,
                                  template_body=template_body)

    while args.wait:
        event_loop.iterate()
        # if the stack is in a "terminal" condition, we're done
        status = cf.describe_stacks(stackid)[0].stack_status
        if not status.endswith('_IN_PROGRESS'):
            log.info("Stack status: %s", status)
            if status not in ('CREATE_COMPLETE', 'UPDATE_COMPLETE'):
                return False
            return True
        time.sleep(2)

def upload_template(args, tpl_json):
    s3 = boto.s3.connect_to_region(args.region)

    bucket_name = BUCKET_NAME.format(args.region)
    location = '' if args.region == 'us-east-1' else args.region
    bucket = s3.lookup(bucket_name)
    if not bucket:
        bucket = s3.create_bucket(bucket_name, location=location)
        bucket.set_acl('private')

    now = datetime.datetime.now().isoformat()
    tpl_base = os.path.basename(args.template)[:-3]
    key_name = '{}/{}.json'.format(tpl_base, now)
    key = bucket.new_key(key_name)

    key.set_contents_from_string(tpl_json)

    region_host = s3.host
    return 'https://{}/{}/{}'.format(region_host, bucket_name, key_name)

if __name__ == '__main__':
    logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.DEBUG)
    logging.getLogger('boto').setLevel(logging.INFO)
    main()
