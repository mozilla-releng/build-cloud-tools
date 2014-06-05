#!/usr/bin/env python
# TODO: delete this script
import argparse
import json
import logging
import time
import random
import os
import site

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))
from cloudtools.aws import get_aws_connection, wait_for_status, \
    AMI_CONFIGS_DIR, INSTANCE_CONFIGS_DIR, attach_and_wait_for_volume, \
    mount_device
from cloudtools.aws.instance import run_instance
from cloudtools.aws.ami import ami_cleanup, volume_to_ami, copy_ami, \
    delete_old_amis
from cloudtools.fabric import setup_fabric_env

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
                           moz_type_config=moz_type_config)
        log.info("AMI %s created, copying to other regions %s", ami,
                 regions_to_copy)
        for r in regions_to_copy:
            copy_ami(ami, r)
        # Delete old AMIs
        if args.keep_last:
            for r in cfg["regions"]:
                delete_old_amis(region=r, tags=moz_type_config["tags"],
                                keep_last=args.keep_last)


def instance2ami(ami_name, region, ami_config, ami_config_name,
                 instance_config, ssh_key, ssh_key_name, ssh_user,
                 moz_type_config):
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
    instance_id = i.id
    log.debug("Selected instance to clone: %s", i)
    v_id = i.block_device_mapping[i.root_device_name].volume_id
    v = conn.get_all_volumes(volume_ids=[v_id])[0]
    snap1 = v.create_snapshot("temporary snapshot of %s" % v_id)

    wait_for_status(snap1, "status", "completed", "update")
    host_instance = run_instance(
        connection=conn, instance_name="tmp", config=ami_config,
        key_name=ssh_key_name, user=ssh_user, key_filename=ssh_key,
        subnet_id=random.choice(moz_type_config["subnet_ids"]))

    int_dev_name = ami_config['target']['int_dev_name']
    mount_dev = int_dev_name
    mount_point = ami_config['target']['mount_point']
    virtualization_type = ami_config.get("virtualization_type")
    if virtualization_type == "hvm":
        mount_dev = "%s1" % mount_dev
    tmp_v = conn.create_volume(size=snap1.volume_size,
                               zone=host_instance.placement,
                               snapshot=snap1)
    setup_fabric_env(host_string=host_instance.private_ip_address,
                     key_filename=ssh_key)
    attach_and_wait_for_volume(
        volume=tmp_v,
        aws_dev_name=ami_config['target']['aws_dev_name'],
        internal_dev_name=int_dev_name,
        instance_id=host_instance.id)
    mount_device(device=mount_dev, mount_point=mount_point)

    remove_extra = []
    if not using_stopped_instance:
        remove_extra.append("builds/slave")
    else:
        remove_extra.append("builds/slave/buildbot.tac")
    ami_cleanup(mount_point=mount_point, distro=ami_config["distro"],
                remove_extra=remove_extra)

    # create snapshot2
    log.info('Terminating %s', host_instance)
    host_instance.terminate()
    wait_for_status(tmp_v, "status", "available", "update")

    if virtualization_type == "hvm":
        kernel_id = None
    else:
        kernel_id = i.kernel
    tags = moz_type_config["tags"]
    tags["moz-based-on"] = instance_id
    ami = volume_to_ami(volume=tmp_v, ami_name=ami_name,
                        arch=ami_config["arch"],
                        virtualization_type=virtualization_type,
                        kernel_id=kernel_id,
                        root_device_name=i.root_device_name,
                        tags=tags)
    # Step 7: Cleanup
    log.info('Cleanup...')
    tmp_v.delete()
    snap1.delete()
    return ami

if __name__ == '__main__':
    main()
