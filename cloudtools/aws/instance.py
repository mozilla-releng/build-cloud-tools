import uuid
import logging
import time
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from fabric.api import run, env, sudo
from . import wait_for_status

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
