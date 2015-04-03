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

from cfn_pyplates.core import generate_pyplate
from cfn_pyplates.options import OptionsMapping

log = logging.getLogger(__name__)


class Deployer(object):

    def __init__(self, args):
        self.connections = {}

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

        args = self.args = parser.parse_args(args)

        logging.basicConfig(
            format="%(asctime)s - %(message)s", level=logging.DEBUG)
        logging.getLogger('boto').setLevel(logging.INFO)

        # load the config file
        config = self.config = yaml.load(open(args.config))
        if 'stacks' not in config or args.stack not in config['stacks']:
            parser.error("Stack %r not found in %s" %
                         (args.stack, args.config))

    def run(self):
        if self.args.delete:
            return self.delete_stack(self.args.stack)
        else:
            return self.deploy_stack(self.args.stack)

    def deploy_stack(self, stack_name):
        stack_config = self.config['stacks'][stack_name]
        template_path = os.path.join(
            os.path.dirname(self.args.config),
            stack_config['template'])
        template_body = self.load_template(stack_name, template_path)
        if self.args.noop:
            print template_body
            return

        return self.deploy_template_to_stack(stack_name, template_body)

    def deploy_template_to_stack(self, stack_name, template_body):
        stack_config = self.config['stacks'][stack_name]
        conn = self.conn(stack_config['region'])

        try:
            stack = conn.describe_stacks(stack_name)[0]
            stackid = stack.stack_id
            create = False
        except boto.exception.BotoServerError as e:
            if e.code != 'ValidationError':
                raise
            log.debug("Stack %r does not exist; creating" % stack_name)
            create = True

        if create:
            stackid = conn.create_stack(stack_name=stack_name,
                                        template_body=template_body,
                                        capabilities=['CAPABILITY_IAM'])
            event_loop = EventLoop(conn, stackid)
        else:
            event_loop = EventLoop(conn, stackid)
            event_loop.consume_old_events()
            try:
                stackid = conn.update_stack(stack_name=stack_name,
                                            template_body=template_body,
                                            capabilities=['CAPABILITY_IAM'])
            except boto.exception.BotoServerError as e:
                # consider this particular error to indicate success
                if e.message == 'No updates are to be performed.':
                    log.info("Stack has not changed; treated as success")
                    return True
                raise

        if self.args.wait:
            return event_loop.log_events_until_done()
        else:
            return True

    def delete_stack(self, stack_name):
        stack_config = self.config['stacks'][stack_name]
        conn = self.conn(stack_config['region'])

        try:
            stack = conn.describe_stacks(stack_name)[0]
            stackid = stack.stack_id
        except boto.exception.BotoServerError as e:
            if e.code != 'ValidationError':
                raise
            log.warning("Stack %r does not exist" % stack_name)
            return True

        event_loop = EventLoop(conn, stackid)
        event_loop.consume_old_events()
        conn.delete_stack(stack_name)
        if self.args.wait:
            return event_loop.log_events_until_done()
        else:
            return True

    def load_external_resources(self, options_mapping, stack_name):
        stack_config = self.config['stacks'][stack_name]
        ext = {}
        for opt, ref in stack_config.get('options', {}).iteritems():
            # only translate those options that have both a 'stack' and
            # 'resource'
            if not isinstance(ref, dict) or set(ref.keys()) != {'stack', 'resource'}:
                continue
            ref_stack = self.config['stacks'][ref['stack']]
            conn = self.conn(ref_stack['region'])
            res = conn.describe_stack_resource(ref['stack'], ref['resource'])
            # for some reason boto doesn't handle this response..
            res = res['DescribeStackResourceResponse']
            res = res['DescribeStackResourceResult']
            res = res['StackResourceDetail']
            options_mapping[opt] = res['PhysicalResourceId']
            log.debug("Mapped option %r (stack %r resource %r) to physical id %r",
                      opt, ref['stack'], ref['resource'], options_mapping[opt])
        return ext

    def load_template(self, stack_name, template_path):
        stack_config = self.config['stacks'][stack_name]
        log.debug("converting template %r to JSON", template_path)

        # see https://github.com/seandst/cfn-pyplates/issues/27 for the
        # solution to using these private functions
        sys.path.insert(0, os.path.dirname(template_path))
        options_mapping = OptionsMapping(stack_config.get('options', {}))

        # add external resources to options
        self.load_external_resources(options_mapping, stack_name)

        # make 'options' available for import, so that flake8 can stay
        # happy when parsing the templates
        cfn_pyplates.core.options = options_mapping

        # load the template and convert the result to JSON
        return generate_pyplate(template_path, options_mapping)

    def conn(self, region):
        try:
            return self.connections[region]
        except KeyError:
            conn = boto.cloudformation.connect_to_region(region)
            self.connections[region] = conn
            return conn


class EventLoop(object):

    def __init__(self, conn, stackid):
        self.conn = conn
        self.stackid = stackid
        self.seen_events = set()
        self.next_token = None

    def _iterate(self):
        # iterate until we get an empty set of events or no next_token
        new_evts = []
        while True:
            evts = self.conn.describe_stack_events(
                self.stackid, next_token=self.next_token)
            self.next_token = evts.next_token
            for evt in evts:
                if evt.event_id in self.seen_events:
                    continue
                self.seen_events.add(evt.event_id)
                new_evts.append(evt)
            if not evts or not self.next_token:
                break

        # AWS doesn't give us the events in order, so sort what we have
        return sorted(new_evts, key=lambda e: e.timestamp)

    def consume_old_events(self):
        self._iterate()

    def log_events_until_done(self):
        while True:
            evts = self._iterate()
            for evt in evts:
                msg = "{} - {} {} -> {}".format(
                    evt.timestamp, evt.resource_type, evt.logical_resource_id,
                    evt.resource_status)
                if evt.resource_status_reason:
                    msg += ' ({})'.format(evt.resource_status_reason)
                log.info(msg)

            # check the stack status
            status = self.conn.describe_stacks(self.stackid)[0].stack_status
            if not status.endswith('_IN_PROGRESS'):
                log.info("Stack status: %s", status)
                if status not in ('CREATE_COMPLETE', 'UPDATE_COMPLETE'):
                    return False
                return True

            time.sleep(1)


def main():
    success = Deployer(sys.argv[1:]).run()
    if not success:
        sys.exit(1)

if __name__ == '__main__':
    main()
