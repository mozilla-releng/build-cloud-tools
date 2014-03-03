#!/usr/bin/env python

from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from fabric.api import run, put, env, lcd
import json
import time
import logging
import os
import site

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import get_aws_connection, AMI_CONFIGS_DIR, wait_for_status
from cloudtools.aws.instance import run_instance

log = logging.getLogger()


def manage_service(service, target, state, distro="centos"):
    assert state in ("on", "off")
    if distro in ("debian", "ubuntu"):
        pass
    else:
        run('chroot %s chkconfig --level 2345 %s %s' % (target, service,
                                                        state))


def create_ami(host_instance, options, config):
    connection = host_instance.connection
    env.host_string = host_instance.public_dns_name
    env.user = 'root'
    env.abort_on_prompts = True
    env.disable_known_hosts = True

    target_name = options.config
    virtualization_type = config.get("virtualization_type")
    config_dir = "%s/%s" % (AMI_CONFIGS_DIR, target_name)
    dated_target_name = "%s-%s" % (
        options.config, time.strftime("%Y-%m-%d-%H-%M", time.gmtime()))
    int_dev_name = config['target']['int_dev_name']
    mount_dev = int_dev_name
    mount_point = config['target']['mount_point']

    v = connection.create_volume(config['target']['size'],
                                 host_instance.placement)
    while True:
        try:
            v.attach(host_instance.id, config['target']['aws_dev_name'])
            break
        except:
            log.debug('hit error waiting for volume to be attached')
            time.sleep(10)

    wait_for_status(v, "status", "in-use", "update")
    while True:
        try:
            if run('ls %s' % int_dev_name).succeeded:
                break
        except:
            log.debug('hit error waiting for volume to be attached')
            time.sleep(10)

    # Step 0: install required packages
    if config.get('distro') not in ('debian', 'ubuntu'):
        run('which MAKEDEV >/dev/null || yum install -y MAKEDEV')
    # Step 1: prepare target FS
    run('mkdir -p %s' % mount_point)
    if virtualization_type == "hvm":
        # HVM based instances use EBS disks as raw disks. They are have to be
        # partitioned first. Additionally ,"1" should the appended to get the
        # first primary device name.
        mount_dev = "%s1" % mount_dev
        run('parted -s %s -- mklabel msdos' % int_dev_name)
        run('parted -s -a optimal %s -- mkpart primary ext2 0 -1s' % int_dev_name)
        run('parted -s %s -- set 1 boot on' % int_dev_name)
    run('/sbin/mkfs.{fs_type} {dev}'.format(
        fs_type=config['target']['fs_type'], dev=mount_dev))
    run('/sbin/e2label {dev} {label}'.format(
        dev=mount_dev, label=config['target']['e2_label']))
    run('mount {dev} {mount_point}'.format(dev=mount_dev,
                                           mount_point=mount_point))
    run('mkdir {0}/dev {0}/proc {0}/etc'.format(mount_point))
    if config.get('distro') not in ('debian', 'ubuntu'):
        run('mount -t proc proc %s/proc' % mount_point)
        run('for i in console null zero ; '
            'do /sbin/MAKEDEV -d %s/dev -x $i ; done' % mount_point)

    # Step 2: install base system
    if config.get('distro') in ('debian', 'ubuntu'):
        run('apt-get update')
        run('which debootstrap >/dev/null || apt-get install -y debootstrap')
        run('debootstrap precise %s http://puppetagain.pub.build.mozilla.org/data/repos/apt/ubuntu/' % mount_point)
        run('chroot %s mount -t proc none /proc' % mount_point)
        run('mount -o bind /dev %s/dev' % mount_point)
        put('%s/releng-public.list' % AMI_CONFIGS_DIR, '%s/etc/apt/sources.list' % mount_point)
        with lcd(config_dir):
            put('usr/sbin/policy-rc.d', '%s/usr/sbin/' % mount_point, mirror_local_mode=True)
        run('chroot %s apt-get update' % mount_point)
        run('DEBIAN_FRONTEND=text chroot {mnt} apt-get install -y '
            'ubuntu-desktop openssh-server makedev curl grub {kernel}'.format(
            mnt=mount_point, kernel=config['kernel_package']))
        run('rm -f %s/usr/sbin/policy-rc.d' % mount_point)
        run('umount %s/dev' % mount_point)
        run('chroot %s ln -s /sbin/MAKEDEV /dev/' % mount_point)
        for dev in ('zero', 'null', 'console', 'generic'):
            run('chroot %s sh -c "cd /dev && ./MAKEDEV %s"' % (mount_point, dev))
        run('chroot %s apt-get clean' % mount_point)
    else:
        with lcd(config_dir):
            put('etc/yum-local.cfg', '%s/etc/yum-local.cfg' % mount_point)
            put('groupinstall', '/tmp/groupinstall')
            put('additional_packages', '/tmp/additional_packages')
        yum = 'yum -c {0}/etc/yum-local.cfg -y --installroot={0} '.format(
            mount_point)
        run('%s groupinstall "`cat /tmp/groupinstall`"' % yum)
        run('%s install `cat /tmp/additional_packages`' % yum)
        run('%s clean packages' % yum)
        # Rebuild RPM DB for cases when versions mismatch
        run('chroot %s rpmdb --rebuilddb || :' % mount_point)

    # Step 3: upload custom configuration files
    run('chroot %s mkdir -p /boot/grub' % mount_point)
    with lcd(config_dir):
        for f in ('etc/rc.local', 'etc/fstab', 'etc/hosts',
                  'etc/sysconfig/network',
                  'etc/sysconfig/network-scripts/ifcfg-eth0',
                  'etc/init.d/rc.local', 'boot/grub/device.map',
                  'etc/network/interfaces', 'boot/grub/menu.lst',
                  'boot/grub/grub.conf'):
            if os.path.exists(os.path.join(config_dir, f)):
                put(f, '%s/%s' % (mount_point, f), mirror_local_mode=True)
            else:
                log.warn("Skipping %s", f)

    # Step 4: tune configs
    run('sed -i -e s/@ROOT_DEV_LABEL@/{label}/g -e s/@FS_TYPE@/{fs}/g '
        '{mnt}/etc/fstab'.format(label=config['target']['e2_label'],
                                 fs=config['target']['fs_type'],
                                 mnt=mount_point))
    if config.get('distro') in ('debian', 'ubuntu'):
        # sanity check
        run('ls -l %s/boot/vmlinuz-%s' % (mount_point, config['kernel_version']))
        run('sed -i s/@VERSION@/%s/g %s/boot/grub/menu.lst' %
            (config['kernel_version'], mount_point))
    else:
        run('ln -s grub.conf %s/boot/grub/menu.lst' % mount_point)
        run('ln -s ../boot/grub/grub.conf %s/etc/grub.conf' % mount_point)
        if config.get('kernel_package') == 'kernel-PAE':
            run('sed -i s/@VERSION@/`chroot %s rpm -q '
                '--queryformat "%%{version}-%%{release}.%%{arch}.PAE" '
                '%s | tail -n1`/g %s/boot/grub/grub.conf' %
                (mount_point, config.get('kernel_package', 'kernel'), mount_point))
        else:
            run('sed -i s/@VERSION@/`chroot %s rpm -q '
                '--queryformat "%%{version}-%%{release}.%%{arch}" '
                '%s | tail -n1`/g %s/boot/grub/grub.conf' %
                (mount_point, config.get('kernel_package', 'kernel'), mount_point))
        if virtualization_type == "hvm":
            # See https://bugs.archlinux.org/task/30241 for the details,
            # grub-nstall doesn't handle /dev/xvd* devices properly
            grub_install_patch = os.path.join(config_dir, "grub-install.diff")
            if os.path.exists(grub_install_patch):
                put(grub_install_patch, "/tmp/grub-install.diff")
                run('which patch >/dev/null || yum install -y patch')
                run('patch -p0 -i /tmp/grub-install.diff /sbin/grub-install')
            run("grub-install --root-directory=%s --no-floppy %s" %
                (mount_point, int_dev_name))

    run("sed -i -e '/PermitRootLogin/d' -e '/UseDNS/d' "
        "-e '$ a PermitRootLogin without-password' "
        "-e '$ a UseDNS no' "
        "%s/etc/ssh/sshd_config" % mount_point)

    if config.get('distro') in ('debian', 'ubuntu'):
        pass
    else:
        manage_service("network", mount_point, "on")
        manage_service("rc.local", mount_point, "on")

    run('umount %s/proc || :' % mount_point)
    run('umount %s' % mount_point)

    v.detach()
    wait_for_status(v, "status", "available", "update")

    # Step 5: Create a snapshot
    log.info('Creating a snapshot')
    snapshot = v.create_snapshot('EBS-backed %s' % dated_target_name)
    wait_for_status(snapshot, "status", "completed", "update")
    snapshot.add_tag('Name', dated_target_name)

    # Step 6: Create an AMI
    log.info('Creating AMI')
    host_img = connection.get_image(config['ami'])
    block_map = BlockDeviceMapping()
    block_map[host_img.root_device_name] = BlockDeviceType(
        snapshot_id=snapshot.id)
    if virtualization_type == "hvm":
        kernel_id = None
        ramdisk_id = None
    else:
        kernel_id = host_img.kernel_id
        ramdisk_id = host_img.ramdisk_id

    ami_id = connection.register_image(
        dated_target_name,
        '%s EBS AMI' % dated_target_name,
        architecture=config['arch'],
        kernel_id=kernel_id,
        ramdisk_id=ramdisk_id,
        root_device_name=host_img.root_device_name,
        block_device_map=block_map,
        virtualization_type=virtualization_type,
    )
    while True:
        try:
            ami = connection.get_image(ami_id)
            ami.add_tag('Name', dated_target_name)
            if config["target"].get("tags"):
                for tag, value in config["target"]["tags"].items():
                    log.info("Tagging %s: %s", tag, value)
                    ami.add_tag(tag, value)
            log.info('AMI created')
            log.info('ID: {id}, name: {name}'.format(id=ami.id, name=ami.name))
            break
        except:
            log.info('Wating for AMI')
            time.sleep(10)

    # Step 7: Cleanup
    if not options.keep_volume:
        log.info('Deleting volume')
        v.delete()
    if not options.keep_host_instance:
        log.info('Terminating host instance')
        host_instance.terminate()

    return ami


