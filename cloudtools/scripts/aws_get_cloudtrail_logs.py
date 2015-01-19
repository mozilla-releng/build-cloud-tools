#!/usr/bin/env python
"""Downloads the cloudtrail logs locally"""

import argparse
import datetime
import boto
import os
import signal
from functools import partial
from multiprocessing import Pool
from cloudtools.aws import DEFAULT_REGIONS, get_s3_connection
from cloudtools.fileutils import mkdir_p

import logging

log = logging.getLogger(__name__)

LIMIT_MONTHS = 1  # 1 this month and the previous one
GET_CONTENTS_TO_FILENAME_TIMEOUT = 5  # get_contents_to_filename timeout in seconds


def get_keys(bucket, prefix):
    """gets s3 keys"""
    for i in bucket.list(prefix=prefix, delimiter="/"):
        if isinstance(i, boto.s3.prefix.Prefix):
            for i in get_keys(bucket, i.name):
                yield i
        else:
            yield i


def days_to_consider(limit=LIMIT_MONTHS):
    """limit logs to the current month + last calender month"""
    # it outputs, ['2014/01', '2013/12']
    now = datetime.datetime.now()
    start_date = datetime.datetime.now() - datetime.timedelta(LIMIT_MONTHS * 30)

    days = []
    days.append(start_date.strftime("%Y/%m"))
    days.append(now.strftime("%Y/%m"))
    return days


class TimeoutException(Exception):
    """Timeout exception used by _timeout()"""
    pass


def _timeout(*args):
    """callback function for signal.alarm, just rise an exception"""
    raise TimeoutException


def write_to_disk(cache_dir, key):
    """write key to disk in cache_dir"""
    dst = os.path.join(cache_dir, key.name)
    mkdir_p(os.path.dirname(dst))
    # key.get_contents_to_filename() is a blocking function,
    # if we try to download non existing files, it will hang here
    # it works only on unix systems
    signal.signal(signal.SIGALRM, _timeout)
    if not os.path.exists(dst):
        log.debug('downloading: {0}'.format(key.name))
        signal.alarm(GET_CONTENTS_TO_FILENAME_TIMEOUT)
        try:
            key.get_contents_to_filename(dst)
        except TimeoutException:
            log.debug('timeout downloading: {0}'.format(key.name))
    else:
        # file is already cached locally
        log.debug('{0} is already cached'.format(key.name))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Increase logging verbosity")
    parser.add_argument("--cache-dir", metavar="cache_dir", required=True,
                        help="cache directory. Cloutrail logs are stored here")
    parser.add_argument("--s3-base-prefix", metavar="s3_base_dir", required=True,
                        help="root of s3 logs keys")
    parser.add_argument("--s3-bucket", metavar="s3_bucket", required=True,
                        help="s3 bucket")

    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(message)s")
    if args.verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)

    conn = get_s3_connection()
    bucket = conn.get_bucket(args.s3_bucket)

    prefixes = []
    log.debug("finding all AWSLog keys")
    for region in DEFAULT_REGIONS:
        for day in days_to_consider():
            prefixes.append("{0}/{1}/{2}".format(args.s3_base_prefix, region,
                            day))

    write_to_disk_partial = partial(write_to_disk, args.cache_dir)

    for prefix in prefixes:
        keys = get_keys(bucket, prefix)
        pool = Pool()
        pool.map(write_to_disk_partial, keys)
        pool.close()
        pool.join()

if __name__ == '__main__':
    main()
