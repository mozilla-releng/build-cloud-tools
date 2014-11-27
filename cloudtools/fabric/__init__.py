from fabric.api import env
import logging

log = logging.getLogger(__name__)


def setup_fabric_env(instance, user="root", abort_on_prompts=True,
                     disable_known_hosts=True, key_filename=None):
    env.abort_on_prompts = abort_on_prompts
    env.disable_known_hosts = disable_known_hosts
    if instance.vpc_id:
        log.info("Using private IP")
        env.host_string = instance.private_ip_address
    else:
        log.info("Using public DNS")
        env.host_string = instance.public_dns_name
    if user:  # pragma: no branch
        env.user = user
    if key_filename:  # pragma: no branch
        env.key_filename = key_filename
