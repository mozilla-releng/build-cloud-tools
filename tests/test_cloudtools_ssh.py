import unittest
import mock
import paramiko
from cloudtools.ssh import SSHClient


class TestSSHClient(unittest.TestCase):

    def test_policy(self):
        instance = mock.MagicMock()
        client = SSHClient(instance, "user", "key")
        self.assertIsInstance(client._policy, paramiko.MissingHostKeyPolicy)

    @mock.patch.object(paramiko.SSHClient, "connect")
    def test_connect(self, m_connect):
        instance = mock.Mock()
        instance.private_ip_address = "ip1"
        instance.tags = {"Name": "n1"}
        ssh_client = SSHClient(instance, "u1", "k1")
        ssh_client.connect()
        m_connect.assert_called_once_with(hostname="ip1", username="u1",
                                          key_filename="k1")

    @mock.patch.object(paramiko.SSHClient, "exec_command")
    def test_get_stdout(self, m_exec_command):
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
        self.assertEqual("out1", out)

    @mock.patch.object(paramiko.SSHClient, "connect")
    def test_connect_returns_None(self, m_connect):
        instance = mock.Mock()
        instance.private_ip_address = "ip1"
        instance.tags = {"Name": "n1"}
        ssh_client = SSHClient(instance, "u1", "k1")
        m_connect.side_effect = Exception("Ooops")
        self.assertIsNone(ssh_client.connect())

    @mock.patch.object(SSHClient, "get_stdout")
    def test_reboot_no_command(self, m_get_stdout):
        instance = mock.Mock()
        instance.private_ip_address = "ip1"
        instance.tags = {"Name": "n1", "moz-type": "t1"}
        ssh_client = SSHClient(instance, "u1", "k1")
        ssh_client.reboot()
        m_get_stdout.assert_called_once_with("sudo reboot")

    @mock.patch.object(SSHClient, "get_stdout")
    def test_reboot_with_command(self, m_get_stdout):
        instance = mock.Mock()
        instance.private_ip_address = "ip1"
        instance.tags = {"Name": "n1", "moz-type": "t1"}
        ssh_client = SSHClient(instance, "u1", "k1")
        ssh_client.reboot("cmd1")
        m_get_stdout.assert_called_once_with("cmd1")
