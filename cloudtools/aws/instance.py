import os
import uuid
import logging
import time
import random
import StringIO
import redo
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from boto.ec2.networkinterface import NetworkInterfaceSpecification, \
    NetworkInterfaceCollection
from fabric.api import run, sudo, put
from fabric.context_managers import cd
from ..fabric import setup_fabric_env
from ..dns import get_ip
from . import wait_for_status, AMI_CONFIGS_DIR, get_aws_connection, \
    get_user_data_tmpl, get_region_dns_atom
from .vpc import get_subnet_id, ip_available, get_vpc
from boto.exception import BotoServerError, EC2ResponseError

log = logging.getLogger(__name__)


def run_instance(region, hostname, config, key_name, user='root',
                 key_filename=None, dns_required=False):
    conn = get_aws_connection(region)
    bdm = None
    if 'device_map' in config:
        bdm = BlockDeviceMapping()
        for device, device_info in config['device_map'].items():
            bdm[device] = BlockDeviceType(size=device_info['size'],
                                          delete_on_termination=True)
    interfaces = None
    if dns_required:
        interfaces = make_instance_interfaces(
            region=region, hostname=hostname, ignore_subnet_check=True,
            avail_subnets=None, security_groups=[], use_public_ip=True)

    reservation = conn.run_instances(
        image_id=config['ami'],
        key_name=key_name,
        instance_type=config['instance_type'],
        block_device_map=bdm,
        client_token=str(uuid.uuid4())[:16],
        network_interfaces=interfaces,
    )

    instance = reservation.instances[0]
    log.info("instance %s created, waiting to come up", instance)
    # Wait for the instance to come up
    wait_for_status(instance, "state", "running", "update")
    setup_fabric_env(instance=instance, user=user, abort_on_prompts=True,
                     disable_known_hosts=True, key_filename=key_filename)

    # wait until the instance is responsive
    while True:
        try:
            if run('date').succeeded:
                break
        except:
            log.debug('hit error waiting for instance to come up')
        time.sleep(10)

    instance.add_tag('Name', hostname.split(".")[0])
    instance.add_tag('FQDN', hostname)
    # Overwrite root's limited authorized_keys
    if user != 'root':
        sudo("cp -f ~%s/.ssh/authorized_keys "
             "/root/.ssh/authorized_keys" % user)
        sudo("sed -i -e '/PermitRootLogin/d' "
             "-e '$ a PermitRootLogin without-password' /etc/ssh/sshd_config")
        sudo("service sshd restart || service ssh restart")
        sudo("sleep 10")
    return instance


_puppet_master_cache = {}


def pick_puppet_master(masters):
    """Pick a puppet master randomly, but in a stable fashion.  Given a choice
    from the same set of masters on a subsequent call, this will return the
    same master.  This helps to ensure that repeated puppetizations hit the
    same master every time, preventing crossed wires due to delayed
    synchronziation between masters."""
    if masters != _puppet_master_cache.get('masters'):
        _puppet_master_cache['masters'] = masters[:]
        _puppet_master_cache['selected'] = random.choice(masters)
    return _puppet_master_cache['selected']


def assimilate_instance(instance, config, ssh_key, instance_data, deploypass,
                        chroot="", reboot=True):
    """Assimilate hostname into our collective

    What this means is that hostname will be set up with some basic things like
    a script to grab AWS user data, and get it talking to puppet (which is
    specified in said config).
    """

    def run_chroot(cmd, *args, **kwargs):
        if chroot:
            run("chroot {} {}".format(chroot, cmd), *args, **kwargs)
        else:
            run(cmd, *args, **kwargs)

    distro = config.get('distro', '')
    if distro.startswith('win'):
        return assimilate_windows(instance, config, instance_data)

    setup_fabric_env(instance=instance, key_filename=ssh_key)

    # Sanity check
    run("date")

    # Set our hostname
    hostname = "{hostname}".format(**instance_data)
    log.info("Bootstrapping %s...", hostname)
    run_chroot("hostname %s" % hostname)
    if distro in ('ubuntu', 'debian'):
        run("echo {hostname} > {chroot}/etc/hostname".format(hostname=hostname,
                                                             chroot=chroot))

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
    put(hosts, "{}/etc/hosts".format(chroot))

    if distro in ('ubuntu', 'debian'):
        put('%s/releng-public.list' % AMI_CONFIGS_DIR,
            '{}/etc/apt/sources.list'.format(chroot))
        run_chroot("apt-get update")
        run_chroot("apt-get install -y --allow-unauthenticated "
                   "puppet cloud-init wget")
        run_chroot("apt-get clean")
    else:
        # Set up yum repos
        run('rm -f {}/etc/yum.repos.d/*'.format(chroot))
        put('%s/releng-public.repo' % AMI_CONFIGS_DIR,
            '{}/etc/yum.repos.d/releng-public.repo'.format(chroot))
        run_chroot('yum clean all')
        run_chroot('yum install -q -y puppet cloud-init wget')

    run_chroot("wget -O /root/puppetize.sh "
               "https://hg.mozilla.org/build/puppet/"
               "raw-file/production/modules/puppet/files/puppetize.sh")
    run_chroot("chmod 755 /root/puppetize.sh")
    put(StringIO.StringIO(deploypass), "{}/root/deploypass".format(chroot))
    put(StringIO.StringIO("exit 0\n"),
        "{}/root/post-puppetize-hook.sh".format(chroot))

    puppet_master = pick_puppet_master(instance_data["puppet_masters"])
    log.info("Puppetizing %s against %s; this may take a while...", hostname, puppet_master)
    run_chroot("env PUPPET_SERVER=%s /root/puppetize.sh" % puppet_master)

    if "buildslave_password" in instance_data:
        # Set up a stub buildbot.tac
        run_chroot("sudo -u cltbld /tools/buildbot/bin/buildslave create-slave "
                   "/builds/slave {buildbot_master} {name} "
                   "{buildslave_password}".format(**instance_data))
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


