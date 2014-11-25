from fabric.api import env


def setup_fabric_env(host_string=None, user="root", abort_on_prompts=True,
                     disable_known_hosts=True, key_filename=None):
    env.abort_on_prompts = abort_on_prompts
    env.disable_known_hosts = disable_known_hosts
    if host_string:  # pragma: no branch
        env.host_string = host_string
    if user:  # pragma: no branch
        env.user = user
    if key_filename:  # pragma: no branch
        env.key_filename = key_filename
