import time
import logging
import xml.dom.minidom
import os
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from fabric.api import run, put, cd

from . import AMI_CONFIGS_DIR, wait_for_status, get_aws_connection, \
    get_s3_connection

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
            ami.add_tag('moz-created', int(time.time()))
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


def get_spot_amis(region, tags, name_glob="spot-*", root_device_type=None):
    conn = get_aws_connection(region)
    filters = {"state": "available"}
    for tag, value in tags.iteritems():
        filters["tag:%s" % tag] = value
    # override Name tag
    filters["tag:Name"] = name_glob
    if root_device_type:
        filters["root-device-type"] = root_device_type
    avail_amis = conn.get_all_images(owners=["self"], filters=filters)
    return sorted(avail_amis, key=lambda ami: ami.tags.get("moz-created"))


def delete_ebs_ami(ami):
    snap_id = ami.block_device_mapping[ami.root_device_name].snapshot_id
    snap = ami.connection.get_all_snapshots(snapshot_ids=[snap_id])[0]
    log.warn("Deleting EBS-backed AMI %s (%s)", ami, ami.tags.get("Name"))
    ami.deregister()
    log.warn("Deleting %s (%s)", snap, snap.description)
    snap.delete()


def delete_instance_store_ami(ami):
    bucket, location = ami.location.split("/", 1)
    folder = os.path.dirname(location)
    conn = get_s3_connection()
    bucket = conn.get_bucket(bucket)
    key = bucket.get_key(location)
    manifest = key.get_contents_as_string()
    dom = xml.dom.minidom.parseString(manifest)
    files = [f.firstChild.nodeValue for f in
             dom.getElementsByTagName("filename")]
    to_delete = [os.path.join(folder, f) for f in files] + [location]
    log.warn("Deleting S3-backed %s (%s)", ami, ami.tags.get("Name"))
    ami.deregister()
    log.warn("Deleting files from S3: %s", to_delete)
    bucket.delete_keys(to_delete)


def delete_ami(ami, dry_run=False):
    if dry_run:
        log.warn("Dry run: would delete %s", ami)
        return
    if ami.root_device_type == "ebs":
        delete_ebs_ami(ami)
    elif ami.root_device_type == "instance-store":
        delete_instance_store_ami(ami)


def delete_old_amis(region, tags, keep_last, root_device_type="ebs",
                    dry_run=False):
    amis = get_spot_amis(region, tags, root_device_type=root_device_type)
    if len(amis) > keep_last:
        if keep_last == 0:
            amis_to_delete = amis
        else:
            amis_to_delete = amis[:-keep_last]

        for a in amis_to_delete:
            delete_ami(a, dry_run)
    else:
        log.info("Nothing to delete")


def get_ami(region, moz_instance_type, root_device_type=None):
    """Return the most recently created AMI. root_device type can
    be either "ebs" or "instance-store" virtualization_type can be
    either "hvm" or "paravirtual"""
    spot_amis = get_spot_amis(region=region,
                              tags={"moz-type": moz_instance_type},
                              root_device_type=root_device_type)
    last_ami = spot_amis[-1]
    return last_ami
