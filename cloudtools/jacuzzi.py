import logging
import requests

JACUZZI_BASE_URL = "http://jacuzzi-allocator.pub.build.mozilla.org/v1"
log = logging.getLogger(__name__)
_jacuzzi_allocated_cache = {}


def get_allocated_slaves(buildername):
    if buildername in _jacuzzi_allocated_cache:  # pragma: no branch
        return _jacuzzi_allocated_cache[buildername]

    if buildername is None:
        log.debug("getting set of all allocated slaves")
        r = requests.get("{0}/allocated/all".format(JACUZZI_BASE_URL),
                         timeout=5)
        _jacuzzi_allocated_cache[buildername] = frozenset(r.json()['machines'])
        return _jacuzzi_allocated_cache[buildername]

    log.debug("getting slaves allocated to %s", buildername)
    r = requests.get("{0}/builders/{1}".format(JACUZZI_BASE_URL, buildername),
                     timeout=5)
    # Handle 404 specially
    if r.status_code == 404:
        _jacuzzi_allocated_cache[buildername] = None
        return None
    _jacuzzi_allocated_cache[buildername] = frozenset(r.json()['machines'])
    return _jacuzzi_allocated_cache[buildername]


def filter_instances_by_slaveset(instances, slaveset):
    retval = []
    if not slaveset:
        allocated_slaves = get_allocated_slaves(None)

    for i in instances:
        if slaveset:
            if i.tags.get('Name') in slaveset:
                retval.append(i)
        elif i.tags.get('Name') not in allocated_slaves:
            retval.append(i)

    return retval
