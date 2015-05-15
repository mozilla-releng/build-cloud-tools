import mock

from cloudtools.aws.vpc import get_subnet_id, ip_available, get_avail_subnet


def test_get_subnet_id():
    s1 = mock.Mock()
    s1.id = "id1"
    s1.cidr_block = "192.168.1.0/28"
    s2 = mock.Mock()
    s2.id = "id2"
    s2.cidr_block = "192.168.1.48/28"
    vpc = mock.Mock()
    vpc.get_all_subnets.return_value = [s1, s2]
    assert get_subnet_id(vpc, "192.168.1.50") == "id2"
    assert get_subnet_id(vpc, "192.168.1.150") is None


@mock.patch("cloudtools.aws.vpc.get_aws_connection")
def test_ip_available(c):
    i1 = mock.Mock()
    i1.private_ip_address = "a1"
    i2 = mock.Mock()
    i2.private_ip_address = "a2"
    e1 = mock.Mock()
    e1.private_ip_address = "a1"
    e2 = mock.Mock()
    e2.private_ip_address = "a3"
    c.return_value.get_only_instances.return_value = [i1, i2]
    c.return_value.get_all_network_interfaces.return_value = [e1, e2]
    assert ip_available("r1", "a5")
    assert not ip_available("r1", "a1")
    assert not ip_available("r1", "a3")


@mock.patch("cloudtools.aws.vpc.get_vpc")
def test_get_avail_subnet(vpc):
    s1 = mock.Mock()
    s1.available_ip_address_count = 10
    s1.availability_zone = "az1"
    s1.id = "id1"
    s2 = mock.Mock()
    s2.available_ip_address_count = 20
    s2.availability_zone = "az1"
    s2.id = "id2"
    s3 = mock.Mock()
    s3.available_ip_address_count = 30
    s3.availability_zone = "az2"
    s3.id = "id3"
    s4 = mock.Mock()
    s4.available_ip_address_count = 15
    s4.availability_zone = "az1"
    s4.id = "id4"
    s5 = mock.Mock()
    s5.available_ip_address_count = 17
    s5.availability_zone = "az1"
    s5.id = "id5"

    vpc.return_value.get_all_subnets.return_value = [s1, s2, s3, s4]
    assert get_avail_subnet(
        "r1", ["id1", "id2", "id3", "id4"], "az1") == "id2"
    vpc.return_value.get_all_subnets.assert_called_once_with(
        subnet_ids=("id1", "id2", "id3", "id4"))
    assert get_avail_subnet("r1", ["id44"], "azx") is None
