import unittest
import mock
from cloudtools.aws.instance import create_block_device_mapping, \
    tag_ondemand_instance


class TestBDM(unittest.TestCase):

    def test_no_ebs_on_instance_store(self):
        ami = mock.Mock()
        ami.root_device_type = "instance-store"
        device_map = {
            "/dev/xvda": {
                "delete_on_termination": True,
                "skip_resize": True,
                "volume_type": "gp2",
                "instance_dev": "/dev/xvda1"
            },
            "/dev/sdb": {
                "ephemeral_name": "ephemeral0",
                "instance_dev": "/dev/xvdb",
                "skip_resize": True,
                "delete_on_termination": False
            }
        }
        bdm = create_block_device_mapping(ami, device_map)
        first_disk_name, _ = bdm.popitem()
        self.assertEqual(len(bdm), 0)
        self.assertEqual(first_disk_name, "/dev/sdb")

    def test_bd_prefer_ami_size(self):
        ami = mock.MagicMock()
        ami.root_device_type = "ebs"
        ami.root_device_name = "/dev/xvda"
        ami.block_device_mapping["/dev/xvda"].size = 20
        ami.virtualization_type = "hvm"
        device_map = {
            "/dev/xvda": {
                "delete_on_termination": True,
                "skip_resize": True,
                "size": 30,  # will be ignored
                "volume_type": "gp2",
                "instance_dev": "/dev/xvda1"
            }
        }
        bdm = create_block_device_mapping(ami, device_map)
        _, bd = bdm.popitem()
        self.assertEqual(bd.size, 20)

    def test_bd_should_be_not_smaller_than_ami(self):
        ami = mock.MagicMock()
        ami.root_device_type = "ebs"
        ami.root_device_name = "/dev/xvda"
        ami.block_device_mapping["/dev/xvda"].size = 20
        ami.virtualization_type = "pv"
        device_map = {
            "/dev/xvda": {
                "delete_on_termination": True,
                "skip_resize": True,
                "size": 10,
                "volume_type": "gp2",
                "instance_dev": "/dev/xvda1"
            }
        }
        self.assertRaises(AssertionError, create_block_device_mapping, ami,
                          device_map)

    def test_bd_delete_on_termination(self):
        ami = mock.MagicMock()
        ami.root_device_type = "ebs"
        ami.root_device_name = "/dev/xvda"
        ami.block_device_mapping["/dev/xvda"].size = 20
        ami.virtualization_type = "hvm"
        device_map = {
            "/dev/xvda": {
                "skip_resize": True,
                "size": 30,  # will be ignored
                "volume_type": "gp2",
                "instance_dev": "/dev/xvda1"
            }
        }
        bdm = create_block_device_mapping(ami, device_map)
        _, bd = bdm.popitem()
        self.assertEqual(bd.delete_on_termination, True)

    def test_ephemeral_name(self):
        ami = mock.Mock()
        ami.root_device_type = "instance-store"
        device_map = {
            "/dev/sdb": {
                "ephemeral_name": "ephemeral0",
                "instance_dev": "/dev/xvdb",
                "skip_resize": True,
                "delete_on_termination": False
            }
        }
        bdm = create_block_device_mapping(ami, device_map)
        _, bd = bdm.popitem()
        self.assertEqual(bd.ephemeral_name, "ephemeral0")

    def test_bd_volume_type(self):
        ami = mock.MagicMock()
        ami.root_device_type = "ebs"
        ami.root_device_name = "/dev/xvda"
        ami.block_device_mapping["/dev/xvda"].size = 20
        ami.virtualization_type = "hvm"
        device_map = {
            "/dev/xvda": {
                "skip_resize": True,
                "size": 30,  # will be ignored
                "volume_type": "gp2",
                "instance_dev": "/dev/xvda1"
            }
        }
        bdm = create_block_device_mapping(ami, device_map)
        _, bd = bdm.popitem()
        self.assertEqual(bd.volume_type, "gp2")


class TestTagOndemandInstance(unittest.TestCase):

    def test_tag_ondemand_instance(self):
        instance = mock.MagicMock()
        name = "name1"
        fqdn = "FQDN1"
        moz_instance_type = "type1"
        with mock.patch("time.sleep"):
            tag_ondemand_instance(instance, name, fqdn, moz_instance_type)
        expected_calls = [
            mock.call.add_tag("Name", name),
            mock.call.add_tag("FQDN", fqdn),
            mock.call.add_tag("moz-type", moz_instance_type),
            mock.call.add_tag("moz-state", "ready"),
        ]
        instance.assert_has_calls(expected_calls, any_order=True)
