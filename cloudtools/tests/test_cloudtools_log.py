import mock
import logging
from cloudtools.log import ContextFilter, SplitSysLogHandler, \
    add_syslog_handler


def test_ContextFilter():
    record = logging.LogRecord("n1", logging.INFO, "p1", 1, "msg1", None, None)
    f = ContextFilter()
    assert not hasattr(record, "hostname")
    f.filter(record)
    assert hasattr(record, "hostname")


@mock.patch.object(logging.handlers.SysLogHandler, "emit")
def test_SplitSysLogHandler(syslog_emit):
    record1 = logging.LogRecord("n1", logging.INFO, "p1", 1, "msg1", None, None)
    record2 = logging.LogRecord("n1", logging.INFO, "p1", 1, "msg2\nmsg3", None,
                                None)
    lh = SplitSysLogHandler()
    lh.emit(record1)
    assert syslog_emit.call_count == 1
    lh.emit(record2)
    assert syslog_emit.call_count == 3


def test_add_syslog_handler():
    logger = logging.getLogger("test_add_syslog_handler1")
    add_syslog_handler(logger, ("localhost", 0), "app1")
    assert isinstance(logger.handlers[0], SplitSysLogHandler)
