import unittest
import mock
from fabric.api import env
from cloudtools.fabric import setup_fabric_env


class TestSetupFabricEnv(unittest.TestCase):

    def test_generic(self):
        instance = mock.Mock()
        setup_fabric_env(instance=instance, user="u2", key_filename="k1")
        self.assertTrue(env.abort_on_prompts)
        self.assertTrue(env.disable_known_hosts)

    def test_vpc(self):
        instance = mock.Mock()
        instance.vpc_id = "vpc1"
        instance.private_ip_address = "a1"
        setup_fabric_env(instance=instance, user="u2", key_filename="k1")
        self.assertEqual(env.host_string, "a1")

    def test_public(self):
        instance = mock.Mock()
        instance.vpc_id = None
        instance.public_dns_name = "a2"
        setup_fabric_env(instance=instance, user="u2", key_filename="k1")
        self.assertEqual(env.host_string, "a2")
