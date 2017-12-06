#!/usr/bin/env python

import argparse
import boto
import json
import time
import logging
import os

from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from fabric.api import run, put, lcd
from fabric.context_managers import hide
from cloudtools.aws import AMI_CONFIGS_DIR, wait_for_status
from cloudtools.aws.ami import ami_cleanup, copy_ami
from cloudtools.aws.instance import run_instance, assimilate_instance
from cloudtools.fabric import setup_fabric_env

log = logging.getLogger(__name__)


def manage_service(service, target, state, distro="centos"):
    assert state in ("on", "off")
    if distro in ("debian", "ubuntu"):
        pass
    else:
        run('chroot %s chkconfig --level 2345 %s %s' % (target, service,
                                                        state))


def partition_image(mount_dev, int_dev_name, img_file):
    run("mkdir /mnt-tmp")
    run("mkfs.ext4 %s" % int_dev_name)
    run("mount %s /mnt-tmp" % int_dev_name)
    run("fallocate -l 10G /mnt-tmp/{}".format(img_file))
    run("losetup /dev/loop0 /mnt-tmp/{}".format(img_file))
    run('parted -s /dev/loop0 -- mklabel msdos')
    # /boot uses 64M, reserve 64 sectors for grub
    run('parted -s -a optimal /dev/loop0 -- mkpart primary ext2 64s 128')
    # / uses the rest
    run('parted -s -a optimal /dev/loop0 -- mkpart primary ext2 128 -1s')
    run('parted -s /dev/loop0 -- set 1 boot on')
    run('parted -s /dev/loop0 -- set 2 lvm on')
    run("kpartx -av /dev/loop0")
    run("mkfs.ext2 /dev/mapper/loop0p1")
    run("pvcreate /dev/mapper/loop0p2")
    run("vgcreate cloud_root /dev/mapper/loop0p2")
    run("lvcreate -n lv_root -l 100%FREE cloud_root")


def partition_ebs_volume(int_dev_name):
    # HVM based instances use EBS disks as raw disks. They are have to be
    # partitioned first. Additionally ,"1" should the appended to get the
    # first primary device name.
    run('parted -s %s -- mklabel msdos' % int_dev_name)
    # /boot uses 256M, reserve 64 sectors for grub
    run('parted -s -a optimal %s -- mkpart primary ext2 64s 256' %
        int_dev_name)
    # / uses the rest
    run('parted -s -a optimal %s -- mkpart primary ext2 256 -1s' %
        int_dev_name)
    run('parted -s %s -- set 1 boot on' % int_dev_name)
    run('parted -s %s -- set 2 lvm on' % int_dev_name)
    run("mkfs.ext2 %s1" % int_dev_name)
    run("pvcreate %s2" % int_dev_name)
    run("vgcreate cloud_root %s2" % int_dev_name)
    run("lvcreate -n lv_root -l 100%FREE cloud_root")


def attach_and_wait(host_instance, size, aws_dev_name, int_dev_name):
    v = host_instance.connection.create_volume(size, host_instance.placement)
    while True:
        try:
            v.attach(host_instance.id, aws_dev_name)
            break
        except:  # noqa: E722
            log.debug('waiting for volume to be attached')
            time.sleep(10)

    wait_for_status(v, "status", "in-use", "update")
    while True:
        try:
            if run('ls %s' % int_dev_name).succeeded:
                break
        except:  # noqa: E722
            log.debug('waiting for volume to appear', exc_info=True)
            time.sleep(10)
    return v


def read_packages(packages_file):
    with open(packages_file) as f:
        packages = " ".join(line.strip() for line in f.readlines())

    return packages


def install_packages(packages_file, distro, chroot=None):
    if distro not in ("debian", "ubuntu"):
        raise NotImplementedError
    packages = read_packages(packages_file)
    if chroot:
        chroot_prefix = "chroot {} ".format(chroot)
    else:
        chroot_prefix = ""

    if distro in ("debian", "ubuntu"):
        run("{}apt-get update".format(chroot_prefix))
        run("DEBIAN_FRONTEND=noninteractive {}apt-get install -y "
            "--force-yes {}".format(chroot_prefix, packages))
        run("{}apt-get clean".format(chroot_prefix))


def sync(src, dst):
    for local_directory, _, files in os.walk(src, followlinks=True):
        directory = os.path.relpath(local_directory, src)
        if directory == '.':
            directory = ''

        remote_directory = os.path.join(dst, directory)
        if directory != '':
            run('mkdir -p %s' % remote_directory)

        for f in files:
            local_file = os.path.join(local_directory, f)
            remote_file = os.path.join(remote_directory, f)
            put(local_file, remote_file, mirror_local_mode=True)


