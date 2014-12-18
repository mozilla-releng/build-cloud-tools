import mock
from fabric.api import env
from cloudtools.fabric import setup_fabric_env


def test_generic():
    instance = mock.Mock()
    setup_fabric_env(instance=instance, user="u2", key_filename="k1")
    assert env.abort_on_prompts
    assert env.disable_known_hosts


def test_vpc():
    instance = mock.Mock()
    instance.vpc_id = "vpc1"
    instance.private_ip_address = "a1"
    setup_fabric_env(instance=instance, user="u2", key_filename="k1")
    assert env.host_string == "a1"


def test_public():
    instance = mock.Mock()
    instance.vpc_id = None
    instance.public_dns_name = "a2"
    setup_fabric_env(instance=instance, user="u2", key_filename="k1")
    assert env.host_string == "a2"
