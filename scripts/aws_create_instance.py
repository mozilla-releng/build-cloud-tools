#!/usr/bin/env python
import json
import uuid
import time
import boto
import StringIO
import random
import site
import os
import multiprocessing
import sys
from random import choice
from fabric.api import run, put, env, sudo
from fabric.context_managers import cd
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from boto.ec2.networkinterface import NetworkInterfaceSpecification, \
    NetworkInterfaceCollection

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import AMI_CONFIGS_DIR, get_aws_connection, get_vpc, \
    name_available, wait_for_status
from cloudtools.dns import get_ip, get_ptr
from cloudtools.aws.vpc import get_subnet_id, ip_available

import logging
log = logging.getLogger(__name__)


def verify(hosts, config, region):
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
            if not ip_available(conn, ip):
                log.error("IP %s reserved for %s, but not available", ip, host)
                passed = False
            vpc = get_vpc(region)
            s_id = get_subnet_id(vpc, ip)
            if s_id not in config['subnet_ids']:
                log.error("IP %s does not belong to assigned subnets", ip)
                passed = False
    if not passed:
        raise RuntimeError("Sanity check failed")


def assimilate_windows(instance, config, instance_data):
    # Wait for the instance to stop, and then clear its userData and start it
    # again
    log.info("waiting for instance to shut down")
    wait_for_status(instance, 'state', 'stopped', 'update')

    log.info("clearing userData")
    instance.modify_attribute("userData", None)
    log.info("starting instance")
    instance.start()
    log.info("waiting for instance to start")
    # Wait for the instance to come up
    wait_for_status(instance, 'state', 'running', 'update')


def assimilate(instance, config, instance_data, deploypass):
    """Assimilate hostname into our collective

    What this means is that hostname will be set up with some basic things like
    a script to grab AWS user data, and get it talking to puppet (which is
    specified in said config).
    """
    ip_addr = instance.private_ip_address
    distro = config.get('distro')
    if distro.startswith('win'):
        return assimilate_windows(instance, config, instance_data)

    env.host_string = ip_addr
    env.user = 'root'
    env.abort_on_prompts = True
    env.disable_known_hosts = True

    # Sanity check
    run("date")

    # Set our hostname
    hostname = "{hostname}".format(**instance_data)
    log.info("Bootstrapping %s...", hostname)
    run("hostname %s" % hostname)
    if distro in ('ubuntu', 'debian'):
        run("echo %s > /etc/hostname" % hostname)

    # Resize the file systems
    # We do this because the AMI image usually has a smaller filesystem than
    # the instance has.
    if 'device_map' in config:
        for device, mapping in config['device_map'].items():
            if not mapping.get("skip_resize"):
                run('resize2fs {dev}'.format(dev=mapping['instance_dev']))

    # Set up /etc/hosts to talk to 'puppet'
    hosts = ['127.0.0.1 %s localhost' % hostname,
             '::1 localhost6.localdomain6 localhost6']
    hosts = StringIO.StringIO("\n".join(hosts) + "\n")
    put(hosts, '/etc/hosts')

    if distro in ('ubuntu', 'debian'):
        put('%s/releng-public.list' % AMI_CONFIGS_DIR, '/etc/apt/sources.list')
        run("apt-get update")
        run("apt-get install -y --allow-unauthenticated puppet")
        run("apt-get clean")
    else:
        # Set up yum repos
        run('rm -f /etc/yum.repos.d/*')
        put('%s/releng-public.repo' % AMI_CONFIGS_DIR,
            '/etc/yum.repos.d/releng-public.repo')
        run('yum clean all')
        run('yum install -q -y lvm-init puppet')
        lvm_init_cfg = StringIO.StringIO(json.dumps(config))
        put(lvm_init_cfg, "/etc/lvm-init/lvm-init.json")
        run("/sbin/lvm-init")

    run("wget -O /root/puppetize.sh https://hg.mozilla.org/build/puppet/raw-file/production/modules/puppet/files/puppetize.sh")
    run("chmod 755 /root/puppetize.sh")
    put(StringIO.StringIO(deploypass), "/root/deploypass")
    put(StringIO.StringIO("exit 0\n"), "/root/post-puppetize-hook.sh")

    puppet_master = random.choice(instance_data["puppet_masters"])
    log.info("Puppetizing %s, it may take a while...", hostname)
    run("PUPPET_SERVER=%s /root/puppetize.sh" % puppet_master)

    if 'home_tarball' in instance_data:
        put(instance_data['home_tarball'], '/tmp/home.tar.gz')
        with cd('~cltbld'):
            sudo('tar xzf /tmp/home.tar.gz', user="cltbld")
            sudo('chmod 700 .ssh', user="cltbld")
            sudo('chmod 600 .ssh/*', user="cltbld")
        run('rm -f /tmp/home.tar.gz')

    if "buildslave_password" in instance_data:
        # Set up a stub buildbot.tac
        sudo("/tools/buildbot/bin/buildslave create-slave /builds/slave "
             "{buildbot_master} {name} "
             "{buildslave_password}".format(**instance_data), user="cltbld")
    if instance_data.get("hg_shares"):
        log.info("Cloning HG repos for %s...", hostname)
        hg = "/tools/python27-mercurial/bin/hg"
        for share, bundle in instance_data['hg_shares'].iteritems():
            target_dir = '/builds/hg-shared/%s' % share
            sudo('rm -rf {d} && mkdir -p {d}'.format(d=target_dir),
                 user="cltbld")
            sudo('{hg} init {d}'.format(hg=hg, d=target_dir), user="cltbld")
            hgrc = "[paths]\n"
            hgrc += "default = https://hg.mozilla.org/%s\n" % share
            put(StringIO.StringIO(hgrc), '%s/.hg/hgrc' % target_dir)
            run("chown cltbld: %s/.hg/hgrc" % target_dir)
            sudo('{hg} -R {d} unbundle {b}'.format(hg=hg, d=target_dir,
                                                   b=bundle), user="cltbld")

    log.info("Rebooting %s...", hostname)
    run("reboot")


