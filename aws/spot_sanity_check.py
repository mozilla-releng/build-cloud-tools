#!/usr/bin/env python

import argparse
import json
import logging
import datetime

from boto.ec2 import connect_to_region
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, DateTime, Float, Integer, \
    create_engine, ForeignKey
from sqlalchemy.orm import validates, relationship, sessionmaker

log = logging.getLogger(__name__)
REGIONS = ['us-east-1', 'us-west-2']
Base = declarative_base()

CANCEL_STATUS_CODES = ["capacity-oversubscribed", "price-too-low",
                       "capacity-not-available"]
IGNORABLE_STATUS_CODES = CANCEL_STATUS_CODES + [
    "bad-parameters", "canceled-before-fulfillment", "fulfilled",
    "instance-terminated-by-price", "instance-terminated-by-user",
    "instance-terminated-capacity-oversubscribed", "pending-evaluation",
    "pending-fulfillment"]


def aws_time_to_gm(aws_time):
    t = datetime.datetime.strptime(aws_time[:-1] + "UTC",
                                   '%Y-%m-%dT%H:%M:%S.000%Z')
    return t


def stringify_dict(d):
    return json.dumps(d)


class SpotRequest(Base):
    __tablename__ = 'spot_requests'
    id = Column(String, primary_key=True)
    create_time = Column(DateTime)
    instance_id = Column(String)
    launched_availability_zone = Column(String)
    price = Column(Float)
    product_description = Column(String)
    region = Column(String)
    tags = Column(String)
    states = relationship("SpotState")
    statuses = relationship("SpotStatus")

    @validates('create_time')
    def convert_datetime(self, key, t):
        if isinstance(t, basestring):
            return aws_time_to_gm(t)
        else:
            return t

    @validates('tags')
    def stringify_tags(self, key, t):
        if isinstance(t, basestring):
            return t
        else:
            return stringify_dict(t)


class SpotState(Base):
    __tablename__ = "states"
    id = Column(Integer, primary_key=True)
    state = Column(String)
    seen = Column(DateTime)
    request_id = Column(String, ForeignKey('spot_requests.id'))

    def __init__(self, state, seen):
        self.state = state
        self.seen = seen

    @validates('seen')
    def convert_datetime(self, key, t):
        if isinstance(t, basestring):
            return aws_time_to_gm(t)
        else:
            return t


class SpotStatus(Base):
    __tablename__ = "statuses"
    id = Column(Integer, primary_key=True)
    code = Column(String)
    message = Column(String)
    update_time = Column(DateTime)
    request_id = Column(String, ForeignKey('spot_requests.id'))

    def __init__(self, code, message, update_time):
        self.code = code
        self.message = message
        self.update_time = update_time

    @validates('update_time')
    def convert_datetime(self, key, t):
        if isinstance(t, basestring):
            return aws_time_to_gm(t)
        else:
            return t


def cancel_low_price(conn):
    spot_requests = conn.get_all_spot_instance_requests() or []
    for req in spot_requests:
        if req.state in ["open", "failed"]:
            if req.status.code in CANCEL_STATUS_CODES:
                log.info("Cancelling request %s", req)
                req.cancel()
            elif req.status.code not in IGNORABLE_STATUS_CODES:
                log.error("Uknown status for request %s: %s", req,
                          req.status.code)


def update_spot_stats(conn, session):
    for req in conn.get_all_spot_instance_requests():
        r = session.query(SpotRequest).filter(SpotRequest.id == req.id).first()
        if r:
            if req.instance_id and r.instance_id != req.instance_id:
                log.debug("Update instance id %s", req.instance_id)
                r.instance_id = req.instance_id
            if req.launched_availability_zone and \
               r.launched_availability_zone != req.launched_availability_zone:
                r.launched_availability_zone = req.launched_availability_zone
            if r.tags != stringify_dict(req.tags):
                log.debug("Update tags: %s", req.tags)
                r.tags = req.tags

            if req.state not in [s.state for s in r.states]:
                log.debug("New state: %s", req.state)
                r.states.append(
                    SpotState(req.state, datetime.datetime.utcnow()))
            if req.status.code not in [s.code for s in r.statuses]:
                log.debug("New status: %s <%s> on %s", req.status.code,
                          req.status.message, req.status.update_time)
                r.statuses.append(
                    SpotStatus(req.status.code, req.status.message,
                               aws_time_to_gm(req.status.update_time)))
        else:
            log.debug("New request: %s", req.id)
            r = SpotRequest()
            r.id = req.id
            r.create_time = req.create_time
            r.instance_id = req.instance_id
            r.launched_availability_zone = req.launched_availability_zone
            r.price = req.price
            r.product_description = req.product_description
            r.region = req.region.name
            r.tags = req.tags
            r.states = [SpotState(req.state, datetime.datetime.utcnow())]
            r.statuses = [SpotStatus(req.status.code, req.status.message,
                                     aws_time_to_gm(req.status.update_time))]
            session.add(r)

        session.commit()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", "--secrets", type=argparse.FileType('r'),
                        help="optional file where secrets can be found")
    parser.add_argument("-r", "--region", dest="regions", action="append",
                        help="optional list of regions")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Supress logging messages")
    parser.add_argument("-d", "--db", default="spots.db")

    args = parser.parse_args()
    if args.secrets:
        secrets = json.load(args.secrets)
    else:
        secrets = None

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.quiet:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.WARNING)

    engine = create_engine('sqlite:///%s' % args.db)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    if not args.regions:
        args.regions = REGIONS
    for region in args.regions:
        if secrets:
            conn = connect_to_region(
                region,
                aws_access_key_id=secrets['aws_access_key_id'],
                aws_secret_access_key=secrets['aws_secret_access_key']
            )
        else:
            conn = connect_to_region(region)
        update_spot_stats(conn, session)
        cancel_low_price(conn)