def create_ami(host_instance, args, config, instance_config, ssh_key,
               key_filename, instance_data, deploypass, cert, pkey,
               ami_name_prefix):
    connection = host_instance.connection
    setup_fabric_env(instance=host_instance, abort_on_prompts=True,
                     disable_known_hosts=True, key_filename=key_filename)

    target_name = args.config
    virtualization_type = config.get("virtualization_type")
    config_dir = "%s/%s" % (AMI_CONFIGS_DIR, target_name)
    if ami_name_prefix:
        prefix = ami_name_prefix
    else:
        prefix = args.config
    dated_target_name = "{}-{}".format(
        prefix, time.strftime("%Y-%m-%d-%H-%M", time.gmtime()))

    if config.get('distro') in ('debian', 'ubuntu'):
        ubuntu_release = config.get("release", "precise")
    int_dev_name = config['target']['int_dev_name']
    mount_dev = int_dev_name
    grub_dev = int_dev_name
    mount_point = config['target']['mount_point']
    boot_mount_dev = None
    host_packages_file = os.path.join(config_dir, "host_packages")
    packages_file = os.path.join(config_dir, "packages")
    if os.path.exists(host_packages_file):
        install_packages(host_packages_file, config.get('distro'))

    v = attach_and_wait(host_instance, config['target']['size'],
                        config['target']['aws_dev_name'], int_dev_name)

    # Step 0: install required packages
    if config.get('distro') == "centos":
        run('which MAKEDEV >/dev/null || yum -d 1 install -y MAKEDEV')

    # Step 1: prepare target FS
    run('mkdir -p %s' % mount_point)
    if config.get("root_device_type") == "instance-store":
        # Use file image
        mount_dev = "/dev/cloud_root/lv_root"
        grub_dev = "/dev/loop0"
        boot_mount_dev = "/dev/mapper/loop0p1"
        img_file = dated_target_name
        partition_image(mount_dev=mount_dev, int_dev_name=int_dev_name,
                        img_file=img_file)

    elif virtualization_type == "hvm":
        # use EBS volume
        mount_dev = "/dev/cloud_root/lv_root"
        boot_mount_dev = "%s1" % int_dev_name
        partition_ebs_volume(int_dev_name=int_dev_name)

    run('/sbin/mkfs.{fs_type} {args} {dev}'.format(
        fs_type=config['target']['fs_type'],
        args=config['target'].get("mkfs_args", ""), dev=mount_dev))
    run('/sbin/e2label {dev} {label}'.format(
        dev=mount_dev, label=config['target']['e2_label']))
    run('mount {dev} {mount_point}'.format(dev=mount_dev,
                                           mount_point=mount_point))
    run('mkdir {0}/dev {0}/proc {0}/etc {0}/boot {0}/sys'.format(mount_point))
    run('mount -t sysfs sys %s/sys' % mount_point)

    if config.get('distro') not in ('debian', 'ubuntu'):
        run('mount -t proc proc %s/proc' % mount_point)
        run('for i in console null zero random urandom; '
            'do /sbin/MAKEDEV -d %s/dev -x $i ; done' % mount_point)
    if boot_mount_dev:
        run('mount {} {}/boot'.format(boot_mount_dev, mount_point))

    # Step 2: install base system
    if config.get('distro') in ('debian', 'ubuntu'):
        run("debootstrap %s %s "
            "http://puppet/repos/apt/ubuntu/"
            % (ubuntu_release, mount_point))
        run('chroot %s mount -t proc none /proc' % mount_point)
        run('mount -o bind /dev %s/dev' % mount_point)
        put('%s/releng-public-%s.list' % (AMI_CONFIGS_DIR, ubuntu_release),
            '%s/etc/apt/sources.list' % mount_point)
        with lcd(config_dir):
            put('usr/sbin/policy-rc.d', '%s/usr/sbin/' % mount_point,
                mirror_local_mode=True)
        install_packages(packages_file, config.get('distro'),
                         chroot=mount_point)
    else:
        with lcd(config_dir):
            put('etc/yum-local.cfg', '%s/etc/yum-local.cfg' % mount_point)
        yum = 'yum -d 1 -c {0}/etc/yum-local.cfg -y --installroot={0} '.format(
            mount_point)
        # this groupinstall emulates the %packages section of the kickstart
        # config, which defaults to Core and Base.
        run('%s groupinstall Core Base' % yum)
        run('%s clean packages' % yum)
        # Rebuild RPM DB for cases when versions mismatch
        run('chroot %s rpmdb --rebuilddb || :' % mount_point)

    # Step 3: upload custom configuration files
    run('chroot %s mkdir -p /boot/grub' % mount_point)
    for directory in ('boot', 'etc', 'usr'):
        local_directory = os.path.join(config_dir, directory)
        remote_directory = os.path.join(mount_point, directory)
        if not os.path.exists(local_directory):
            pass

        sync(local_directory, remote_directory)

    # Step 4: tune configs
    run('sed -i -e s/@ROOT_DEV_LABEL@/{label}/g -e s/@FS_TYPE@/{fs}/g '
        '{mnt}/etc/fstab'.format(label=config['target']['e2_label'],
                                 fs=config['target']['fs_type'],
                                 mnt=mount_point))
    if config.get('distro') in ('debian', 'ubuntu'):
        if virtualization_type == "hvm":
            run("chroot {mnt} grub-install {int_dev_name}".format(
                mnt=mount_point, int_dev_name=int_dev_name))
            run("chroot {mnt} update-grub".format(mnt=mount_point))
        else:
            run("chroot {mnt} update-grub -y".format(mnt=mount_point))
            run("sed  -i 's/^# groot.*/# groot=(hd0)/g' "
                "{mnt}/boot/grub/menu.lst".format(mnt=mount_point))
            run("chroot {mnt} update-grub".format(mnt=mount_point))
    else:
        run('ln -s grub.conf %s/boot/grub/menu.lst' % mount_point)
        run('ln -s ../boot/grub/grub.conf %s/etc/grub.conf' % mount_point)
        if config.get('kernel_package') == 'kernel-PAE':
            run('sed -i s/@VERSION@/`chroot %s rpm -q '
                '--queryformat "%%{version}-%%{release}.%%{arch}.PAE" '
                '%s | tail -n1`/g %s/boot/grub/grub.conf' %
                (mount_point, config.get('kernel_package', 'kernel'),
                 mount_point))
        else:
            run('sed -i s/@VERSION@/`chroot %s rpm -q '
                '--queryformat "%%{version}-%%{release}.%%{arch}" '
                '%s | tail -n1`/g %s/boot/grub/grub.conf' %
                (mount_point, config.get('kernel_package', 'kernel'),
                 mount_point))
        if config.get("root_device_type") == "instance-store":
            # files normally copied by grub-install
            run("cp -va /usr/share/grub/x86_64-redhat/* /mnt/boot/grub/")
            put(os.path.join(config_dir, "grub.cmd"), "/tmp/grub.cmd")
            run("sed -i s/@IMG@/{}/g /tmp/grub.cmd".format(img_file))
            run("cat /tmp/grub.cmd | grub --device-map=/dev/null")
        elif virtualization_type == "hvm":
            # See https://bugs.archlinux.org/task/30241 for the details,
            # grub-nstall doesn't handle /dev/xvd* devices properly
            grub_install_patch = os.path.join(config_dir, "grub-install.diff")
            if os.path.exists(grub_install_patch):
                put(grub_install_patch, "/tmp/grub-install.diff")
                run('which patch >/dev/null || yum -d 1 install -y patch')
                run('patch -p0 -i /tmp/grub-install.diff /sbin/grub-install')
            run("grub-install --root-directory=%s --no-floppy %s" %
                (mount_point, grub_dev))

    run("sed -i -e '/PermitRootLogin/d' -e '/UseDNS/d' "
        "-e '$ a PermitRootLogin without-password' "
        "-e '$ a UseDNS no' "
        "%s/etc/ssh/sshd_config" % mount_point)

    if config.get('distro') in ('debian', 'ubuntu'):
        pass
    else:
        manage_service("network", mount_point, "on")
        manage_service("rc.local", mount_point, "on")

    if config.get("root_device_type") == "instance-store" and \
            config.get("distro") == "centos":
        instance_data = instance_data.copy()
        instance_data['name'] = host_instance.tags.get("Name")
        instance_data['hostname'] = host_instance.tags.get("FQDN")
        run("cp /etc/resolv.conf {}/etc/resolv.conf".format(mount_point))
        # make puppet happy
        # disable ipv6
        run("/sbin/service ip6tables stop")
        # mount /dev to let sshd start
        run('mount -o bind /dev %s/dev' % mount_point)
        assimilate_instance(host_instance, instance_config, ssh_key,
                            instance_data, deploypass, chroot=mount_point,
                            reboot=False)
        ami_cleanup(mount_point=mount_point, distro=config["distro"])
        # kill chroot processes
        put('%s/kill_chroot.sh' % AMI_CONFIGS_DIR, '/tmp/kill_chroot.sh')
        run('bash /tmp/kill_chroot.sh {}'.format(mount_point))
        run('swapoff -a')
    run('umount %s/dev || :' % mount_point)
    if config.get("distro") == "ubuntu":
        run('rm -f %s/usr/sbin/policy-rc.d' % mount_point)
        run('chroot %s ln -s /sbin/MAKEDEV /dev/' % mount_point)
        for dev in ('zero', 'null', 'console', 'generic'):
            run('chroot %s sh -c "cd /dev && ./MAKEDEV %s"' % (mount_point, dev))
    run('umount %s/sys || :' % mount_point)
    run('umount %s/proc || :' % mount_point)
    run('umount %s/dev  || :' % mount_point)
    run('umount %s/boot || :' % mount_point)
    run('umount %s' % mount_point)
    if config.get("root_device_type") == "instance-store" \
            and config.get("distro") == "centos":
        # create bundle
        run("yum -d 1 install -y ruby "
            "http://s3.amazonaws.com/ec2-downloads/ec2-ami-tools.noarch.rpm")
        bundle_location = "{b}/{d}/{t}/{n}".format(
            b=config["bucket"], d=config["bucket_dir"],
            t=config["target"]["tags"]["moz-type"], n=dated_target_name)
        manifest_location = "{}/{}.manifest.xml".format(bundle_location,
                                                        dated_target_name)
        run("mkdir -p /mnt-tmp/out")
        put(cert, "/mnt-tmp/cert.pem")
        put(pkey, "/mnt-tmp/pk.pem")
        run("ec2-bundle-image -c /mnt-tmp/cert.pem -k /mnt-tmp/pk.pem "
            "-u {uid} -i /mnt-tmp/{img_file} -d /mnt-tmp/out -r x86_64".format(
                img_file=img_file, uid=config["aws_user_id"]))

        with hide('running', 'stdout', 'stderr'):
            log.info("uploading bundle")
            run("ec2-upload-bundle -b {bundle_location}"
                " --access-key {access_key} --secret-key {secret_key}"
                " --region {region}"
                " -m /mnt-tmp/out/{img_file}.manifest.xml  --retry".format(
                    bundle_location=bundle_location,
                    access_key=boto.config.get("Credentials",
                                               "aws_access_key_id"),
                    secret_key=boto.config.get("Credentials",
                                               "aws_secret_access_key"),
                    region=connection.region.name,
                    img_file=img_file))

    v.detach(force=True)
    wait_for_status(v, "status", "available", "update")
    if not config.get("root_device_type") == "instance-store":
        # Step 5: Create a snapshot
        log.info('Creating a snapshot')
        snapshot = v.create_snapshot(dated_target_name)
        wait_for_status(snapshot, "status", "completed", "update")
        snapshot.add_tag('Name', dated_target_name)
        snapshot.add_tag('moz-created', str(int(time.mktime(time.gmtime()))))

    # Step 6: Create an AMI
    log.info('Creating AMI')
    if config.get("root_device_type") == "instance-store":
        ami_id = connection.register_image(
            dated_target_name,
            '%s AMI' % dated_target_name,
            architecture=config['arch'],
            virtualization_type=virtualization_type,
            image_location=manifest_location,
        )
    else:
        host_img = connection.get_image(config['ami'])
        block_map = BlockDeviceMapping()
        block_map[host_img.root_device_name] = BlockDeviceType(
            snapshot_id=snapshot.id)
        root_device_name = host_img.root_device_name
        if virtualization_type == "hvm":
            kernel_id = None
            ramdisk_id = None
        else:
            kernel_id = host_img.kernel_id
            ramdisk_id = host_img.ramdisk_id

        ami_id = connection.register_image(
            dated_target_name,
            '%s AMI' % dated_target_name,
            architecture=config['arch'],
            kernel_id=kernel_id,
            ramdisk_id=ramdisk_id,
            root_device_name=root_device_name,
            block_device_map=block_map,
            virtualization_type=virtualization_type,
        )
    while True:
        try:
            ami = connection.get_image(ami_id)
            ami.add_tag('Name', dated_target_name)
            ami.add_tag('moz-created', str(int(time.mktime(time.gmtime()))))
            if config["target"].get("tags"):
                for tag, value in config["target"]["tags"].items():
                    log.info("Tagging %s: %s", tag, value)
                    ami.add_tag(tag, value)
            log.info('AMI created')
            log.info('ID: {id}, name: {name}'.format(id=ami.id, name=ami.name))
            break
        except:  # noqa: E722
            log.info('Wating for AMI')
            time.sleep(10)

    # Step 7: Cleanup
    if not args.keep_volume:
        log.info('Deleting volume')
        v.delete()
    if not args.keep_host_instance:
        log.info('Terminating host instance')
        host_instance.terminate()

    return ami


