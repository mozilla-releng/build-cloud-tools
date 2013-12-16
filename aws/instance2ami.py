#!/usr/bin/env python
import argparse
import json
import logging
import time
import random
from boto.ec2 import connect_to_region
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from fabric.api import run, env, put, cd

from aws_create_ami import create_instance, AMI_CONFIGS_DIR, \
    INSTANCE_CONFIGS_DIR
log = logging.getLogger(__name__)


def wait_for_status(obj, attr_name, attr_value, update_method):
    log.debug("waiting for %s availability", obj)
    while True:
        try:
            getattr(obj, update_method)()
            if getattr(obj, attr_name) == attr_value:
                break
            else:
                time.sleep(1)
        except:
            log.exception('hit error waiting for snapshot to be taken')
            time.sleep(10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", "--secrets", type=argparse.FileType('r'),
                        help="optional file where secrets can be found")
    parser.add_argument("-r", "--region", dest="region", required=True,
                        help="optional list of regions")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Supress logging messages")
    parser.add_argument("-c", "--ami-config", required=True, help="AMI config")
    parser.add_argument("-i", "--instance-config", required=True,
                        help="Instance config")
    parser.add_argument("--ssh-key", required=True, help="SSH key name")
    parser.add_argument("--user", help="Login name")
    parser.add_argument("--public", action="store_true", default=False,
                        help="Generate a public AMI (no secrets)")
    parser.add_argument("--deploypass", required=True,
                        type=argparse.FileType('r'))

    args = parser.parse_args()
    if args.secrets:
        secrets = json.load(args.secrets)
    else:
        secrets = None
    try:
        ami_config = json.load(
            open("%s/%s.json" % (AMI_CONFIGS_DIR, args.ami_config))
        )[args.region]
        moz_type_config = json.load(
            open("%s/%s" % (INSTANCE_CONFIGS_DIR, args.instance_config))
        )[args.region]
    except KeyError:
        parser.error("unknown configuration")

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.quiet:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.ERROR)

    if secrets:
        conn = connect_to_region(
            args.region,
            aws_access_key_id=secrets['aws_access_key_id'],
            aws_secret_access_key=secrets['aws_secret_access_key']
        )
    else:
        conn = connect_to_region(args.region)

    dated_target_name = "spot-%s-%s" % (
        args.ami_config, time.strftime("%Y-%m-%d-%H-%M", time.gmtime()))
    filters = {
        "tag:moz-state": "ready",
        "instance-state-name": "stopped"
    }
    for tag, value in moz_type_config["tags"].iteritems():
        filters["tag:%s" % tag] = value
    res = conn.get_all_instances(filters=filters)
    instances = reduce(lambda a, b: a + b, [r.instances for r in res])
    i = sorted(instances, key=lambda i: i.launch_time)[-1]
    log.debug("Selected instance to clone: %s", i)
    v_id = i.block_device_mapping['/dev/sda1'].volume_id
    v = conn.get_all_volumes(volume_ids=[v_id])[0]
    snap1 = v.create_snapshot("temporary snapshot of %s" % v_id)

    wait_for_status(snap1, "status", "completed", "update")
    host_instance = create_instance(
        connection=conn, instance_name="tmp", config=ami_config,
        key_name=args.ssh_key, user=args.user,
        subnet_id=random.choice(moz_type_config["subnet_ids"]))

    env.host_string = host_instance.private_ip_address
    env.user = 'root'
    env.abort_on_prompts = True
    env.disable_known_hosts = True
    int_dev_name = ami_config['target']['int_dev_name']
    mount_point = ami_config['target']['mount_point']
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
    run('mount {dev} {mount_point}'.format(dev=int_dev_name,
                                           mount_point=mount_point))
    with cd(mount_point):
        run("rm -f root/*.sh")
        run("rm -f root/*.log")
        run("rm -f root/userdata")
        run("rm -f root/*.done")
        run("rm -f etc/setup_hostname.done")
        run("rm -f var/lib/puppet/ssl/private_keys/*")
        run("rm -f var/lib/puppet/ssl/certs/*")
        run("rm -rf builds/slave")
        run("echo localhost > etc/hostname")
        run("sed -i -e 's/127.0.0.1.*/127.0.0.1 localhost/g' etc/hosts")
        if args.public:
            # put rc.local
            put("%s/%s/etc/rc.local" % (AMI_CONFIGS_DIR, args.ami_config),
                "etc/rc.local", mirror_local_mode=True)
            run("rm -rf home/cltbld/.ssh")
            run("rm -rf root/.ssh/*")
            run("rm -rf builds/gapi.data")
            run("rm -rf builds/mock_mozilla/*/root/home/mock_mozilla")
        else:
            put("%s/setup_hostname.sh" % AMI_CONFIGS_DIR,
                "etc/setup_hostname.sh", mirror_local_mode=True)
            # replace puppet init with our script
            if ami_config["distro"] == "ubuntu":
                put("%s/setup_hostname.conf" % AMI_CONFIGS_DIR,
                    "etc/init/puppet.conf", mirror_local_mode=True)
            else:
                run("echo '/etc/setup_hostname.sh' > etc/init.d/puppet")
    # create snapshot2
    log.info('Terminating %s', host_instance)
    host_instance.terminate()
    wait_for_status(tmp_v, "status", "available", "update")
    log.info('Creating a snapshot')
    snap2 = tmp_v.create_snapshot(dated_target_name)
    wait_for_status(snap2, "status", "completed", "update")
    snap2.add_tag("Name", dated_target_name)

    bdm = BlockDeviceMapping()
    bdm[i.root_device_name] = BlockDeviceType(snapshot_id=snap2.id)

    log.info('Creating AMI')
    ami_id = conn.register_image(
        dated_target_name,
        dated_target_name,
        architecture=i.architecture,
        kernel_id=i.kernel,
        root_device_name=i.root_device_name,
        block_device_map=bdm,
    )
    log.info('Waiting...')
    while True:
        try:
            ami = conn.get_image(ami_id)
            ami.add_tag('Name', dated_target_name)
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


if __name__ == '__main__':
    main()