if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.set_defaults(
        config=None,
        region="us-west-1",
        secrets=None,
        key_name=None,
        action="create",
        keep_volume=False,
        keep_host_instance=False,
    )
    parser.add_option("-c", "--config", dest="config",
                      help="instance configuration to use")
    parser.add_option("-r", "--region", dest="region", help="region to use")
    parser.add_option("-k", "--secrets", dest="secrets",
                      help="file where secrets can be found")
    parser.add_option("-s", "--key-name", dest="key_name", help="SSH key name")
    parser.add_option('--keep-volume', dest='keep_volume', action='store_true',
                      help="Don't delete target volume")
    parser.add_option('--keep-host-instance', dest='keep_host_instance',
                      action='store_true', help="Don't delete host instance")
    parser.add_option('--user', dest='user', default='root')

    options, args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if not args:
        parser.error("at least one instance name is required")

    if not options.config:
        parser.error("config name is required")

    if not options.secrets:
        parser.error("secrets are required")

    if not options.key_name:
        parser.error("SSH key name name is required")

    try:
        config = json.load(open("%s/%s.json" % (AMI_CONFIGS_DIR,
                                                options.config)))[options.region]
        secrets = json.load(open(options.secrets))
    except KeyError:
        parser.error("unknown configuration")

    connection = get_aws_connection(options.region,
                                    secrets["aws_access_key_id"],
                                    secrets["aws_secret_access_key"])
    host_instance = run_instance(connection, args[0], config, options.key_name,
                                 options.user)
    create_ami(host_instance, options, config)
