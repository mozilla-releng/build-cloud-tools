import logging
import paramiko
from .graphite import get_graphite_logger

log = logging.getLogger(__name__)
gr_log = get_graphite_logger()


class SSHClient(paramiko.SSHClient):

    def __init__(self, instance, username, key_filename, timeout=10):
        super(SSHClient, self).__init__()
        self.set_missing_host_key_policy(paramiko.MissingHostKeyPolicy())
        self.instance = instance
        self.username = username
        self.key_filename = key_filename
        self.ip = instance.private_ip_address
        self.name = instance.tags.get("Name")
        self.timeout = timeout

    def connect(self, *args, **kwargs):
        try:
            super(SSHClient, self).connect(*args, hostname=self.ip,
                                           username=self.username,
                                           key_filename=self.key_filename,
                                           timeout=self.timeout,
                                           **kwargs)
            return self
        except Exception:
            log.debug("Couldn't log into %s at %s", self.name, self.ip)
            return None

    def get_stdout(self, command):
        stdin, stdout, _ = self.exec_command(command)
        stdin.close()
        data = stdout.read()
        return data

    def reboot(self, command=None):
        if not command:
            command = "sudo reboot"
        self.get_stdout(command)
        gr_log.add(
            "rebooted.{}".format(self.instance.tags.get("moz-type", "none")),
            1, collect=True)
