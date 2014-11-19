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
import logging
from random import choice
from fabric.api import run, put, sudo
from fabric.context_managers import cd
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from boto.ec2.networkinterface import NetworkInterfaceSpecification, \
    NetworkInterfaceCollection

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import AMI_CONFIGS_DIR, get_aws_connection, get_vpc, \
    name_available, wait_for_status, get_user_data_tmpl
from cloudtools.dns import get_ip, get_ptr
from cloudtools.aws.vpc import get_subnet_id, ip_available
from cloudtools.aws.ami import ami_cleanup, volume_to_ami, copy_ami, get_ami
from cloudtools.fabric import setup_fabric_env

log = logging.getLogger(__name__)


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
            if not ip_available(conn, ip):
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


def assimilate(instance, config, ssh_key, instance_data, deploypass,
               reboot=True):
    """Assimilate hostname into our collective

    What this means is that hostname will be set up with some basic things like
    a script to grab AWS user data, and get it talking to puppet (which is
    specified in said config).
    """
    ip_addr = instance.private_ip_address
    distro = config.get('distro', '')
    if distro.startswith('win'):
        return assimilate_windows(instance, config, instance_data)

    setup_fabric_env(host_string=ip_addr, key_filename=ssh_key)

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
        run("apt-get install -y --allow-unauthenticated puppet cloud-init")
        run("apt-get clean")
    else:
        # Set up yum repos
        run('rm -f /etc/yum.repos.d/*')
        put('%s/releng-public.repo' % AMI_CONFIGS_DIR,
            '/etc/yum.repos.d/releng-public.repo')
        run('yum clean all')
        run('yum install -q -y puppet cloud-init')

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
    if instance_data.get("hg_bundles"):
        unbundle_hg(instance_data['hg_bundles'])
    if instance_data.get("s3_tarballs"):
        unpack_tarballs(instance_data["s3_tarballs"])
    if instance_data.get("hg_repos"):
        share_repos(instance_data["hg_repos"])

    run("sync")
    run("sync")
    if reboot:
        log.info("Rebooting %s...", hostname)
        run("reboot")


def unbundle_hg(hg_bundles):
    log.info("Cloning HG bundles")
    hg = "/tools/python27-mercurial/bin/hg"
    for share, bundle in hg_bundles.iteritems():
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
    log.info("Unbundling HG repos finished")


def unpack_tarballs(tarballs):
    log.info("Unpacking tarballs")
    put("%s/s3-get" % AMI_CONFIGS_DIR, "/tmp/s3-get")
    for dest_dir, info in tarballs.iteritems():
        bucket, key = info["bucket"], info["key"]
        sudo("mkdir -p {d}".format(d=dest_dir), user="cltbld")
        with cd(dest_dir):
            sudo("python /tmp/s3-get -b {bucket} -k {key} -o - | tar xf -".format(
                 bucket=bucket, key=key), user="cltbld")
    run("rm -f /tmp/s3-get")
    log.info("Unpacking tarballs finished")


def share_repos(hg_repos):
    log.info("Cloning HG repos")
    hg = "/tools/python27-mercurial/bin/hg"
    for share, repo in hg_repos.iteritems():
        target_dir = '/builds/hg-shared/%s' % share
        parent_dir = os.path.dirname(target_dir.rstrip("/"))
        sudo('rm -rf {d} && mkdir -p {p}'.format(d=target_dir, p=parent_dir),
             user="cltbld")
        sudo('{hg} clone -U {repo} {d}'.format(hg=hg, repo=repo, d=target_dir),
             user="cltbld")
    log.info("Cloning HG repos finished")


def create_instance(name, config, region, key_name, ssh_key, instance_data,
                    deploypass, loaned_to, loan_bug, create_ami,
                    ignore_subnet_check, max_attempts):
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
        if ignore_subnet_check:
            subnet_id = s_id
        elif s_id in config['subnet_ids']:
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
                )

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
            assimilate(instance=instance, config=config, ssh_key=ssh_key,
                       instance_data=instance_data, deploypass=deploypass,
                       reboot=reboot)
            break
        except:
            log.warn("problem assimilating %s (%s, %s), retrying in "
                     "10 sec ...", instance_data['hostname'], instance.id,
                     instance.private_ip_address, exc_info=True)
            time.sleep(10)
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
    parser.add_argument("--ssh-key", required=True,
                        help="SSH key to be used by Fabric")
    parser.add_argument("-i", "--instance-data", help="instance specific data",
                        type=argparse.FileType('r'), required=True)
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip DNS related checks")
    parser.add_argument("-v", "--verbose", action="store_true",
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
                        help="The number of attempts to try after each failure")
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
        ami = get_ami(region=args.region,
                      moz_instance_type=config["type"])
        log.info("Copying %s (%s) to %s", ami.id, ami.tags.get("Name"), r)
        new_ami = copy_ami(ami, r)
        log.info("New AMI created. AMI ID: %s", new_ami.id)
