import mock
import cloudtools.jacuzzi
from cloudtools.jacuzzi import filter_instances_by_slaveset, \
    get_allocated_slaves


@mock.patch("cloudtools.jacuzzi.get_allocated_slaves")
def test_None(m):
    i1 = mock.Mock()
    i1.tags = {"Name": "name1"}
    i2 = mock.Mock()
    i2.tags = {"Name": "name2"}
    m.return_value = ["name2"]
    assert filter_instances_by_slaveset([i1, i2], None) == [i1]
    m.assert_called_once_with(None)


@mock.patch("cloudtools.jacuzzi.get_allocated_slaves")
def test_allocated(m):
    i1 = mock.Mock()
    i1.tags = {"Name": "name1"}
    i2 = mock.Mock()
    i2.tags = {"Name": "name2"}
    # ensure it's not called
    assert filter_instances_by_slaveset([i1, i2], ["name1"]) == [i1]
    assert m.mock_calls == []


@mock.patch("requests.get")
def test_cache(m):
    cloudtools.jacuzzi._jacuzzi_allocated_cache = {"b1": "ret1"}
    slaves = get_allocated_slaves("b1")
    assert slaves == "ret1"
    assert m.call_count == 0


@mock.patch("requests.get")
def test_caching_no_buildername(m):
    m.return_value.json.return_value = {"machines": ["m1", "m2"]}
    get_allocated_slaves(None)
    assert cloudtools.jacuzzi._jacuzzi_allocated_cache[None].issuperset(
        set(["m1", "m2"]))


@mock.patch("requests.get")
def test_no_buildername(m):
    m.return_value.json.return_value = {"machines": ["m1", "m2"]}
    assert get_allocated_slaves(None) == frozenset(["m1", "m2"])


@mock.patch("requests.get")
def test_404(m):
    m.return_value.status_code = 404
    assert get_allocated_slaves("b0") is None
    assert cloudtools.jacuzzi._jacuzzi_allocated_cache["b0"] is None


@mock.patch("requests.get")
def test_buildername(m):
    cloudtools.jacuzzi._jacuzzi_allocated_cache = {}
    m.return_value.json.return_value = {"machines": ["m1", "m2"]}
    get_allocated_slaves("b1")
    assert cloudtools.jacuzzi._jacuzzi_allocated_cache["b1"].issuperset(
        set(["m1", "m2"]))
    assert get_allocated_slaves("b1") == frozenset(["m1", "m2"])
