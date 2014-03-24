#!/usr/bin/env python
import argparse
import json
import logging
import time
import random
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from fabric.api import run, env, put, cd
import os
import site

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import get_aws_connection, wait_for_status, \
    AMI_CONFIGS_DIR, INSTANCE_CONFIGS_DIR
from cloudtools.aws.instance import run_instance

log = logging.getLogger(__name__)


def main():
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", type=argparse.FileType('r'),
                        required=True)
    parser.add_argument("--keep-last", type=int,
                        help="Keep last N AMIs, delete others")
    parser.add_argument("--ssh-key", required=True,
                        help="SSH key to be used by Fabric")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Supress logging messages")
    args = parser.parse_args()
    if not args.quiet:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.ERROR)

    if not os.path.exists(args.ssh_key):
        parser.error("Cannot read %s" % args.ssh_key)
    config = json.load(args.config)
    for cfg in config:
        ami_config_name = cfg["ami-config"]
        instance_config = cfg["instance-config"]
        ssh_key_name = cfg["ssh-key"]
        ssh_user = cfg["ssh-user"]
        regions = list(cfg["regions"])
        # Pick a random region to work in. Save the rest regions and copy the
        # generated AMI to those regions.
        region = regions.pop(random.randint(0, len(regions) - 1))
        regions_to_copy = regions
        try:
            ami_config = json.load(
                open("%s/%s.json" % (AMI_CONFIGS_DIR,
                                     ami_config_name)))[region]
            moz_type_config = json.load(
                open("%s/%s" % (INSTANCE_CONFIGS_DIR, instance_config)))
            moz_type_config = moz_type_config[region]
        except KeyError:
            log.error("Skipping unknown configuration %s", cfg, exc_info=True)
            continue
        dated_target_name = "spot-%s-%s" % (
            ami_config_name, time.strftime("%Y-%m-%d-%H-%M", time.gmtime()))
        ami = instance2ami(ami_name=dated_target_name, region=region,
                           ami_config=ami_config,
                           ami_config_name=ami_config_name,
                           instance_config=instance_config,
                           ssh_key_name=ssh_key_name, ssh_user=ssh_user,
                           ssh_key=args.ssh_key,
                           moz_type_config=moz_type_config, public=False)
        log.info("AMI %s created, copying to other regions %s", ami,
                 regions_to_copy)
        for r in regions_to_copy:
            copy_ami(ami, r)
        # Delete old AMIs
        if args.keep_last:
            for r in cfg["regions"]:
                cleanup_spot_amis(region=r, tags=moz_type_config["tags"],
                                  keep_last=args.keep_last)


