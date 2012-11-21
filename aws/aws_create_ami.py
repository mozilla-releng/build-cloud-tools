#!/usr/bin/env python

import boto
from boto.ec2 import connect_to_region
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from fabric.api import run, put, env, lcd, sudo
import json
import uuid
import time
import logging
log = logging.getLogger()

configs = {
    "centos-6-x86_64-base": {
        "us-east-1": {
            "ami": "ami-41d00528",  # Any RHEL-6.2 AMI
            "instance_type": "c1.xlarge",
            "arch": "x86_64",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdl",
                "mount_point": "/mnt",
            },
        },
        "us-west-1": {
            "ami": "ami-250e5060",  # Any RHEL-6.2 AMI
            "instance_type": "c1.xlarge",
            "arch": "x86_64",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdl",
                "mount_point": "/mnt",
            },
        },
        "us-west-2": {
            "ami": "ami-8a25a9ba",  # Any RHEL-6.2 AMI
            "instance_type": "c1.xlarge",
            "arch": "x86_64",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdl",
                "mount_point": "/mnt",
            },
        },
    },
    "centos-6-i386-base": {
        "us-east-1": {
            "ami": "ami-cdd306a4",  # Any RHEL-6. i386 AMI
            "instance_type": "m1.medium",
            "arch": "i386",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdl",
                "mount_point": "/mnt",
            },
        },
        "us-west-1": {
            "ami": "ami-e50e50a0",
            "instance_type": "m1.medium",
            "arch": "i386",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdl",
                "mount_point": "/mnt",
            },
        },
    },
    "fedora-12-x86_64-desktop": {
        "us-east-1": {
            "ami": "ami-41d00528",  # Any RHEL-6.2 AMI
            "instance_type": "c1.xlarge",
            "arch": "x86_64",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdl",
                "mount_point": "/mnt",
            },
        },
        "us-west-1": {
            "ami": "ami-250e5060",  # Any RHEL-6.2 AMI
            "instance_type": "c1.xlarge",
            "arch": "x86_64",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdl",
                "mount_point": "/mnt",
            },
        },
    },
    "fedora-12-i386-desktop": {
        "us-east-1": {
            "ami": "ami-cdd306a4",  # Any RHEL-6. i386 AMI
            "instance_type": "m1.medium",
            "arch": "i386",
            "kernel_package": "kernel-PAE",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdl",
                "mount_point": "/mnt",
            },
        },
        "us-west-1": {
            "ami": "ami-e50e50a0",
            "instance_type": "m1.medium",
            "arch": "i386",
            "kernel_package": "kernel-PAE",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdl",
                "mount_point": "/mnt",
            },
        },
    },
    "fedora-17-x86_64-desktop": {
        "us-west-1": {
            # See https://fedoraproject.org/wiki/Cloud_images
            "ami": "ami-877e24c2",
            "instance_type": "c1.xlarge",
            "arch": "x86_64",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdh",
                "mount_point": "/mnt",
            },
        },
        "us-east-1": {
            # See https://fedoraproject.org/wiki/Cloud_images
            "ami": "ami-a1ef36c8",
            "instance_type": "c1.xlarge",
            "arch": "x86_64",
            "target": {
                "size": 4,
                "fs_type": "ext4",
                "e2_label": "root_dev",
                "aws_dev_name": "/dev/sdh",
                "int_dev_name": "/dev/xvdh",
                "mount_point": "/mnt",
            },
        },
    },
}


def create_connection(options):
    secrets = json.load(open(options.secrets))
    connection = connect_to_region(
        options.region,
        aws_access_key_id=secrets['aws_access_key_id'],
        aws_secret_access_key=secrets['aws_secret_access_key'],
    )
    return connection


def create_instance(connection, instance_name, config, key_name, user='root'):

    bdm = None
    if 'device_map' in config:
        bdm = BlockDeviceMapping()
        for device, device_info in config['device_map'].items():
            bdm[device] = BlockDeviceType(size=device_info['size'],
                                          delete_on_termination=True)

    reservation = connection.run_instances(
        image_id=config['ami'],
        key_name=key_name,
        instance_type=config['instance_type'],
        block_device_map=bdm,
        client_token=str(uuid.uuid4())[:16],
    )

    instance = reservation.instances[0]
    log.info("instance %s created, waiting to come up", instance)
    # Wait for the instance to come up
    while True:
        try:
            instance.update()
            if instance.state == 'running':
                env.host_string = instance.public_dns_name
                env.user = user
                env.abort_on_prompts = True
                env.disable_known_hosts = True
                if run('date').succeeded:
                    break
        except:
            log.debug('hit error waiting for instance to come up')
        time.sleep(10)
    instance.add_tag('Name', instance_name)
    # Overwrite root's limited authorized_keys
    if user != 'root':
        sudo('cp -f ~%s/.ssh/authorized_keys /root/.ssh/authorized_keys' % user)
    return instance