@redo.retriable(sleeptime=0, jitter=0, attempts=3)
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


@redo.retriable(sleeptime=0, jitter=0, attempts=3)
def unpack_tarballs(tarballs):
    log.info("Unpacking tarballs")
    put("%s/s3-get" % AMI_CONFIGS_DIR, "/tmp/s3-get")
    for dest_dir, info in tarballs.iteritems():
        bucket, key = info["bucket"], info["key"]
        sudo("mkdir -p {d}".format(d=dest_dir), user="cltbld")
        with cd(dest_dir):
            sudo("python /tmp/s3-get -b {bucket} -k {key} -o - | "
                 "tar xf - --touch".format(bucket=bucket, key=key),
                 user="cltbld")
    run("rm -f /tmp/s3-get")
    log.info("Unpacking tarballs finished")


@redo.retriable(sleeptime=0, jitter=0, attempts=3)
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


def make_instance_interfaces(region, hostname, ignore_subnet_check,
                             avail_subnets, security_groups, use_public_ip):
    vpc = get_vpc(region)
    ip_address = get_ip(hostname)
    subnet_id = None

    if ip_address:
        log.info("Using IP %s", ip_address)
        s_id = get_subnet_id(vpc, ip_address)
        log.info("subnet %s", s_id)
        if ignore_subnet_check:
            log.info("ignore_subnet_check, usning %s", s_id)
            subnet_id = s_id
        elif s_id in avail_subnets:
            if ip_available(region, ip_address):
                subnet_id = s_id
            else:
                log.warning("%s already assigned" % ip_address)

    if not ip_address or not subnet_id:
        ip_address = None
        log.info("Picking random IP")
        subnet_id = random.choice(avail_subnets)
    interface = NetworkInterfaceSpecification(
        subnet_id=subnet_id, private_ip_address=ip_address,
        delete_on_termination=True,
        groups=security_groups,
        associate_public_ip_address=use_public_ip
    )
    return NetworkInterfaceCollection(interface)


def create_block_device_mapping(ami, device_map):
    bdm = BlockDeviceMapping()
    for device, device_info in device_map.items():
        if ami.root_device_type == "instance-store" and \
                not device_info.get("ephemeral_name"):
            # EBS is not supported by S3-backed AMIs at request time
            # EBS volumes can be attached when an instance is running
            continue
        bd = BlockDeviceType()
        if device_info.get('size'):
            bd.size = device_info['size']
        if ami.root_device_name == device:
            ami_size = ami.block_device_mapping[device].size
            if ami.virtualization_type == "hvm":
                # Overwrite root device size for HVM instances, since they
                # cannot be resized online
                bd.size = ami_size
            elif device_info.get('size'):
                # make sure that size is enough for this AMI
                assert ami_size <= device_info['size'], \
                    "Instance root device size cannot be smaller than AMI " \
                    "root device"
        if device_info.get("delete_on_termination") is not False:
            bd.delete_on_termination = True
        if device_info.get("ephemeral_name"):
            bd.ephemeral_name = device_info["ephemeral_name"]
        if device_info.get("volume_type"):
            bd.volume_type = device_info["volume_type"]

        bdm[device] = bd
    return bdm


def user_data_from_template(moz_instance_type, fqdn, region):
    user_data = get_user_data_tmpl(moz_instance_type)
    if user_data:
        user_data = user_data.format(
            fqdn=fqdn,
            region_dns_atom=get_region_dns_atom(region),
            moz_instance_type=moz_instance_type)

    return user_data


def tag_ondemand_instance(instance, name, fqdn, moz_instance_type):
    tags = {"Name": name, "FQDN": fqdn, "moz-type": moz_instance_type,
            "moz-state": "ready"}
    # Sleep for a little bit to prevent us hitting
    # InvalidInstanceID.NotFound right away
    time.sleep(0.5)
    max_tries = 10
    sleep_time = 5
    for i in range(max_tries):
        try:
            for tag, value in tags.iteritems():
                instance.add_tag(tag, value)
            return instance
        except EC2ResponseError, e:
            if e.code == "InvalidInstanceID.NotFound":
                if i < max_tries - 1:
                    # Try again
                    log.debug("waiting for instance")
                    time.sleep(sleep_time)
                    sleep_time = min(30, sleep_time * 1.5)
                    continue
        except BotoServerError, e:
            if e.code == "RequestLimitExceeded":
                if i < max_tries - 1:
                    # Try again
                    log.debug("request limit exceeded; sleeping and "
                              "trying again")
                    time.sleep(sleep_time)
                    sleep_time = min(30, sleep_time * 1.5)
                    continue
            raise