def instance2ami(ami_name, region, ami_config, ami_config_name,
                 instance_config, ssh_key, ssh_key_name, ssh_user,
                 moz_type_config, public=False):
    log.debug("Creting %s in %s", ami_name, region)
    conn = get_aws_connection(region)

    filters = {
        "tag:moz-state": "ready",
        "instance-state-name": "stopped"
    }
    for tag, value in moz_type_config["tags"].iteritems():
        filters["tag:%s" % tag] = value
    using_stopped_instance = True
    instances = conn.get_only_instances(filters=filters)
    if not instances:
        filters["instance-state-name"] = "running"
        instances = conn.get_only_instances(filters=filters)
        using_stopped_instance = False
    # skip loaned instances
    instances = [i for i in instances if not i.tags.get("moz-loaned-to")]
    i = sorted(instances, key=lambda i: i.launch_time)[-1]
    log.debug("Selected instance to clone: %s", i)
    v_id = i.block_device_mapping[i.root_device_name].volume_id
    v = conn.get_all_volumes(volume_ids=[v_id])[0]
    snap1 = v.create_snapshot("temporary snapshot of %s" % v_id)

    wait_for_status(snap1, "status", "completed", "update")
    host_instance = run_instance(
        connection=conn, instance_name="tmp", config=ami_config,
        key_name=ssh_key_name, user=ssh_user, key_filename=ssh_key,
        subnet_id=random.choice(moz_type_config["subnet_ids"]))

    env.host_string = host_instance.private_ip_address
    env.user = 'root'
    env.abort_on_prompts = True
    env.disable_known_hosts = True
    env.key_filename = ssh_key
    int_dev_name = ami_config['target']['int_dev_name']
    mount_dev = int_dev_name
    mount_point = ami_config['target']['mount_point']
    virtualization_type = ami_config.get("virtualization_type")
    if virtualization_type == "hvm":
        mount_dev = "%s1" % mount_dev
    tmp_v = conn.create_volume(size=snap1.volume_size,
                               zone=host_instance.placement,
                               snapshot=snap1)
    wait_for_status(tmp_v, "status", "available", "update")
    while True:
        try:
            tmp_v.attach(host_instance.id,
                         ami_config['target']['aws_dev_name'])
            break
        except:
            log.debug('hit error waiting for volume to be attached')
            time.sleep(10)
    while True:
        try:
            tmp_v.update()
            if tmp_v.status == 'in-use':
                if run('ls %s' % int_dev_name).succeeded:
                    break
        except:
            log.debug('hit error waiting for volume to be attached')
            time.sleep(10)
    run('mkdir -p %s' % mount_point)
    run('mount {dev} {mount_point}'.format(dev=mount_dev,
                                           mount_point=mount_point))
    with cd(mount_point):
        run("rm -f root/*.sh")
        run("rm -f root/*.log")
        run("rm -f root/userdata")
        run("rm -f root/*.done")
        run("rm -f etc/spot_setup.done")
        run("rm -f var/lib/puppet/ssl/private_keys/*")
        run("rm -f var/lib/puppet/ssl/certs/*")
        if not using_stopped_instance or public:
            run("rm -rf builds/slave")
        else:
            run("rm -f builds/slave/buildbot.tac")
        run("echo localhost > etc/hostname")
        run("sed -i -e 's/127.0.0.1.*/127.0.0.1 localhost/g' etc/hosts")
        if public:
            # put rc.local
            put("%s/%s/etc/rc.local" % (AMI_CONFIGS_DIR, ami_config_name),
                "etc/rc.local", mirror_local_mode=True)
            run("rm -rf home/cltbld/.ssh")
            run("rm -rf root/.ssh/*")
            run("rm -rf builds/gapi.data")
            run("rm -rf builds/mock_mozilla/*/root/home/mock_mozilla")
        else:
            put("%s/spot_setup.sh" % AMI_CONFIGS_DIR,
                "etc/spot_setup.sh", mirror_local_mode=True)
            # replace puppet init with our script
            if ami_config["distro"] == "ubuntu":
                put("%s/spot_setup.conf" % AMI_CONFIGS_DIR,
                    "etc/init/puppet.conf", mirror_local_mode=True)
            else:
                run("echo '/etc/spot_setup.sh' > etc/init.d/puppet")
    # create snapshot2
    log.info('Terminating %s', host_instance)
    host_instance.terminate()
    wait_for_status(tmp_v, "status", "available", "update")
    log.info('Creating a snapshot')
    snap2 = tmp_v.create_snapshot(ami_name)
    wait_for_status(snap2, "status", "completed", "update")
    snap2.add_tag("Name", ami_name)

    bdm = BlockDeviceMapping()
    bdm[i.root_device_name] = BlockDeviceType(snapshot_id=snap2.id)

    log.info('Creating AMI')

    if virtualization_type == "hvm":
        kernel_id = None
    else:
        kernel_id = i.kernel

    ami_id = conn.register_image(
        ami_name,
        ami_name,
        architecture=ami_config["arch"],
        kernel_id=kernel_id,
        root_device_name=i.root_device_name,
        block_device_map=bdm,
        virtualization_type=virtualization_type,
    )
    log.info('Waiting...')
    while True:
        try:
            ami = conn.get_image(ami_id)
            ami.add_tag('Name', ami_name)
            ami.add_tag('moz-created', int(time.mktime(time.gmtime())))
            for tag, value in moz_type_config["tags"].iteritems():
                ami.add_tag(tag, value)
            log.info('AMI created')
            log.info('ID: {id}, name: {name}'.format(id=ami.id, name=ami.name))
            break
        except:
            log.info('Wating for AMI')
            time.sleep(10)
    # Step 7: Cleanup
    log.info('Cleanup...')
    tmp_v.delete()
    snap1.delete()
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
        else:
            return new_ami


def get_spot_amis(region, tags):
    conn = get_aws_connection(region)
    filters = {}
    for tag, value in tags.iteritems():
        filters["tag:%s" % tag] = value
    # override Name tag
    filters["tag:Name"] = "spot-*"
    avail_amis = conn.get_all_images(owners=["self"], filters=filters)
    return sorted(avail_amis, key=lambda ami: ami.tags.get("moz-created"))


def cleanup_spot_amis(region, tags, keep_last, dry_run=False):
    amis = get_spot_amis(region, tags)
    conn = get_aws_connection(region)
    if len(amis) > keep_last:
        amis_to_delete = amis[:-keep_last]
        if dry_run:
            log.warn("Would delete %s AMIs out of %s", len(amis_to_delete),
                     len(amis))
            log.warn("Would delete these AMIs: %s" % amis_to_delete)
            log.warn("AMIs all: %s", ", ".join(ami.name for ami in amis))
            log.warn("AMIs del: %s", ", ".join(ami.name for ami in
                                               amis_to_delete))
            return
        for a in amis_to_delete:
            snap_id = a.block_device_mapping[a.root_device_name].snapshot_id
            snap = conn.get_all_snapshots(snapshot_ids=[snap_id])[0]
            log.warn("Deleting %s" % a)
            a.deregister()
            log.warn("Deleting %s" % snap)
            snap.delete()

if __name__ == '__main__':
    main()
