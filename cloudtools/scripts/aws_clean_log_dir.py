#!/usr/bin/env python
"""Downloads the cloudtrail logs locally"""

import argparse
import datetime
import os
import shutil
import json
import logging

from cloudtools.aws import DEFAULT_REGIONS

log = logging.getLogger(__name__)


def delete_obsolete_logs(root_dir, reference_dir):
    """removes cloudtrail directories"""
    try:
        # cloudtrails directories are organized by year/month/day
        #
        # let's say we run the script with the follows parameters:
        # root dir      => /builds/aws_cloudtrail
        # reference_dir => /builds/aws_cloudtrail/2014
        # all the directories named /builds/aws_cloudtrail/<year>
        # where year is < 2014 will be deleted
        # this function is called 3 times with the follwing parametes:
        # e.g log_dir = /builds/aws_cloudtrail_logs
        # 1st run:
        #   root_dir = log_dir
        #   reference_dir = root_dir/year
        #   deletes obsolete logs from last year and before
        # 2nd run:
        #   root_dir = log_dir/year
        #   reference_dir = root_dir/year/month
        #   deletes obsolete logs from last month and before
        # 3rd run:
        #   root_dir = log_dir/year/month
        #   reference_dir = root_dir/year/month/day
        #   deletes obsolete logs from last day and before
        # where last day, last month, last year are today - numdays
        for directory in os.listdir(root_dir):
            full_path = os.path.join(root_dir, directory)
            if full_path < reference_dir:
                # current directory is < than reference dir
                log.debug("deleting obsolete cloudtrail file: %s",
                          full_path)
                shutil.rmtree(full_path)
    except OSError:
        # root dir does not exist, nothing to delete here
        pass


def delete_obsolete_json_file(json_file, numdays):
    """reads a json log and returns the eventTime"""
    try:
        with open(json_file) as json_f:
            data = json.loads(json_f.read())
            #  event time is stored as: 2014-04-07T18:09:23Z
            event = datetime.datetime.strptime(data['eventTime'],
                                               '%Y-%m-%dT%H:%M:%SZ')
            now = datetime.datetime.now()
            tdelta = now - event
            if tdelta.days > numdays:
                log.debug("deleting: %s (obsolete)" % json_file)
                os.remove(json_file)
    except TypeError:
        log.debug("deleting: %s (not valid)" % json_file)
        os.remove(json_file)
    except IOError:
        # file does not exist
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Increase logging verbosity")
    parser.add_argument("--cache-dir", metavar="cache_dir", required=True,
                        help="cache directory. Cloutrail logs are stored here")
    parser.add_argument("--s3-base-prefix", metavar="s3_base_dir", required=True,
                        help="root of s3 logs keys")
    parser.add_argument("--events-dir", metavar="events_dir", required=True,
                        help="root of the events directory")

    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(message)s")
    if args.verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)

    numdays = 60
    base = datetime.datetime.today()
    last_day_to_keep = base - datetime.timedelta(days=numdays)

    day = last_day_to_keep.strftime("%d")
    month = last_day_to_keep.strftime("%m")
    year = last_day_to_keep.strftime("%Y")

    cache_dir = args.cache_dir

    log.debug("deleting obsolete cloudtrail logs")
    for region in DEFAULT_REGIONS:
        aws_cloudtrail_logs = os.path.join(
            cache_dir, args.s3_base_prefix, region)

        # delete last years
        root_dir = aws_cloudtrail_logs
        reference_dir = os.path.join(aws_cloudtrail_logs, year)
        delete_obsolete_logs(root_dir, reference_dir)

        # delete last months
        root_dir = reference_dir
        reference_dir = os.path.join(reference_dir, month)
        delete_obsolete_logs(root_dir, reference_dir)

        # delete last days
        root_dir = reference_dir
        reference_dir = os.path.join(reference_dir, day)
        delete_obsolete_logs(root_dir, reference_dir)

    log.debug("deleting obsolete event files")
    for root, dirnames, filenames in os.walk(args.events_dir):
        for f in filenames:
            if f.startswith('i-'):
                # do not delete non instance files
                instance_event_file = os.path.join(root, f)
                delete_obsolete_json_file(instance_event_file, numdays)

if __name__ == '__main__':
    main()
