import unittest
import mock
from cloudtools.slavealloc import slave_moz_type, get_classified_slaves


class TestSlaveMozType(unittest.TestCase):

    def test_bld_linux64(self):
        slave = {
            "bitlength": "64",
            "environment": "prod",
            "distro": "centos6-mock",
            "purpose": "build",
            "trustlevel": "core"
        }
        self.assertEqual(slave_moz_type(slave), "bld-linux64")

    def test_try_linux64(self):
        slave = {
            "bitlength": "64",
            "environment": "prod",
            "distro": "centos6-mock",
            "purpose": "build",
            "trustlevel": "try"
        }
        self.assertEqual(slave_moz_type(slave), "try-linux64")

    def test_tst_linux64(self):
        slave = {
            "bitlength": "64",
            "environment": "prod",
            "distro": "ubuntu64",
            "purpose": "tests",
            "speed": "m1.medium",
            "trustlevel": "try"
        }
        self.assertEqual(slave_moz_type(slave), "tst-linux64")

    def test_tst_linux32(self):
        slave = {
            "bitlength": "32",
            "environment": "prod",
            "distro": "ubuntu32",
            "purpose": "tests",
            "speed": "m1.medium",
            "trustlevel": "try"
        }
        self.assertEqual(slave_moz_type(slave), "tst-linux32")

    def test_tst_emulator64(self):
        slave = {
            "bitlength": "64",
            "environment": "prod",
            "distro": "ubuntu64",
            "purpose": "tests",
            "speed": "c3.xlarge",
            "trustlevel": "try"
        }
        self.assertEqual(slave_moz_type(slave), "tst-emulator64")


class TestClassification(unittest.TestCase):

    def tearDown(self):
        # A dirty hack to invalidate @lru_cache decorated function mocked in
        # the tests below
        get_classified_slaves.func_closure[0].cell_contents.clear()

    @staticmethod
    def get_example_data():
        j = [
            {"name": "slave-spot-1", "datacenter": "us-west-2",
             "enabled": True, "bitlength": "64", "environment": "prod",
             "distro": "centos6-mock", "purpose": "build",
             "trustlevel": "core"},
            {"name": "slave-1", "datacenter": "us-west-2",
             "enabled": True, "bitlength": "64", "environment": "prod",
             "distro": "centos6-mock", "purpose": "build",
             "trustlevel": "core"},
            {"name": "slave-2", "datacenter": "us-west-2",
             "enabled": False, "bitlength": "64", "environment": "prod",
             "distro": "centos6-mock", "purpose": "build",
             "trustlevel": "core"},
            # Bad puprpose
            {"name": "slave-spot-2", "datacenter": "us-west-2",
             "enabled": True, "bitlength": "64", "environment": "prod",
             "distro": "ubuntu64", "purpose": "build",
             "trustlevel": "core"},
            {"name": "slave-spot-3", "datacenter": "us-west-2",
             "enabled": True, "bitlength": "64", "environment": "prod",
             "distro": "ubuntu64", "purpose": "tests", "speed": "c3.xlarge",
             "trustlevel": "try"},
            # Duplicate
            {"name": "slave-spot-3", "datacenter": "us-west-2",
             "enabled": True, "bitlength": "64", "environment": "prod",
             "distro": "ubuntu64", "purpose": "tests", "speed": "c3.xlarge",
             "trustlevel": "try"},
            # bad datacenter
            {"name": "slave-spot-5", "missing_datacenter": "us-west-2",
             "enabled": True, "bitlength": "64", "environment": "prod",
             "distro": "ubuntu64", "purpose": "tests", "speed": "c3.xlarge",
             "trustlevel": "try"},
        ]
        return j

    def test_bld_spot(self):
        with mock.patch("cloudtools.slavealloc.get_slaves_json") as gsj:
            gsj.return_value = self.get_example_data()
            slaves = get_classified_slaves(True)
        self.assertDictEqual(
            slaves,
            {'bld-linux64': {'us-west-2': set(['slave-spot-1'])},
             'tst-emulator64': {'us-west-2': set(['slave-spot-3'])},
             })

    def test_bld_ondemand(self):
        with mock.patch("cloudtools.slavealloc.get_slaves_json") as gsj:
            gsj.return_value = self.get_example_data()
            slaves = get_classified_slaves(False)
        self.assertDictEqual(
            slaves,
            {'bld-linux64': {'us-west-2': set(['slave-1'])}})
