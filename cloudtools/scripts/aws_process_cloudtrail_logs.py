#!/usr/bin/env python
"""parses local cloudtrail logs and stores the results in the events dir"""

import argparse
import json
import os
from functools import partial
from multiprocessing import Pool

from cloudtools.fileutils import (mkdir_p, get_data_from_gz_file,
                                  get_data_from_json_file)

import logging
log = logging.getLogger(__name__)


def move_to_bad_logs(filename):
    """moves filename into BAD_LOGS dir"""
    bad_logs_dir = os.path.join(os.path.dirname(filename), '..', 'bad_logs')
    bad_logs_dir = os.path.abspath(bad_logs_dir)
    mkdir_p(bad_logs_dir)
    name = os.path.split(filename)[1]
    dst_file = os.path.join(bad_logs_dir, name)
    log.debug("%s => %s", filename, dst_file)
    os.rename(filename, dst_file)


def process_cloudtrail(discard_bad_logs, events_dir, filename):
    """extracts data from filename"""
    try:
        data = get_data_from_gz_file(filename)
        data = json.loads(data)
    except (ValueError, IOError):
        log.debug('cannot decode JSON from %s', filename)
        try:
            if discard_bad_logs:
                log.debug('%s is not valid, deleting it', filename)
                os.remove(filename)
            else:
                move_to_bad_logs(filename)
        except Exception:
            pass
        return

    log.debug('processing: %s', filename)
    for record in data['Records']:
        eventName = record['eventName']
        # just process stop events, skip StartInstances and TerminateInstances
        if eventName in ('StopInstances',):
            process_start_stop_record(events_dir, record)


def process_start_stop_record(events_dir, record):
    """process a start/stop/terminate row"""
    # this metod works with Start/Stop/Terminate events too
    time_ = record['eventTime']
    for item in record['requestParameters']['instancesSet']['items']:
        instanceId = item['instanceId']
        data = {'instances': instanceId,
                'eventName': record['eventName'],
                'eventTime': time_}
        write_to_json(events_dir, data)


def get_time_from_file(filename):
    """returns the eventTime from filename"""
    try:
        data = get_data_from_json_file(filename)
        return data['eventTime']
    except (ValueError, KeyError):
        log.debug('cannot get eventTime from json file: %s', filename)
        return None


def write_to_json(events_dir, data):
    """writes data to a json file; the file name is:
       <EVENTS_DIR>/event/instance,
       event and instance are provided by data itself"""
    event = data['eventName']
    instance = data['instances']
    filename = os.path.join(events_dir, event, instance)
    mkdir_p(os.path.dirname(filename))
    if not os.path.exists(filename):
        with open(filename, 'w') as f_out:
            json.dump(data, f_out)
    elif data['eventTime'] > get_time_from_file(filename):
        # replace old event with current one
        with open(filename, 'w') as f_out:
            json.dump(data, f_out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Increase logging verbosity")
    parser.add_argument("--cloudtrail-dir", metavar="cloudtrail_dir",
                        required=True,
                        help="Cloutrail logs directory")
    parser.add_argument("--events-dir", metavar="events_dir", required=True,
                        help="directory where events logs will be stored")
    parser.add_argument("--discard-bad-logs", action="store_true",
                        help="delete bad log files, if not provided, bad log "
                        "files will be moved into bad_logs_dir (next to "
                        "--event-dir)")
    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(message)s")
    if args.verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)

    # cloudtrails
    # get all the available cloudtrail files
    logging.debug("processing cloudtrail files")
    cloudtrail_files = []
    for dirpath, dirnames, filenames in os.walk(args.cloudtrail_dir):
        for log_file in filenames:
            cloudtrail_files.append(os.path.join(dirpath, log_file))

    # process_cloud_tails requires 3 arguments: discard_bad_logs,
    # events_dir and cloudtrail_file, maps() accepts only 2 parameters,
    # function name and an iterable, let's use partials
    process_cloudtrail_partial = partial(
        process_cloudtrail, args.discard_bad_logs, args.events_dir)
    pool = Pool()
    pool.map(process_cloudtrail_partial, cloudtrail_files)
    pool.close()
    pool.join()

if __name__ == '__main__':
    main()
