import mock
import boto
import pytest
import cloudtools.aws.spot
from cloudtools.aws.spot import (
    get_spot_requests_for_moztype, populate_spot_requests_cache,
    get_spot_request, get_instances_to_tag, copy_spot_request_tags,
    get_active_spot_requests, get_spot_instances, get_spot_requests
)


@mock.patch("cloudtools.aws.spot.get_aws_connection")
def test_no_reqest_ids(conn):
    populate_spot_requests_cache("region-a")
    conn.assert_has_calls(
        [mock.call().get_all_spot_instance_requests()])


@mock.patch("cloudtools.aws.spot.get_aws_connection")
def test_with_reqest_ids(conn):
    populate_spot_requests_cache("region-a", request_ids=[1, 2])
    conn.assert_has_calls(
        [mock.call().get_all_spot_instance_requests(request_ids=[1, 2])])


@mock.patch("cloudtools.aws.spot.get_aws_connection")
def test_invalid_request_id(conn):
    req = mock.Mock()
    req.id = "id-1"
    conn.return_value.get_all_spot_instance_requests.side_effect = \
        [boto.exception.EC2ResponseError("404", "reason"), [req]]
    populate_spot_requests_cache("r-1", ["id-1"])
    expected_calls = [
        mock.call(request_ids=["id-1"]),
        mock.call()
    ]
    conn.return_value.get_all_spot_instance_requests.assert_has_called(
        expected_calls)
    assert cloudtools.aws.spot._spot_requests == {("r-1", "id-1"): req}


@pytest.fixture
def setup():
    # reset the cahches
    reload(cloudtools.aws.spot)


@mock.patch("cloudtools.aws.spot.populate_spot_requests_cache")
def test_not_cached(m_populate_spot_requests_cache, setup):
    get_spot_request("region-1", "id-1")
    m_populate_spot_requests_cache.assert_called_once_with("region-1")


@mock.patch("cloudtools.aws.spot.get_aws_connection")
def test_cached(m_get_aws_conn, setup):
    req = mock.Mock()
    req.id = "id-1"
    m_get_aws_conn.return_value. \
        get_all_spot_instance_requests.return_value = [req]
    get_spot_request("region-1", "id-1")
    get_spot_request("region-1", "id-1")
    m_get_aws_conn.assert_called_once_with("region-1")


@mock.patch("cloudtools.aws.spot.get_spot_instances")
def test_no_tags(m_get_spot_instances):
    i = mock.Mock()
    i.tags = {}
    m_get_spot_instances.return_value = [i]
    assert cloudtools.aws.spot.get_instances_to_tag("r-1") == [i]


@mock.patch("cloudtools.aws.spot.get_spot_instances")
def test_all_tags(m_get_spot_instances):
    i = mock.Mock()
    i.tags = {"Name": "n1", "FQDN": "fqdn1", "moz-type": "t1",
              "moz-state": "s1"}
    m_get_spot_instances.return_value = [i]
    assert cloudtools.aws.spot.get_instances_to_tag("r-1") == []


@mock.patch("cloudtools.aws.spot.get_spot_instances")
def test_some_tags(m_get_spot_instances):
    i = mock.Mock()
    i.tags = {"Name1": "n1", "FQDN": "fqdn1", "moz-type": "t1",
              "moz-state": "s1"}
    m_get_spot_instances.return_value = [i]
    assert get_instances_to_tag("r-1") == [i]


@mock.patch("cloudtools.aws.spot.get_spot_request")
def test_copy_spot_request_tags(m_get_spot_request):
    req = mock.Mock()
    req.tags = {"t1": "v1", "t2": "v2", "t3": "v3"}
    m_get_spot_request.return_value = req
    i = mock.Mock()
    i.tags = {"t3": "v0", "t4": "vx"}
    i.id = "id1"
    copy_spot_request_tags(i)
    i.connection.create_tags.assert_called_once_with(
        ["id1"], {"t1": "v1", "t2": "v2", "moz-state": "ready"})


@mock.patch("cloudtools.aws.spot.get_spot_request")
def test_no_req(m_get_spot_request):
    m_get_spot_request.return_value = None
    i = mock.Mock()
    copy_spot_request_tags(i)
    i.connection.create_tags.assert_not_called()


@mock.patch("cloudtools.aws.spot.get_aws_connection")
def test_get_active_spot_requests(c):
    get_active_spot_requests("r1")
    c.assert_called_once_with("r1")
    c.return_value.get_all_spot_instance_requests.assert_called_once_with(
        filters={'state': ['open', 'active']})


@mock.patch("cloudtools.aws.spot.get_aws_connection")
def test_get_spot_instances(conn):
    get_spot_instances("r1")
    conn.return_value.get_only_instances.assert_called_once_with(
        filters={"instance-lifecycle": "spot",
                 "instance-state-name": "running"})


@mock.patch("cloudtools.aws.spot.get_aws_connection")
def test_state(conn):
    get_spot_instances("r1", "stopped")
    conn.return_value.get_only_instances.assert_called_once_with(
        filters={"instance-lifecycle": "spot",
                 "instance-state-name": "stopped"})


@mock.patch("cloudtools.aws.spot.get_active_spot_requests")
def test_get_spot_requests(m):
    r1 = mock.Mock()
    r1.launch_specification.instance_type = "t1"
    r1.launched_availability_zone = "az1"
    r2 = mock.Mock()
    r2.launch_specification.instance_type = "t2"
    r2.launched_availability_zone = "az1"
    r3 = mock.Mock()
    r3.launch_specification.instance_type = "t1"
    r3.launched_availability_zone = "az2"
    m.return_value = [r1, r2, r3]
    assert get_spot_requests("r1", "t1", "az1") == [r1]
    m.assert_called_once_with("r1")


@mock.patch("cloudtools.aws.spot.get_active_spot_requests")
def test_no_requests(m):
    m.return_value = None
    # Warning: make sure to specify different values to avoid LRU caching
    assert get_spot_requests("R1", "T1", "AZ1") == []


@mock.patch("cloudtools.aws.spot.get_active_spot_requests")
def test_generic(m):
    r1 = mock.Mock()
    r1.tags = {"moz-type": "tt1"}
    r2 = mock.Mock()
    r2.tags = {"moz-type": "tt2"}
    r3 = mock.Mock()
    m.return_value = [r1, r2, r3]
    assert get_spot_requests_for_moztype("r11", "tt1") == [r1]
