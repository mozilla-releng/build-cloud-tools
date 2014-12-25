import mock
import paramiko
from cloudtools.ssh import SSHClient


def test_policy():
    instance = mock.MagicMock()
    client = SSHClient(instance, "user", "key")
    assert isinstance(client._policy, paramiko.MissingHostKeyPolicy)


@mock.patch.object(paramiko.SSHClient, "connect")
def test_connect(m_connect):
    instance = mock.Mock()
    instance.private_ip_address = "ip1"
    instance.tags = {"Name": "n1"}
    ssh_client = SSHClient(instance, "u1", "k1")
    ssh_client.connect()
    m_connect.assert_called_once_with(hostname="ip1", username="u1",
                                      key_filename="k1", timeout=10)


@mock.patch.object(paramiko.SSHClient, "exec_command")
def test_get_stdout(m_exec_command):
    instance = mock.Mock()
    instance.private_ip_address = "ip1"
    instance.tags = {"Name": "n1"}
    ssh_client = SSHClient(instance, "u1", "k1")
    stdin, stdout = mock.Mock(), mock.Mock()
    stdout.read.return_value = "out1"
    m_exec_command.return_value = stdin, stdout, None
    out = ssh_client.get_stdout("my command")
    m_exec_command.assert_called_once_with("my command")
    stdin.close.assert_called_once_with()
    stdout.read.assert_called_once_with()
    assert out == "out1"


@mock.patch.object(paramiko.SSHClient, "connect")
def test_connect_returns_None(m_connect):
    instance = mock.Mock()
    instance.private_ip_address = "ip1"
    instance.tags = {"Name": "n1"}
    ssh_client = SSHClient(instance, "u1", "k1")
    m_connect.side_effect = Exception("Ooops")
    assert ssh_client.connect() is None


@mock.patch.object(SSHClient, "get_stdout")
def test_reboot_no_command(m_get_stdout):
    instance = mock.Mock()
    instance.private_ip_address = "ip1"
    instance.tags = {"Name": "n1", "moz-type": "t1"}
    ssh_client = SSHClient(instance, "u1", "k1")
    ssh_client.reboot()
    m_get_stdout.assert_called_once_with("sudo reboot")


@mock.patch.object(SSHClient, "get_stdout")
def test_reboot_with_command(m_get_stdout):
    instance = mock.Mock()
    instance.private_ip_address = "ip1"
    instance.tags = {"Name": "n1", "moz-type": "t1"}
    ssh_client = SSHClient(instance, "u1", "k1")
    ssh_client.reboot("cmd1")
    m_get_stdout.assert_called_once_with("cmd1")