def main():
    parser = argparse.ArgumentParser()
    parser.set_defaults(
        region="us-west-1",
        key_name=None,
    )
    parser.add_argument("-c", "--config", required=True,
                        help="instance configuration to use")
    parser.add_argument("-r", "--region", help="region to use",
                        default="us-east-1")
    parser.add_argument("--ssh-key", help="SSH key file", required=True)
    parser.add_argument("--key-name", help="SSH key name", required=True)
    parser.add_argument('--keep-volume', action='store_true',
                        help="Don't delete target volume")
    parser.add_argument('--keep-host-instance', action='store_true',
                        help="Don't delete host instance")
    parser.add_argument('--user', default='root')
    parser.add_argument('--puppetize', action="store_true",
                        help="Puppetize the AMI")
    parser.add_argument('--instance-config', type=argparse.FileType('r'),
                        help="Path to instance config file")
    parser.add_argument('--instance-data', type=argparse.FileType('r'),
                        help="Path to instance data file")
    parser.add_argument('--secrets', type=argparse.FileType('r'),
                        help="Path to secrets file")
    parser.add_argument('--certificate',
                        help="Path to AMI encryptiion certificate")
    parser.add_argument('--pkey',
                        help="Path to AMI encryptiion privte key")
    parser.add_argument('--ami-name-prefix', help="AMI name prefix")
    parser.add_argument("-t", "--copy-to-region", action="append", default=[],
                        dest="copy_to_regions", help="Regions to copy AMI to")
    parser.add_argument("-v", "--verbose", action="store_const",
                        default=logging.INFO, const=logging.DEBUG,
                        dest="log_level", help="Verbose logging")
    parser.add_argument("host", metavar="host", nargs=1,
                        help="Temporary hostname")

    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)
    logging.getLogger("boto").setLevel(logging.INFO)
    logging.getLogger("paramiko").setLevel(logging.INFO)
    instance_config = None
    instance_data = None
    deploypass = None
    dns_required = False

    try:
        ami_config = json.load(open("%s/%s.json" % (AMI_CONFIGS_DIR,
                                                    args.config)))[args.region]
        if args.instance_config:
            instance_config = json.load(args.instance_config)[args.region]
        if args.instance_data:
            instance_data = json.load(args.instance_data)
        if args.secrets:
            deploypass = json.load(args.secrets)["deploy_password"]

    except KeyError:
        parser.error("unknown configuration")
        raise
    except IOError:
        parser.error("Cannot read")
        raise

    if args.puppetize:
        dns_required = True
        for attr in ("instance_config", "instance_data", "secrets"):
            if not getattr(args, attr):
                parser.error("{} is required for puppetizing AMIs".format(attr))
        if ami_config.get("root_device_type") == "instance-store":
            for attr in ("certificate", "pkey"):
                if not getattr(args, attr):
                    parser.error(
                        "{} is required for S3-backed AMIs".format(attr))

    host_instance = run_instance(region=args.region, hostname=args.host[0],
                                 config=ami_config, key_name=args.key_name,
                                 user=args.user, key_filename=args.ssh_key,
                                 dns_required=dns_required)
    ami = create_ami(host_instance=host_instance, args=args, config=ami_config,
                     instance_config=instance_config, ssh_key=args.key_name,
                     instance_data=instance_data, deploypass=deploypass,
                     cert=args.certificate, pkey=args.pkey,
                     ami_name_prefix=args.ami_name_prefix,
                     key_filename=args.ssh_key)

    for r in args.copy_to_regions:
        log.info("Copying %s (%s) to %s", ami.id, ami.tags.get("Name"), r)
        new_ami = copy_ami(ami, r)
        log.info("New AMI created. AMI ID: %s", new_ami.id)


if __name__ == '__main__':
    main()
