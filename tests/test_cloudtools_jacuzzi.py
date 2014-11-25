import unittest
import mock
import cloudtools.jacuzzi
from cloudtools.jacuzzi import filter_instances_by_slaveset, \
    get_allocated_slaves


class TestFilterSlaveset(unittest.TestCase):

    def test_None(self):

        i1 = mock.Mock()
        i1.tags = {"Name": "name1"}
        i2 = mock.Mock()
        i2.tags = {"Name": "name2"}

        with mock.patch("cloudtools.jacuzzi.get_allocated_slaves") as mock_gas:
            mock_gas.return_value = ["name2"]
            self.assertEqual(filter_instances_by_slaveset([i1, i2], None),
                             [i1])
            mock_gas.assert_called_once_with(None)

    def test_allocated(self):
        i1 = mock.Mock()
        i1.tags = {"Name": "name1"}
        i2 = mock.Mock()
        i2.tags = {"Name": "name2"}

        with mock.patch("cloudtools.jacuzzi.get_allocated_slaves") as mock_gas:
            # ensure it's not called
            self.assertEqual(filter_instances_by_slaveset([i1, i2], ["name1"]),
                             [i1])
            self.assertEquals(mock_gas.mock_calls, [])


class TestGetAllocatedSlaves(unittest.TestCase):

    @mock.patch("requests.get")
    def test_cache(self, m_get):
        cloudtools.jacuzzi._jacuzzi_allocated_cache = {"b1": "ret1"}
        slaves = get_allocated_slaves("b1")
        self.assertEqual(slaves, "ret1")
        self.assertEqual(m_get.call_count, 0)

    @mock.patch("requests.get")
    def test_caching_no_buildername(self, m_get):
        m_get.return_value.json.return_value = {"machines": ["m1", "m2"]}
        get_allocated_slaves(None)
        self.assertTrue(
            cloudtools.jacuzzi._jacuzzi_allocated_cache[None].issuperset(
                set(["m1", "m2"])))

    @mock.patch("requests.get")
    def test_no_buildername(self, m_get):
        m_get.return_value.json.return_value = {"machines": ["m1", "m2"]}
        self.assertEqual(get_allocated_slaves(None), frozenset(["m1", "m2"]))

    @mock.patch("requests.get")
    def test_404(self, m_get):
        m_get.return_value.status_code = 404
        self.assertEqual(get_allocated_slaves("b1"), None)
        self.assertIsNone(cloudtools.jacuzzi._jacuzzi_allocated_cache["b1"])

    @mock.patch("requests.get")
    def test_buildername(self, m_get):
        cloudtools.jacuzzi._jacuzzi_allocated_cache = {}
        m_get.return_value.json.return_value = {"machines": ["m1", "m2"]}
        get_allocated_slaves("b1")
        self.assertTrue(
            cloudtools.jacuzzi._jacuzzi_allocated_cache["b1"].issuperset(
                set(["m1", "m2"])))
        self.assertEqual(get_allocated_slaves("b1"), frozenset(["m1", "m2"]))
