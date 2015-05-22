import mock
import pytest

from cloudtools.aws.instance import create_block_device_mapping, \
    tag_ondemand_instance, pick_puppet_master


def test_no_ebs_on_instance_store():
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
    assert len(bdm) == 0
    assert first_disk_name == "/dev/sdb"


def test_bd_prefer_ami_size():
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
    assert bd.size == 20


def test_bd_should_be_not_smaller_than_ami():
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
    with pytest.raises(AssertionError):
        create_block_device_mapping(ami, device_map)


def test_bd_delete_on_termination():
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
    assert bd.delete_on_termination


def test_ephemeral_name():
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
    assert bd.ephemeral_name == "ephemeral0"


def test_bd_volume_type():
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
    assert bd.volume_type == "gp2"


def test_tag_ondemand_instance():
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


def test_pick_puppet_master():
    first_pick = pick_puppet_master(['m1', 'm2'])
    assert first_pick in ('m1', 'm2')
    second_pick = pick_puppet_master(['m1', 'm2'])
    assert second_pick is first_pick
    third_pick = pick_puppet_master(['m4', 'm5'])
    assert third_pick in ('m4', 'm5')
