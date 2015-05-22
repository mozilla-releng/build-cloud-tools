#!/usr/bin/env python

import argparse
import json
import uuid
import time
import boto
import os
import multiprocessing
import sys
import logging
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType

from cloudtools.aws import get_aws_connection, get_vpc, \
    name_available, wait_for_status, get_user_data_tmpl, get_region_dns_atom
from cloudtools.dns import get_ip, get_ptr
from cloudtools.aws.instance import assimilate_instance, \
    make_instance_interfaces
from cloudtools.aws.vpc import get_subnet_id, ip_available
from cloudtools.aws.ami import ami_cleanup, volume_to_ami, copy_ami, \
    get_ami

from fabric.network import NetworkError

log = logging.getLogger(__name__)

# this needs to be long enough for the puppetmasters to synchronize the issued
# certificate and its revocation
FAILURE_TIMEOUT = 60 * 20


def verify(hosts, config, region, ignore_subnet_check=False):
    """ Check DNS entries and IP availability for hosts"""
    passed = True
    conn = get_aws_connection(region)
    for host in hosts:
        fqdn = "%s.%s" % (host, config["domain"])
        log.info("Checking name conflicts for %s", host)
        if not name_available(conn, host):
            log.error("%s has been already taken", host)
            passed = False
            continue
        log.debug("Getting IP for %s", fqdn)
        ip = get_ip(fqdn)
        if not ip:
            log.error("%s has no DNS entry", fqdn)
            passed = False
        else:
            log.debug("Getting PTR for %s", fqdn)
            ptr = get_ptr(ip)
            if ptr != fqdn:
                log.error("Bad PTR for %s", host)
                passed = False
            log.debug("Checking %s availablility", ip)
            if not ip_available(region, ip):
                log.error("IP %s reserved for %s, but not available", ip, host)
                passed = False
            if not ignore_subnet_check:
                vpc = get_vpc(region)
                s_id = get_subnet_id(vpc, ip)
                if s_id not in config['subnet_ids']:
                    log.error("IP %s does not belong to assigned subnets", ip)
                    passed = False
    if not passed:
        raise RuntimeError("Sanity check failed")


