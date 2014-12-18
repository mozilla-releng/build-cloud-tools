import logging
import socket
from logging.handlers import SysLogHandler
from copy import copy


class ContextFilter(logging.Filter):
    """Adds hostname attribute to log record objects"""
    hostname = socket.gethostname()

    def filter(self, record):
        record.hostname = self.hostname
        return True


class SplitSysLogHandler(SysLogHandler):
    """Converts multiline log records into single line records"""

    def emit(self, record):
        if "\n" in record.getMessage():
            new_record = copy(record)
            for line in record.msg.splitlines():
                new_record.msg = line
                super(SplitSysLogHandler, self).emit(new_record)
        else:
            super(SplitSysLogHandler, self).emit(record)


def add_syslog_handler(logger, address, app="unknown", formatter=None):
    f = ContextFilter()
    logger.addFilter(f)
    syslog = SplitSysLogHandler(address=address)
    if not formatter:  # pragma: no branch
        formatter = logging.Formatter(
            "%(asctime)s %(hostname)s {app} %(message)s".format(app=app),
            datefmt='%Y-%m-%dT%H:%M:%S')
    syslog.setFormatter(formatter)
    logger.addHandler(syslog)
