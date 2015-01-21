#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import boto.cloudformation
import boto.exception
import boto.s3
import cfn_pyplates.core
import sys
import time
import os
import logging
import yaml

from cfn_pyplates.cli import _find_cloudformationtemplate
from cfn_pyplates.cli import _load_pyplate
from cfn_pyplates.options import OptionsMapping

log = logging.getLogger(__name__)


def main():
    success = deploy(sys.argv[1:])
    if not success:
        sys.exit(1)


def deploy(args):
    stacks_yml = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "../../configs/cloudformation/stacks.yml"))
    parser = argparse.ArgumentParser(
        description='deploy a cloudformation stack')
    parser.add_argument('stack', type=str,
                        help='CloudFormation stack to create or update')
    parser.add_argument('--config', type=str,
                        help='Path to stacks.yml (default is relative to this script)',
                        default=stacks_yml)
    parser.add_argument('--delete', action='store_true',
                        help='Delete the stack')
    parser.add_argument('--noop', action='store_true',
                        help='Just parse and output the template, without updating')
    parser.add_argument('--wait', action='store_true',
                        help='Wait for the create or update operation to complete')

    args = parser.parse_args(args)

    logging.basicConfig(
        format="%(asctime)s - %(message)s", level=logging.DEBUG)
    logging.getLogger('boto').setLevel(logging.INFO)

    # load the config file
    config = yaml.load(open(args.config))
    if 'stacks' not in config or args.stack not in config['stacks']:
        parser.error("Stack %r not found in %s" % (args.stack, args.config))
    stack_config = config['stacks'][args.stack]

    if args.delete:
        return delete_stack(args, stack_config, args.stack)
    else:
        return deploy_stack(args, stack_config, args.stack)


def deploy_stack(args, stack_config, stack_name):
    template_path = os.path.join(os.path.dirname(args.config),
                                 stack_config['template'])
    template_body = load_template(args, stack_config, template_path)
    if args.noop:
        print template_body
        return

    return deploy_template(args, stack_config, template_body)


def load_template(args, stack_config, template_path):
    log.debug("converting template %r to JSON", template_path)
    # see https://github.com/seandst/cfn-pyplates/issues/27 for the
    # solution to using these private functions
    sys.path.insert(0, os.path.dirname(template_path))
    options_mapping = OptionsMapping(stack_config.get('options', {}))
    # make 'options' available for import, so that flake8 can stay
    # happy when parsing the templates
    cfn_pyplates.core.options = options_mapping
    # load the template and convert the result to JSON
    pyplate = _load_pyplate(open(template_path), options_mapping)
    cft = _find_cloudformationtemplate(pyplate)
    return unicode(cft)


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
        # iterate until we get an empty set of events
        while True:
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
            else:
                break


def delete_stack(args, stack_config, stack_name):
    region = stack_config['region']
    cf = boto.cloudformation.connect_to_region(region)

    try:
        stack = cf.describe_stacks(args.stack)[0]
        stackid = stack.stack_id
    except boto.exception.BotoServerError as e:
        if e.code != 'ValidationError':
            raise
        log.warning("Stack %r does not exist" % args.stack)
        return True

    event_loop = EventLoop(cf, stackid)
    # flush events before the delete
    event_loop.iterate(log_events=False)
    cf.delete_stack(stack_name)

    return poll_stack(args, cf, event_loop, stackid)


def deploy_template(args, stack_config, template_body):
    region = stack_config['region']
    cf = boto.cloudformation.connect_to_region(region)

    try:
        stack = cf.describe_stacks(args.stack)[0]
        stackid = stack.stack_id
        create = False
    except boto.exception.BotoServerError as e:
        if e.code != 'ValidationError':
            raise
        log.debug("Stack %r does not exist; creating" % args.stack)
        create = True

    if create:
        stackid = cf.create_stack(stack_name=args.stack,
                                  template_body=template_body)
        event_loop = EventLoop(cf, stackid)
    else:
        # flush all of the pre-existing events before starting the
        # update
        event_loop = EventLoop(cf, stackid)
        event_loop.iterate(log_events=False)

        try:
            stackid = cf.update_stack(stack_name=args.stack,
                                      template_body=template_body)
        except boto.exception.BotoServerError as e:
            # consider this particular error to indicate success
            if e.message == 'No updates are to be performed.':
                log.info("Stack has not changed; treated as success")
                return True
            raise

    return poll_stack(args, cf, event_loop, stackid)


def poll_stack(args, cf, event_loop, stackid):
    if not args.wait:
        return True
    while True:
        event_loop.iterate()
        # if the stack is in a "terminal" condition, we're done
        status = cf.describe_stacks(stackid)[0].stack_status
        if not status.endswith('_IN_PROGRESS'):
            log.info("Stack status: %s", status)
            if status not in ('CREATE_COMPLETE', 'UPDATE_COMPLETE'):
                return False
            return True
        time.sleep(2)

if __name__ == '__main__':
    main()