def create_instance(name, config, region, key_name, ssh_key, instance_data,
                    deploypass, loaned_to, loan_bug, create_ami,
                    ignore_subnet_check, max_attempts):
    """Creates an AMI instance with the given name and config. The config must
    specify things like ami id."""
    conn = get_aws_connection(region)
    # Make sure we don't request the same things twice
    token = str(uuid.uuid4())[:16]

    instance_data = instance_data.copy()
    instance_data['name'] = name
    instance_data['domain'] = config['domain']
    instance_data['hostname'] = '{name}.{domain}'.format(
        name=name, domain=config['domain'])

    ami = conn.get_all_images(image_ids=[config["ami"]])[0]
    bdm = None
    if 'device_map' in config:
        bdm = BlockDeviceMapping()
        for device, device_info in config['device_map'].items():
            bd = BlockDeviceType()
            if device_info.get('size'):
                bd.size = device_info['size']
            # Overwrite root device size for HVM instances, since they cannot
            # be resized online
            if ami.virtualization_type == "hvm" and \
                    ami.root_device_name == device:
                bd.size = ami.block_device_mapping[ami.root_device_name].size
            if device_info.get("delete_on_termination") is not False:
                bd.delete_on_termination = True
            if device_info.get("ephemeral_name"):
                bd.ephemeral_name = device_info["ephemeral_name"]

            bdm[device] = bd

    interfaces = make_instance_interfaces(
        region, instance_data['hostname'], ignore_subnet_check,
        config.get('subnet_ids'), config.get('security_group_ids', []),
        config.get("use_public_ip"))

    keep_going, attempt = True, 1
    while keep_going:
        try:
            if 'user_data_file' in config:
                user_data = open(config['user_data_file']).read()
            else:
                user_data = get_user_data_tmpl(config['type'])
            if user_data:
                user_data = user_data.format(
                    puppet_server=instance_data.get('default_puppet_server'),
                    fqdn=instance_data['hostname'],
                    hostname=instance_data['name'],
                    domain=instance_data['domain'],
                    dns_search_domain=config.get('dns_search_domain'),
                    password=deploypass,
                    moz_instance_type=config['type'],
                    region_dns_atom=get_region_dns_atom(region),
                )

            reservation = conn.run_instances(
                image_id=config['ami'],
                key_name=key_name,
                instance_type=config['instance_type'],
                block_device_map=bdm,
                client_token=token,
                disable_api_termination=config.get('disable_api_termination'),
                user_data=user_data,
                instance_profile_name=config.get('instance_profile_name'),
                network_interfaces=interfaces,
            )
            break
        except boto.exception.BotoServerError:
            log.exception("Cannot start an instance")
        time.sleep(10)
        if max_attempts:
            attempt += 1
            keep_going = max_attempts >= attempt

    instance = reservation.instances[0]
    log.info("instance %s created, waiting to come up", instance)
    # Wait for the instance to come up
    wait_for_status(instance, "state", "running", "update")
    instance.add_tag('Name', name)
    instance.add_tag('FQDN', instance_data['hostname'])
    instance.add_tag('created', time.strftime("%Y-%m-%d %H:%M:%S %Z",
                                              time.gmtime()))
    instance.add_tag('moz-type', config['type'])
    if loaned_to:
        instance.add_tag("moz-loaned-to", loaned_to)
    if loan_bug:
        instance.add_tag("moz-bug", loan_bug)

    log.info("assimilating %s", instance)
    instance.add_tag('moz-state', 'pending')

    keep_going, attempt = True, 1
    while keep_going:
        try:
            # Don't reboot if need to create ami
            reboot = not create_ami
            assimilate_instance(instance=instance, config=config,
                                ssh_key=ssh_key, instance_data=instance_data,
                                deploypass=deploypass, reboot=reboot)
            break
        except NetworkError as e:
            # it takes a while for the machine to start/reboot so the
            # NetworkError exception is quite common, just log the error,
            # without the full stack trace
            log.warn("cannot connect; instance may still be starting  %s (%s, %s) - %s,"
                     "retrying in %d sec ...", instance_data['hostname'], instance.id,
                     instance.private_ip_address, e, FAILURE_TIMEOUT)
            time.sleep(FAILURE_TIMEOUT)

        except:
            # any other exception
            log.warn("problem assimilating %s (%s, %s), retrying in "
                     "%d sec ...", instance_data['hostname'], instance.id,
                     instance.private_ip_address, FAILURE_TIMEOUT, exc_info=True)
            time.sleep(FAILURE_TIMEOUT)
        if max_attempts:
            attempt += 1
            keep_going = max_attempts >= attempt

    instance.add_tag('moz-state', 'ready')
    if create_ami:
        ami_name = "spot-%s-%s" % (
            config['type'], time.strftime("%Y-%m-%d-%H-%M", time.gmtime()))
        log.info("Generating AMI %s", ami_name)
        ami_cleanup(mount_point="/", distro=config["distro"])
        root_bd = instance.block_device_mapping[instance.root_device_name]
        volume = instance.connection.get_all_volumes(
            volume_ids=[root_bd.volume_id])[0]
        # The instance has to be stopped to flush EBS caches
        instance.stop()
        wait_for_status(instance, 'state', 'stopped', 'update')
        ami = volume_to_ami(volume=volume, ami_name=ami_name,
                            arch=instance.architecture,
                            virtualization_type=instance.virtualization_type,
                            kernel_id=instance.kernel,
                            root_device_name=instance.root_device_name,
                            tags=config["tags"])
        log.info("AMI %s (%s) is ready", ami_name, ami.id)
        log.warn("Terminating %s", instance)
        instance.terminate()


