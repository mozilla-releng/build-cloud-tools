#!/usr/bin/env python
"""Usage: aws_create_win_ami.py -c <config> -s <keyname> [-r region] [-k secrets] INSTANCE_NAME

-c, --config <config>    instance configuration to use
-r, --region <region>    region to use [default: us-east-1]
-k, --secrets <secrets>  file for AWS secrets
-s, --key-name <keyname> ssh key name
"""
import random
import json
import uuid
import time
import logging
import boto

from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from boto.ec2.networkinterface import NetworkInterfaceSpecification, \
    NetworkInterfaceCollection
from cloudtools.aws import AMI_CONFIGS_DIR, wait_for_status, get_aws_connection
from docopt import docopt

log = logging.getLogger(__name__)


def create_instance(connection, instance_name, config, key_name):
    bdm = None
    if 'device_map' in config:
        bdm = BlockDeviceMapping()
        for device, device_info in config['device_map'].items():
            bdm[device] = BlockDeviceType(size=device_info['size'],
                                          delete_on_termination=True)

    if 'user_data_file' in config:
        log.debug("reading user_data from '%s'" % config['user_data_file'])
        user_data = open(config['user_data_file']).read()
        # assert that there are no values in need of formatting
        user_data = user_data.format()
    else:
        user_data = None

    subnet_id = random.choice(config.get('subnet_ids'))

    interface = NetworkInterfaceSpecification(
        subnet_id=subnet_id,
        delete_on_termination=True,
        groups=config.get('security_group_ids', []),
        associate_public_ip_address=config.get("use_public_ip")
    )
    interfaces = NetworkInterfaceCollection(interface)

    reservation = connection.run_instances(
        image_id=config['ami'],
        key_name=key_name,
        instance_type=config['instance_type'],
        block_device_map=bdm,
        client_token=str(uuid.uuid4())[:16],
        disable_api_termination=bool(config.get('disable_api_termination')),
        user_data=user_data,
        instance_profile_name=config.get('instance_profile_name'),
        network_interfaces=interfaces,
    )

    instance = reservation.instances[0]
    instance.add_tag('Name', instance_name)

    log.info("instance %s created, waiting to come up", instance)
    # Wait for the instance to come up
    wait_for_status(instance, 'state', 'running', 'update')

    log.info("instance %s is running; waiting for shutdown", instance)
    wait_for_status(instance, 'state', 'stopped', 'update')
    log.info("clearing userData")
    instance.modify_attribute("userData", None)
    return instance


def create_ami(host_instance, config_name, config):
    connection = host_instance.connection
    dated_target_name = "%s-%s" % (
        config_name, time.strftime("%Y-%m-%d-%H-%M", time.gmtime()))

    log.info('Creating AMI')

    ami_id = connection.create_image(host_instance.id, name=dated_target_name,
                                     description='%s EBS AMI' %
                                     dated_target_name,)
    while True:
        try:
            ami = connection.get_image(ami_id)
            ami.add_tag('Name', dated_target_name)
            log.info('AMI created')
            log.info('ID: {id}, name: {name}'.format(id=ami.id, name=ami.name))
            break
        except boto.exception.EC2ResponseError:
            log.info('Wating for AMI')
            time.sleep(10)
    log.info("Waiting for AMI")
    while ami.state != 'available':
        ami.update()
        time.sleep(10)
    return ami


def main():
    args = docopt(__doc__)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

    try:
        config = json.load(
            open("%s/%s.json" % (AMI_CONFIGS_DIR,
                                 args['--config'])))[args['--region']]
    except KeyError:
        log.error("unknown configuration")
        exit(1)

    connection = get_aws_connection(args['--region'])
    host_instance = create_instance(connection, args['INSTANCE_NAME'], config,
                                    args['--key-name'])
    create_ami(host_instance, args['--config'], config)

if __name__ == '__main__':
    main()
