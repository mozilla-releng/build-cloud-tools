#!/usr/bin/env python

import errno
import os
import logging
import gzip
import json
log = logging.getLogger(__name__)


def mkdir_p(dst_dir, exist_ok=True):
    """same as os.makedirs(path, exist_ok=True) in python > 3.2"""
    try:
        os.makedirs(dst_dir)
        log.debug('created %s', dst_dir)
    except OSError, error:
        if error.errno == errno.EEXIST and os.path.isdir(dst_dir) and exist_ok:
            pass
        else:
            log.error('cannot create %s, %s', dst_dir, error)
            raise


def get_data_from_gz_file(filename):
    log.debug(filename)
    try:
        with gzip.open(filename, 'rb') as f:
            return f.read()
    except IOError:
        log.debug('%s is not a valid gz file', filename)
        raise


def get_data_from_json_file(filename):
    """returns a json object from filename"""
    try:
        log.debug(filename)
        with open(filename, 'rb') as f:
            return json.loads(f.read())
    except ValueError:
        # discard log file if it's not a good json file
        # a log file can be broken because the download has been halted or the file
        # has been modified by the user
        log.debug('%s is not valid, deleting it', filename)
        raise