class LoggingProcess(multiprocessing.Process):

    def __init__(self, log, *args, **kwargs):
        self.log = log
        super(LoggingProcess, self).__init__(*args, **kwargs)

    def run(self):
        output = open(self.log, 'wb', 0)
        logging.basicConfig(stream=output)
        sys.stdout = output
        sys.stderr = output
        return super(LoggingProcess, self).run()


def make_instances(names, config, region, key_name, ssh_key, instance_data,
                   deploypass, loaned_to, loan_bug, create_ami,
                   ignore_subnet_check, max_attempts):
    """Create instances for each name of names for the given configuration"""
    procs = []
    for name in names:
        p = LoggingProcess(log="{name}.log".format(name=name),
                           target=create_instance,
                           args=(name, config, region, key_name, ssh_key,
                                 instance_data, deploypass, loaned_to,
                                 loan_bug, create_ami, ignore_subnet_check,
                                 max_attempts),
                           )
        p.start()
        procs.append(p)

    log.info("waiting for workers")
    for p in procs:
        p.join()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True,
                        type=argparse.FileType('r'),
                        help="instance configuration to use")
    parser.add_argument("-r", "--region", help="region to use",
                        default="us-east-1")
    parser.add_argument("-k", "--secrets", type=argparse.FileType('r'),
                        required=True, help="file where secrets can be found")
    parser.add_argument("-s", "--key-name", help="SSH key name", required=True)
    parser.add_argument("--ssh-key", required=True,
                        help="SSH key to be used by Fabric")
    parser.add_argument("-i", "--instance-data", help="instance specific data",
                        type=argparse.FileType('r'), required=True)
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip DNS related checks")
    parser.add_argument("-v", "--verbose", action="store_const",
                        dest="log_level", const=logging.DEBUG,
                        default=logging.INFO,
                        help="Increase logging verbosity")
    parser.add_argument("-l", "--loaned-to", help="Loaner contact e-mail")
    parser.add_argument("-b", "--bug", help="Loaner bug number")
    parser.add_argument("hosts", metavar="host", nargs="+",
                        help="hosts to be processed")
    parser.add_argument("--create-ami", action="store_true",
                        help="Generate AMI and terminate the instance")
    parser.add_argument("--ignore-subnet-check", action="store_true",
                        help="Do not check subnet IDs")
    parser.add_argument("-t", "--copy-to-region", action="append", default=[],
                        dest="copy_to_regions", help="Regions to copy AMI to")
    parser.add_argument("--max-attempts",
                        help="The number of attempts to try after each failure"
                        )

    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s",
                        level=args.log_level)

    try:
        config = json.load(args.config)[args.region]
    except KeyError:
        parser.error("unknown configuration")
    if not os.path.exists(args.ssh_key):
        parser.error("Cannot read %s" % args.ssh_key)

    secrets = json.load(args.secrets)
    deploypass = secrets["deploy_password"]

    instance_data = json.load(args.instance_data)
    if not args.no_verify:
        log.info("Sanity checking DNS entries...")
        verify(args.hosts, config, args.region, args.ignore_subnet_check)
    make_instances(names=args.hosts, config=config, region=args.region,
                   key_name=args.key_name, ssh_key=args.ssh_key,
                   instance_data=instance_data, deploypass=deploypass,
                   loaned_to=args.loaned_to, loan_bug=args.bug,
                   create_ami=args.create_ami,
                   ignore_subnet_check=args.ignore_subnet_check,
                   max_attempts=args.max_attempts)
    for r in args.copy_to_regions:
        ami = get_ami(region=args.region, moz_instance_type=config["type"])
        log.info("Copying %s (%s) to %s", ami.id, ami.tags.get("Name"), r)
        new_ami = copy_ami(ami, r)
        log.info("New AMI created. AMI ID: %s", new_ami.id)

if __name__ == '__main__':
    main()
