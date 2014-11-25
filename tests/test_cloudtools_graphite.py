import socket
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

    def test_add_destination(self):
        gl = get_graphite_logger()
        gl.add_destination("host0", 888, "prefix0")
        gl.add_destination("host9", 999, "prefix9")
        self.assertEqual(gl._servers,
                         [("host0", 888, "prefix0"),
                          ("host9", 999, "prefix9")])

    def test_single_server(self):
        gl = get_graphite_logger()
        gl.add("name", 44)
        gl.add_destination("host1", 1111, "prefix1")
        with mock.patch("socket.create_connection") as conn:
            gl.sendall()
            expected_calls = [
                mock.call(("host1", 1111), timeout=10),
            ]
            conn.assert_has_calls(expected_calls)

    def test_multiple_servers(self):
        gl = get_graphite_logger()
        gl.add_destination("host1", 1111, "prefix1")
        gl.add_destination("host2", 2222, "prefix2")
        gl.add("name", 44)
        with mock.patch("socket.create_connection") as conn:
            gl.sendall()
            expected_calls = [
                mock.call(("host1", 1111), timeout=10),
                mock.call(("host2", 2222), timeout=10),
            ]
            conn.assert_has_calls(expected_calls, any_order=True)

    def test_multiple_servers_sendall(self):
        gl = get_graphite_logger()
        gl.add_destination("host1", 1111, "prefix1")
        gl.add_destination("host2", 2222, "prefix2")
        with mock.patch("time.time") as m_time:
            m_time.return_value = 9999
            gl.add("name", 44)
        with mock.patch("socket.create_connection") as conn:
            sock = mock.MagicMock()
            conn.return_value = sock
            gl.sendall()
            expected_calls = [
                mock.call("prefix1.name 44 9999\n"),
                mock.call("prefix2.name 44 9999\n"),
            ]
            sock.sendall.assert_has_calls(expected_calls)

    @mock.patch.object(socket, "create_connection")
    def test_sendall_no_data(self, m_conn):
        gl = get_graphite_logger()
        gl.add_destination("host1", 1111, "prefix1")
        gl.sendall()
        self.assertEqual(m_conn.call_count, 0)

    @mock.patch.object(socket, "create_connection")
    def test_sendall_exception(self, m_create_connection):
        gl = get_graphite_logger()
        gl.add_destination("host1", 1111, "prefix1")
        gl.add("name", 44)
        m_create_connection.side_effect = Exception("oops")
        # No exception should be raised
        gl.sendall()
        self.assertDictEqual({}, gl._data)


class TestGenerateInstanceStats(unittest.TestCase):

    def test_running_only(self):
        i1 = mock.Mock()
        i1.state = "running"
        i2 = mock.Mock()
        i2.state = "stopped"
        for i in [i1, i2]:
            i.region.name = "r1"
            i.tags = {"moz-type": "m1"}
            i.instance_type = "i1"
            i.spot_instance_request_id = "r1"
            i.virtualization_type = "v1"
            i.root_device_type = "d1"
        with mock.patch("cloudtools.graphite._graphite_logger") as m_l:
            cloudtools.graphite.generate_instance_stats([i1, i2])
            m_l.add.assert_called_once_with("running.r1.m1.i1.spot.v1.d1",
                                            1, collect=True)
