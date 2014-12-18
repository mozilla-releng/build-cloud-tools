import mock
import socket

from cloudtools.dns import get_ip, get_ptr, get_cname


@mock.patch("cloudtools.dns.gethostbyname")
def test_get_ip(m):
    m.return_value = "a1"
    assert get_ip("h1") == "a1"


@mock.patch("cloudtools.dns.gethostbyname")
def test_get_ip_error(m):
    m.side_effect = socket.gaierror
    assert get_ip("h1") is None


@mock.patch("cloudtools.dns.gethostbyaddr")
def test_get_ptr(m):
    m.return_value = ["a1"]
    assert get_ptr("h1") == "a1"


@mock.patch("cloudtools.dns.gethostbyaddr")
def test_get_ptr_error(m):
    m.side_effect = socket.herror
    assert get_ptr("h1") is None


@mock.patch("cloudtools.dns.gethostbyname_ex")
def test_get_cname(m):
    m.return_value = ["a1"]
    assert get_cname("h1") == "a1"


@mock.patch("cloudtools.dns.gethostbyname_ex")
def test_get_cname_error(m):
    m.side_effect = Exception
    assert get_cname("h1") is None
