import unittest
import mock
import socket

from cloudtools.dns import get_ip, get_ptr, get_cname


class TestGetIP(unittest.TestCase):

    def test_normal(self):
        with mock.patch("cloudtools.dns.gethostbyname") as m:
            m.return_value = "a1"
            self.assertEqual(get_ip("h1"), "a1")

    def test_error(self):
        with mock.patch("cloudtools.dns.gethostbyname") as m:
            m.side_effect = socket.gaierror
            self.assertIsNone(get_ip("h1"))


class TestGetPTR(unittest.TestCase):

    def test_normal(self):
        with mock.patch("cloudtools.dns.gethostbyaddr") as m:
            m.return_value = ["a1"]
            self.assertEqual(get_ptr("h1"), "a1")

    def test_error(self):
        with mock.patch("cloudtools.dns.gethostbyaddr") as m:
            m.side_effect = socket.herror
            self.assertIsNone(get_ptr("h1"))


class TestGetCNAME(unittest.TestCase):

    def test_normal(self):
        with mock.patch("cloudtools.dns.gethostbyname_ex") as m:
            m.return_value = ["a1"]
            self.assertEqual(get_cname("h1"), "a1")

    def test_error(self):
        with mock.patch("cloudtools.dns.gethostbyname_ex") as m:
            m.side_effect = Exception
            self.assertIsNone(get_cname("h1"))
