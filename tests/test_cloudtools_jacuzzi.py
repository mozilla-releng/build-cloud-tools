import unittest
import mock
from cloudtools.jacuzzi import filter_instances_by_slaveset


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
