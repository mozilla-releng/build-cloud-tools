import logging
import socket
import time

log = logging.getLogger(__name__)


class GraphiteLogger(object):
    # to be used by modules

    def __init__(self):
        self._data = {}
        self._servers = []

    def add_destination(self, host, port, prefix):
        self._servers.append((host, port, prefix))

    @staticmethod
    def _generate_line(prefix, name, value, timestamp):
        return "{prefix}.{name} {value} {timestamp}\n".format(
            prefix=prefix, name=name, value=value, timestamp=timestamp)

    def add(self, name, value, timestamp=None, collect=False):
        # graphite needs numbers, not strings
        try:
            float(value)
        except ValueError:
            log.error("Graphite accepts numeric values only, discarding...")
            return

        if not timestamp:
            timestamp = int(time.time())
        if collect and name in self._data:
            self._data[name] = (self._data[name][0] + value, timestamp)
        else:
            self._data[name] = (value, timestamp)

    def generate_data(self, prefix):
        data = []
        for name, (value, timestamp) in sorted(self._data.iteritems()):
            data.append(self._generate_line(prefix, name, value, timestamp))
        return "".join(data)

    def sendall(self):
        if not self._data:
            log.debug("Nothing to submit to graphite")
            return

        for host, port, prefix in self._servers:
            data = self.generate_data(prefix)
            log.debug("Graphite send: \n%s", data)
            try:
                log.debug("Connecting to graphite at %s:%s", host, port)
                sock = socket.create_connection((host, port), timeout=10)
                sock.sendall(data)
            except Exception:
                log.exception("Couldn't send graphite data to %s:%s", host,
                              port)
                log.warn("Ignoring all grapite submissions!")
        self._data = {}

_graphite_logger = GraphiteLogger()


def get_graphite_logger():
    global _graphite_logger
    return _graphite_logger


def generate_instance_stats(instances):
    l = _graphite_logger
    for i in instances:
        if i.state != "running":
            continue
        template_values = dict(
            region=i.region.name,
            moz_instance_type=i.tags.get("moz-type", "none"),
            instance_type=i.instance_type.replace(".", "-"),
            life_cycle_type="spot" if i.spot_instance_request_id else
            "ondemand",
            virtualization=i.virtualization_type,
            root_device_type=i.root_device_type
        )
        name = "running.{region}.{moz_instance_type}.{instance_type}" \
            ".{life_cycle_type}.{virtualization}.{root_device_type}"
        l.add(name.format(**template_values), 1, collect=True)
