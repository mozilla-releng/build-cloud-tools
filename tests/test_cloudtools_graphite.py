import unittest
import mock
import cloudtools.graphite
from cloudtools.graphite import get_graphite_logger


class TestGraphiteLogger(unittest.TestCase):

    def setUp(self):
        # need to reload the module to make the test data isolated
        reload(cloudtools.graphite)

    def test_add_no_timestamp(self):
        gl = get_graphite_logger()
        with mock.patch("time.time") as m_time:
            m_time.return_value = 1111
            gl.add("name", 55)
        self.assertDictEqual(gl._data, {"name": (55, 1111)})

    def test_add_mixed(self):
        gl = get_graphite_logger()
        with mock.patch("time.time") as m_time:
            m_time.return_value = 1111
            gl.add("name", 44)
            gl.add("name2", 55.66, 2222)
        self.assertDictEqual(
            gl._data,
            {"name": (44, 1111), "name2": (55.66, 2222)})

    def test_generate_data(self):
        gl = get_graphite_logger()
        with mock.patch("time.time") as m_time:
            m_time.return_value = 1111
            gl.add("name", 33)
            gl.add("name2", 66, 2222)
        expected_data = "prefix.mine.name 33 1111\n" \
            "prefix.mine.name2 66 2222\n"
        self.assertEqual(gl.generate_data("prefix.mine"), expected_data)

    def test__generate_line(self):
        gl = get_graphite_logger()
        self.assertEqual(
            gl._generate_line("my.prefix", "your.value", 55, 1111),
            "my.prefix.your.value 55 1111\n")

    def test_add_string(self):
        gl = get_graphite_logger()
        gl.add("name", "value")
        self.assertDictEqual(gl._data, {})

    def test_rewrite(self):
        gl = get_graphite_logger()
        gl.add("name", 44)
        gl.add("name", 55.66, 2222)
        self.assertDictEqual(gl._data, {"name": (55.66, 2222)})

    def test_collect(self):
        gl = get_graphite_logger()
        gl.add("name", 44, collect=True)
        gl.add("name", 55.66, 2222, collect=True)
        self.assertDictEqual(gl._data, {"name": (99.66, 2222)})
