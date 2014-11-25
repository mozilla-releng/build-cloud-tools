import unittest
from fabric.api import env
from cloudtools.fabric import setup_fabric_env


class TestSetupFabricEnv(unittest.TestCase):

    def test_generic(self):
        setup_fabric_env(host_string="h1", user="u1", key_filename="k1")
        self.assertTrue(env.abort_on_prompts)
        self.assertTrue(env.disable_known_hosts)