def create_instance(name, config, region, key_name, instance_data,
                    deploypass, loaned_to, loan_bug):
    """Creates an AMI instance with the given name and config. The config must
    specify things like ami id."""
    conn = get_aws_connection(region)
    vpc = get_vpc(region)
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

    ip_address = get_ip(instance_data['hostname'])
    subnet_id = None

    if ip_address:
        s_id = get_subnet_id(vpc, ip_address)
        if s_id in config['subnet_ids']:
            if ip_available(conn, ip_address):
                subnet_id = s_id
            else:
                log.warning("%s already assigned" % ip_address)

    if not ip_address or not subnet_id:
        ip_address = None
        subnet_id = choice(config.get('subnet_ids'))
    interface = NetworkInterfaceSpecification(
        subnet_id=subnet_id, private_ip_address=ip_address,
        delete_on_termination=True,
        groups=config.get('security_group_ids', []),
        associate_public_ip_address=config.get("use_public_ip")
    )
    interfaces = NetworkInterfaceCollection(interface)

    while True:
        try:
            if 'user_data_file' in config:
                user_data = open(config['user_data_file']).read()
                user_data = user_data.format(
                    puppet_server=instance_data.get('default_puppet_server'),
                    fqdn=instance_data['hostname'],
                    hostname=instance_data['name'],
                    domain=instance_data['domain'],
                    dns_search_domain=config.get('dns_search_domain'),
                    password=deploypass,
                )
            else:
                user_data = None

            reservation = conn.run_instances(
                image_id=config['ami'],
                key_name=key_name,
                instance_type=config['instance_type'],
                block_device_map=bdm,
                client_token=token,
                disable_api_termination=bool(config.get('disable_api_termination')),
                user_data=user_data,
                instance_profile_name=config.get('instance_profile_name'),
                network_interfaces=interfaces,
            )
            break
        except boto.exception.BotoServerError:
            log.exception("Cannot start an instance")
        time.sleep(10)

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
    while True:
        try:
            assimilate(instance, config, instance_data, deploypass)
            break
        except:
            log.warn("problem assimilating %s (%s), retrying in 10 sec ...",
                     instance_data['hostname'], instance.id)
            time.sleep(10)
    instance.add_tag('moz-state', 'ready')


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


def make_instances(names, config, region, key_name, instance_data,
                   deploypass, loaned_to, loan_bug):
    """Create instances for each name of names for the given configuration"""
    procs = []
    for name in names:
        p = LoggingProcess(log="{name}.log".format(name=name),
                           target=create_instance,
                           args=(name, config, region, key_name, instance_data,
                                 deploypass, loaned_to, loan_bug),
                           )
        p.start()
        procs.append(p)

    log.info("waiting for workers")
    for p in procs:
        p.join()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True,
                        type=argparse.FileType('r'),
                        help="instance configuration to use")
    parser.add_argument("-r", "--region", help="region to use",
                        default="us-east-1")
    parser.add_argument("-k", "--secrets", type=argparse.FileType('r'),
                        required=True, help="file where secrets can be found")
    parser.add_argument("-s", "--key-name", help="SSH key name", required=True)
    parser.add_argument("-i", "--instance-data", help="instance specific data",
                        type=argparse.FileType('r'), required=True)
    parser.add_argument("--instance_id", help="assimilate existing instance")
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip DNS related checks")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Increase logging verbosity")
    parser.add_argument("-l", "--loaned-to", help="Loaner contact e-mail")
    parser.add_argument("-b", "--bug", help="Loaner bug number")
    parser.add_argument("hosts", metavar="host", nargs="+",
                        help="hosts to be processed")

    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if args.verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)

    try:
        config = json.load(args.config)[args.region]
    except KeyError:
        parser.error("unknown configuration")

    secrets = json.load(args.secrets)
    deploypass = secrets["deploy_password"]

    instance_data = json.load(args.instance_data)
    if not args.no_verify:
        log.info("Sanity checking DNS entries...")
        verify(args.hosts, config, args.region)
    make_instances(args.hosts, config, args.region, args.key_name,
                   instance_data, deploypass, args.loaned_to, args.bug)
