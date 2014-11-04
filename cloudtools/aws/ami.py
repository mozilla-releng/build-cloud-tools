import time
import logging
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from fabric.api import run, put, cd

from . import AMI_CONFIGS_DIR, wait_for_status, get_aws_connection

log = logging.getLogger(__name__)


def ami_cleanup(mount_point, distro, remove_extra=None):
    remove_extra = remove_extra or []
    remove = [
        "root/*.sh",
        "root/*.log",
        "root/userdata",
        "var/lib/puppet",
        "etc/init.d/puppet"
    ]
    with cd(mount_point):
        for e in remove + remove_extra:
            run('rm -rf %s' % (e,))
        run("sed -i -e 's/127.0.0.1.*/127.0.0.1 localhost/g' etc/hosts")
        put("%s/fake_puppet.sh" % AMI_CONFIGS_DIR,
            "usr/sbin/fake_puppet.sh", mirror_local_mode=True)
        # TODO: remove the following code when runner is deployed
        run("wget -O etc/check_ami.py https://raw.githubusercontent.com/mozilla/build-runner/master/example-tasks.d/0-check_ami.py")
        run("chmod 755 etc/check_ami.py")
        run("echo '#!/bin/sh' > usr/sbin/fake_puppet.sh")
        run("echo python /etc/check_ami.py >> usr/sbin/fake_puppet.sh")
        # TODO: end of remove
        # replace puppet init with our script
        if distro == "ubuntu":
            put("%s/fake_puppet.conf" % AMI_CONFIGS_DIR,
                "etc/init/puppet.conf", mirror_local_mode=True)
            run("echo localhost > etc/hostname")
        else:
            run("ln -sf /usr/sbin/fake_puppet.sh etc/init.d/puppet")
            run('echo "NETWORKING=yes" > etc/sysconfig/network')


def volume_to_ami(volume, ami_name, arch, virtualization_type,
                  root_device_name, tags, kernel_id=None):
    log.info('Creating a snapshot')
    snap = volume.create_snapshot(ami_name)
    wait_for_status(snap, "status", "completed", "update")
    snap.add_tag("Name", ami_name)

    bdm = BlockDeviceMapping()
    bdm[root_device_name] = BlockDeviceType(snapshot_id=snap.id)

    log.info('Creating AMI')

    ami_id = volume.connection.register_image(
        ami_name,
        ami_name,
        architecture=arch,
        kernel_id=kernel_id,
        root_device_name=root_device_name,
        block_device_map=bdm,
        virtualization_type=virtualization_type,
    )
    log.info('Waiting...')
    while True:
        try:
            ami = volume.connection.get_image(ami_id)
            ami.add_tag('Name', ami_name)
            ami.add_tag('moz-created', int(time.mktime(time.gmtime())))
            for tag, value in tags.iteritems():
                ami.add_tag(tag, value)
            log.info('AMI created')
            log.info('ID: {id}, name: {name}'.format(id=ami.id, name=ami.name))
            break
        except:
            log.info('Wating for AMI')
            time.sleep(10)
    wait_for_status(ami, "state", "available", "update")
    return ami


def copy_ami(source_ami, region_to_copy):
    log.info("Copying %s to %s", source_ami, region_to_copy)
    conn = get_aws_connection(region_to_copy)
    ami_copy = conn.copy_image(source_ami.region.name, source_ami.id,
                               source_ami.name, source_ami.description)
    while True:
        try:
            new_ami = conn.get_image(ami_copy.image_id)
            for tag, value in source_ami.tags.iteritems():
                new_ami.add_tag(tag, value)
            new_ami.update()
            log.info('AMI created')
            log.info('ID: {id}, name: {name}'.format(id=new_ami.id,
                                                     name=new_ami.name))
            break
        except:
            log.info('Wating for AMI')
            time.sleep(10)
    return new_ami


def get_spot_amis(region, tags, name_glob="spot-*"):
    conn = get_aws_connection(region)
    filters = {}
    for tag, value in tags.iteritems():
        filters["tag:%s" % tag] = value
    # override Name tag
    filters["tag:Name"] = name_glob
    avail_amis = conn.get_all_images(owners=["self"], filters=filters)
    return sorted(avail_amis, key=lambda ami: ami.tags.get("moz-created"))


def delete_old_amis(region, tags, keep_last):
    amis = get_spot_amis(region, tags)
    conn = get_aws_connection(region)
    if len(amis) > keep_last:
        amis_to_delete = amis[:-keep_last]
        for a in amis_to_delete:
            snap_id = a.block_device_mapping[a.root_device_name].snapshot_id
            snap = conn.get_all_snapshots(snapshot_ids=[snap_id])[0]
            log.warn("Deleting %s (%s)", a, a.tags.get("Name"))
            a.deregister()
            log.warn("Deleting %s (%s)", snap, snap.description)
            snap.delete()


def get_ami(region, moz_instance_type):
    conn = get_aws_connection(region)
    avail_amis = conn.get_all_images(
        owners=["self"],
        filters={"tag:moz-type": moz_instance_type, "state": "available"})
    # If creation dates are equal, use AMI IDs to sort
    last_ami = sorted(
        avail_amis, key=lambda ami: (ami.tags.get("moz-created"), ami.id))[-1]
    return last_ami
