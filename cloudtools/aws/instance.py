import uuid
import logging
import time
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from boto.exception import BotoServerError, EC2ResponseError
from fabric.api import run, env, sudo
from . import wait_for_status, get_user_data_tmpl

log = logging.getLogger(__name__)


def run_instance(connection, instance_name, config, key_name, user='root',
                 key_filename=None, subnet_id=None):
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
        subnet_id=subnet_id,
    )

    instance = reservation.instances[0]
    log.info("instance %s created, waiting to come up", instance)
    # Wait for the instance to come up
    wait_for_status(instance, "state", "running", "update")
    if subnet_id:
        env.host_string = instance.private_ip_address
    else:
        env.host_string = instance.public_dns_name
    env.user = user
    env.abort_on_prompts = True
    env.disable_known_hosts = True
    if key_filename:
        env.key_filename = key_filename

    # wait until the instance is responsive
    while True:
        try:
            if run('date').succeeded:
                break
        except:
            log.debug('hit error waiting for instance to come up')
        time.sleep(10)

    instance.add_tag('Name', instance_name)
    # Overwrite root's limited authorized_keys
    if user != 'root':
        sudo("cp -f ~%s/.ssh/authorized_keys "
             "/root/.ssh/authorized_keys" % user)
        sudo("sed -i -e '/PermitRootLogin/d' "
             "-e '$ a PermitRootLogin without-password' /etc/ssh/sshd_config")
        sudo("service sshd restart || service ssh restart")
        sudo("sleep 20")
    return instance


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


def user_data_from_template(moz_instance_type, fqdn):
    user_data = get_user_data_tmpl(moz_instance_type)
    if user_data:
        user_data = user_data.format(fqdn=fqdn,
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
