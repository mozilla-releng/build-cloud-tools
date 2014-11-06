import time
import sqlalchemy as sa
import re
import logging
from sqlalchemy.engine.reflection import Inspector
from collections import defaultdict

from .jacuzzi import get_allocated_slaves

log = logging.getLogger(__name__)


def find_pending(dburl):
    db = sa.create_engine(dburl)
    inspector = Inspector(db)
    # Newer buildbot has a "buildrequest_claims" table
    if "buildrequest_claims" in inspector.get_table_names():
        query = sa.text("""
        SELECT buildername, id FROM
               buildrequests WHERE
               complete=0 AND
               submitted_at > :yesterday AND
               submitted_at < :toonew AND
               (select count(brid) from buildrequest_claims
                       where brid=id) = 0""")
    # Older buildbot doesn't
    else:
        query = sa.text("""
        SELECT buildername, id FROM
               buildrequests WHERE
               complete=0 AND
               claimed_at=0 AND
               submitted_at > :yesterday AND
               submitted_at < :toonew""")

    result = db.execute(
        query,
        yesterday=time.time() - 86400,
        toonew=time.time() - 10
    )
    retval = result.fetchall()
    return retval


def map_builders(pending, builder_map):
    """Map pending builder names to instance types"""
    type_map = defaultdict(int)
    for pending_buildername, _ in pending:
        for buildername_exp, moz_instance_type in builder_map.items():
            if re.match(buildername_exp, pending_buildername):
                slaveset = get_allocated_slaves(pending_buildername)
                log.debug("%s instance type %s slaveset %s",
                          pending_buildername, moz_instance_type, slaveset)
                type_map[moz_instance_type, slaveset] += 1
                break
        else:
            log.debug("%s has pending jobs, but no instance types defined",
                      pending_buildername)
    return type_map
