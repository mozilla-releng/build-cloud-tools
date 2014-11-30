import pytest
import mock

from cloudtools.aws import aws_get_fresh_instances, FRESH_INSTANCE_DELAY, \
    FRESH_INSTANCE_DELAY_JACUZZI, filter_instances_launched_since, \
    reduce_by_freshness, distribute_in_region, aws_get_running_instances, \
    jacuzzi_suffix, aws_filter_instances, filter_spot_instances, \
    filter_ondemand_instances, get_buildslave_instances


@pytest.fixture
def example_instances():
    i0 = mock.Mock(name="i0")
    i0.state = "running"
    i0.tags = {"moz-type": "m1", "moz-state": "ready"}
    i0.spot_instance_request_id = "r0"
    i0.launch_time = "2014-11-01T02:44:03.000Z"

    i1 = mock.Mock(name="i1")
    i1.state = "running"
    i1.tags = {"moz-type": "m2", "moz-state": "ready"}
    i1.spot_instance_request_id = "r1"
    i1.launch_time = "2013-11-01T02:44:03.000Z"

    i2 = mock.Mock(name="i2")
    i2.state = "stopped"
    i2.tags = {"moz-type": "m1", "moz-state": "ready"}
    i2.spot_instance_request_id = None
    i2.launch_time = "2013-11-01T02:44:03.000Z"

    i3 = mock.Mock(name="i3")
    i3.state = "running"
    i3.tags = {"moz-type": "m1", "moz-state": "not-ready"}
    i3.spot_instance_request_id = None
    i3.launch_time = "2014-11-01T02:44:03.000Z"

    i4 = mock.Mock(name="i4")
    i4.state = "running"
    i4.tags = {"moz-type": "m1", "moz-loaned-to": "dev1"}
    i4.spot_instance_request_id = "r1"
    i4.launch_time = "2014-11-01T02:44:03.000Z"

    return [i0, i1, i2, i3, i4]


def test_aws_get_fresh_instances():
    now_ts = 10 * 1000
    with mock.patch("time.time") as m_time:
        with mock.patch("cloudtools.aws.filter_instances_launched_since") \
                as m_fils:
            m_time.return_value = now_ts
            aws_get_fresh_instances(None, None)
            m_fils.assert_called_once_with(
                None, now_ts - FRESH_INSTANCE_DELAY)


def test_aws_get_fresh_jacuzzy_instances():
    now_ts = 10 * 1000
    with mock.patch("time.time") as m_time:
        with mock.patch("cloudtools.aws.filter_instances_launched_since") \
                as m_fils:
            m_time.return_value = now_ts
            aws_get_fresh_instances(None, "fake_slaveset")
            m_fils.assert_called_once_with(
                None, now_ts - FRESH_INSTANCE_DELAY_JACUZZI)


def test_filter_instances_launched_since(example_instances):
    e = example_instances
    # launch_time converted to UNIX time
    t1 = 1414809843
    since = t1 - FRESH_INSTANCE_DELAY + 10
    assert filter_instances_launched_since(e, since) == [e[0], e[3], e[4]]


def test_reduce_by_freshness():
    instances = []
    # reduce by 100% of fresh (10) and 10% of old (3), 13 in total
    # add 10 fresh instances, 100% to be reduces
    for i in range(10):
        i = mock.Mock()
        i.launch_time = "2014-11-01T02:44:03.000Z"
        instances.append(i)
    # add 20 not fresh instances, 10% to be reduced
    for i in range(30):
        i = mock.Mock()
        i.launch_time = "2013-11-01T02:44:03.000Z"
        instances.append(i)
    # fresh launch_time converted to UNIX time
    t_fresh = 1414809843 - FRESH_INSTANCE_DELAY + 10
    with mock.patch("time.time") as m_time:
        m_time.return_value = t_fresh
        assert reduce_by_freshness(100, instances, "meh_type", None) == 87


def test_reduce_by_freshness_jacuzzi():
    instances = []
    # reduce by 100% of fresh (10) and 0% of old
    for i in range(10):
        i = mock.Mock()
        i.launch_time = "2014-11-01T02:44:03.000Z"
        instances.append(i)
    for i in range(30):
        i = mock.Mock()
        i.launch_time = "2013-11-01T02:44:03.000Z"
        instances.append(i)
    # fresh launch_time converted to UNIX time
    t_fresh = 1414809843 - FRESH_INSTANCE_DELAY_JACUZZI + 10
    with mock.patch("time.time") as m_time:
        m_time.return_value = t_fresh
        assert reduce_by_freshness(
            100, instances, "meh_type", "fake_slaveset") == 90


def test_basic():
    count = 50
    regions = ["a", "b", "c"]
    region_priorities = {"a": 2, "b": 3, "c": 5}
    assert distribute_in_region(
        count, regions, region_priorities) == {"a": 10, "b": 15, "c": 25}


def test_zero():
    count = 50
    regions = ["a", "b", "c"]
    region_priorities = {"a": 2, "b": 3, "c": 0}
    assert distribute_in_region(
        count, regions, region_priorities) == {"a": 20, "b": 30, "c": 0}


def test_total():
    count = 6
    regions = ["a", "b", "c"]
    region_priorities = {"a": 20, "b": 30, "c": 0}
    assert sum(distribute_in_region(
        count, regions, region_priorities).values()) == count


def test_total_priority():
    count = 6
    regions = ["a", "b", "c"]
    region_priorities = {"a": 20, "b": 30, "c": 0}
    # make sure that rounding leftover is added to b (highest priority)
    assert distribute_in_region(count, regions, region_priorities) == \
        {"a": 2, "b": 4, "c": 0}


def test_regions_not_in_region_priorities():
    count = 10
    regions = ["a", "b", "c"]
    region_priorities = {"a": 20, "b": 30}
    assert distribute_in_region(count, regions, region_priorities) == \
        {"a": 4, "b": 6}


def test_intersection():
    count = 10
    regions = ["a", "b", "c"]
    region_priorities = {"a": 20, "d": 30}
    assert distribute_in_region(count, regions, region_priorities) == {"a": 10}


def test_jacuzzied():
    assert jacuzzi_suffix(slaveset=["a"]) == "jacuzzied"


def test_not_jacuzzied():
    assert jacuzzi_suffix(slaveset=None) == "not_jacuzzied"


def test_aws_get_running_instances(example_instances):
    e = example_instances
    assert aws_get_running_instances(e, "m1") == [e[0]]


def test_aws_filter_instances(example_instances):
    e = example_instances
    assert aws_filter_instances(e) == e[:-1]
    assert aws_filter_instances(e, state="running") == \
        e[:2] + [e[3]]
    assert aws_filter_instances(e, tags={"moz-type": "m2"}) == [e[1]]


def test_filter_spot_instances(example_instances):
    e = example_instances
    assert filter_spot_instances(e) == [e[0], e[1], e[4]]


def test_filter_ondemand_instances(example_instances):
    e = example_instances
    assert filter_ondemand_instances(e) == [e[2], e[3]]


@mock.patch("cloudtools.aws.get_aws_connection")
def test_get_buildslave_instances(conn, example_instances):
    e = example_instances
    conn.return_value.get_only_instances.return_value = e
    assert get_buildslave_instances("r", ["m1", "m2"]) == [e[0], e[1], e[2]]
    conn.return_value.get_only_instances.assert_called_once_with(
        filters={'tag:moz-state': 'ready',
                 'instance-state-name': 'running'})