def create_ami(host_instance, options, config):
    # TODO: use mozilla yum repos
    # TODO: swap?
    # TODO: factor status checks
    connection = host_instance.connection
    env.host_string = host_instance.public_dns_name
    env.user = 'root'
    env.abort_on_prompts = True
    env.disable_known_hosts = True

    target_name = options.config
    int_dev_name = config['target']['int_dev_name']
    mount_point = config['target']['mount_point']

    v = connection.create_volume(config['target']['size'],
                                 host_instance.placement)
    v.attach(host_instance.id, config['target']['aws_dev_name'])

    while True:
        try:
            v.update()
            if v.status == 'in-use':
                if run('ls %s' % int_dev_name).succeeded:
                    break
        except:
            log.debug('hit error waiting for volume to be attached')
            time.sleep(10)

    # Step 0: install required packages
    run('which MAKEDEV >/dev/null || yum install -f MAKEDEV')
    # Step 1: prepare target FS
    run('/sbin/mkfs.{fs_type} {dev}'.format(
        fs_type=config['target']['fs_type'],
        dev=int_dev_name))
    run('/sbin/e2label {dev} {label}'.format(
        dev=int_dev_name, label=config['target']['e2_label']))
    run('mount {dev} {mount_point}'.format(dev=int_dev_name,
                                           mount_point=mount_point))
    run('mkdir {0}/dev {0}/proc {0}/etc'.format(mount_point))
    run('mount -t proc proc %s/proc' % mount_point)
    run('for i in console null zero ; '
        'do /sbin/MAKEDEV -d %s/dev -x $i ; done' % mount_point)

    # Step 2: install base system
    with lcd(target_name):
        put('etc/yum-local.cfg', '%s/etc/yum-local.cfg' % mount_point)
        put('groupinstall', '/tmp/groupinstall')
        put('additional_packages', '/tmp/additional_packages')
    yum = 'yum -c {0}/etc/yum-local.cfg -y --installroot={0} '.format(
        mount_point)
    run('%s groupinstall "`cat /tmp/groupinstall`"' % yum)
    run('%s install `cat /tmp/additional_packages`' % yum)
    run('%s clean packages' % yum)

    # Step 3: upload custom configuration files
    with lcd(target_name):
        for f in ('etc/rc.local', 'etc/fstab', 'etc/hosts',
                  'etc/sysconfig/network',
                  'etc/sysconfig/network-scripts/ifcfg-eth0',
                  'etc/init.d/rc.local',
                  'boot/grub/grub.conf'):
            put(f, '%s/%s' % (mount_point, f), mirror_local_mode=True)

    # Step 4: tune configs
    run('sed -i -e s/@ROOT_DEV_LABEL@/{label}/g -e s/@FS_TYPE@/{fs}/g '
        '{mnt}/etc/fstab'.format(label=config['target']['e2_label'],
                                 fs=config['target']['fs_type'],
                                 mnt=mount_point))
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
    run('echo "UseDNS no" >> %s/etc/ssh/sshd_config' % mount_point)
    run('echo "PermitRootLogin without-password" >> %s/etc/ssh/sshd_config' %
        mount_point)

    run('chroot %s chkconfig --level 2345 network on' % mount_point)
    run('chroot %s chkconfig --level 2345 rc.local on' % mount_point)
    run('chroot %s chkconfig --level 2345 firstboot off || :' % mount_point)
    run('chroot %s chkconfig --level 2345 NetworkManager off || :' %
        mount_point)

    run('umount %s/proc' % mount_point)
    run('umount %s' % mount_point)

    v.detach()
    while True:
        try:
            v.update()
            if v.status == 'available':
                break
        except:
            log.exception('hit error waiting for volume to be detached')
            time.sleep(10)

    # Step 5: Create a snapshot
    log.info('Creating a snapshot')
    snapshot = v.create_snapshot('EBS-backed %s' % target_name)
    while True:
        try:
            snapshot.update()
            if snapshot.status == 'completed':
                break
        except:
            log.exception('hit error waiting for snapshot to be taken')
            time.sleep(10)
    snapshot.add_tag('Name', target_name)

    # Step 6: Create an AMI
    log.info('Creating AMI')
    host_img = connection.get_image(config['ami'])
    block_map = BlockDeviceMapping()
    block_map[host_img.root_device_name] = BlockDeviceType(
        snapshot_id=snapshot.id)
    ami_id = connection.register_image(
        target_name,
        '%s EBS AMI' % target_name,
        architecture=config['arch'],
        kernel_id=host_img.kernel_id,
        ramdisk_id=host_img.ramdisk_id,
        root_device_name=host_img.root_device_name,
        block_device_map=block_map,
    )
    while True:
        try:
            ami = connection.get_image(ami_id)
            ami.add_tag('Name', target_name)
            log.info('AMI created')
            log.info('ID: {id}, name: {name}'.format(id=ami.id, name=ami.name))
            break
        except boto.exception.EC2ResponseError:
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
    parser.add_option("-l", "--list", dest="action", action="store_const",
                      const="list", help="list available configs")
    parser.add_option('--keep-volume', dest='keep_volume', action='store_true',
                      help="Don't delete target volume")
    parser.add_option('--keep-host-instance', dest='keep_host_instance',
                      action='store_true', help="Don't delete host instance")
    parser.add_option('--user', dest='user', default='root')

    options, args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if options.action == "list":
        for config, regions in configs.items():
            print config, regions.keys()
        # All done!
        raise SystemExit(0)

    if not args:
        parser.error("at least one instance name is required")

    if not options.config:
        parser.error("config name is required")

    if not options.secrets:
        parser.error("secrets are required")

    if not options.key_name:
        parser.error("SSH key name name is required")

    try:
        config = configs[options.config][options.region]
    except KeyError:
        parser.error('unknown configuration; run with '
                     '--list for list of supported configs')

    connection = create_connection(options)
    host_instance = create_instance(connection, args[0], config,
                                    options.key_name, options.user)
    target_ami = create_ami(host_instance, options, config)
