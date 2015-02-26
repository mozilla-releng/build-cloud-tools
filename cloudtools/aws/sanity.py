"""aws_slave module"""

import os
import json
import time
import logging
import urllib2
import socket
import calendar
from datetime import timedelta
from cloudtools.aws import parse_aws_time

log = logging.getLogger(__name__)

BUILDAPI_URL_JSON = "http://buildapi.pvt.build.mozilla.org/buildapi/recent/" \
    "{slave_name}?format=json"
BUILDAPI_URL = "http://buildapi.pvt.build.mozilla.org/buildapi/recent/" \
    "{slave_name}"

SLAVE_TAGS = ('try-linux64', 'tst-linux32', 'tst-linux64', 'tst-emulator64',
              'bld-linux64')

KNOWN_TYPES = ('puppetmaster', 'buildbot-master', 'dev-linux64', 'infra',
               'bld-linux64', 'try-linux64', 'tst-linux32', 'tst-linux64',
               'tst-emulator64', 'tst-win64', 'dev', 'packager',
               'vcssync', "signing")

EXPECTED_MAX_UPTIME = {
    "puppetmaster": "meh",
    "buildbot-master": "meh",
    "dev": "meh",
    "infra": "meh",
    "vcssync": "meh",
    "dev-linux64": 8,
    "bld-linux64": 24,
    "try-linux64": 12,
    "tst-linux32": 12,
    "tst-linux64": 12,
    "tst-emulator64": 12,
    "default": 4
}

EXPECTED_MAX_DOWNTIME = {
    "puppetmaster": 0,
    "buildbot-master": 0,
    "dev": 0,
    "infra": 0,
    "vcssync": 0,
    "dev-linux64": 72,
    "bld-linux64": 72,
    "try-linux64": 72,
    "tst-linux32": 72,
    "tst-linux64": 72,
    "tst-emulator64": 72,
    "packager": "meh",
    "default": 24
}


def timedelta_to_time_string(timeout):
    """converts a time delta in seconds to Xd, Yh, Zm.
    If days == 0 it returns Yh, Zm"""
    if timeout == 'meh':
        return 'N/A'
    time_d = timedelta(seconds=timeout)
    days = time_d.days
    hours = time_d.seconds // 3600
    minutes = time_d.seconds // 60 % 60
    time_string = "{hours}h:{minutes}m".format(hours=hours, minutes=minutes)
    if days != 0:
        time_string = "{days}d {time_string}".format(days=days,
                                                     time_string=time_string)
    return time_string


def launch_time_to_epoch(launch_time):
    """converts a lunch_time into a timestamp"""
    return calendar.timegm(
        time.strptime(launch_time[:19], '%Y-%m-%dT%H:%M:%S'))


class AWSInstance(object):
    """AWS AWSInstance"""
    def __init__(self, instance, events_dir=None):
        self.instance = instance
        self.now = time.time()
        self.timeout = None
        self.last_job_endtime = None
        self.max_downtime = self._get_timeout(EXPECTED_MAX_DOWNTIME)
        self.max_uptime = self._get_timeout(EXPECTED_MAX_UPTIME)
        self.events_dir = events_dir

    def _get_tag(self, tag_name, default=None):
        """returns tag_name tag from instance tags"""
        instance = self.instance
        return instance.tags.get(tag_name, default)

    def _get_timeout(self, timeouts):
        """returns the timeout in seconds from timeouts"""
        default_timeout = timeouts['default']
        instance_type = self.get_instance_type()
        timeout = timeouts.get(instance_type, default_timeout)
        if timeout == "meh":
            # set the timeout in the future...
            self.timeout = self.now + 3600
            log.debug('{0}: timeout = {1}'.format(self.get_id(), self.timeout))
        else:
            self.timeout = int(timeout) * 3600
            log.debug('{0}: timeout = {1}'.format(self.get_id(), self.timeout))
        return self.timeout

    def _get_bug_string(self):
        """returns the bug string (moz-bug tag)"""
        return self._get_tag('moz-bug', 'an unknown bug')

    def _get_loaned_string(self):
        """returns the loaned to string (moz-bug tag)"""
        return self._get_tag('moz-loaned-to', 'unknown')

    def _get_state(self):
        """gets the current state from instance.state"""
        instance = self.instance
        return instance.state

    def _get_moz_state(self):
        """returns moz-state string (moz-state tag)"""
        return self._get_tag("moz-state")

    def _get_moz_type(self):
        """returns moz-type string (moz-type tag)"""
        return self._get_tag("moz-type")

    def _get_uptime_timestamp(self, default=None):
        """returns the uptime in timestamp format"""
        if self.instance.launch_time:
            return time.time() - launch_time_to_epoch(self.instance.launch_time)
        else:
            return default

    def get_uptime(self, default=None):
        """returns the uptime in human readable format"""
        if self.instance.launch_time:
            return timedelta_to_time_string(self._get_uptime_timestamp())
        else:
            return default

    def get_name(self):
        """retuns tag name"""
        return self._get_tag('Name')

    def get_instance_type(self):
        """returns the instance type (moz-type tag)"""
        return self._get_tag('moz-type')

    def get_id(self):
        """returns the id of the instance"""
        instance = self.instance
        return instance.id

    def get_region(self):
        """returns the current region"""
        instance = self.instance
        region = instance.region
        return region.name

    def is_long_running(self):
        """returns True is this instance is running for a long time"""
        if not self.is_running():
            return False
        if self.is_loaned():
            return False
        my_uptime = self._get_uptime_timestamp()
        return my_uptime > self.max_uptime

    def is_long_stopped(self):
        """returns True is this instance is running for a long time"""
        if self.is_running():
            return False
        if self.is_loaned():
            return False
        # get the uptime and assume it has been always down...
        my_downtime = self._get_uptime_timestamp()
        if self.events_dir:
            # ... unless we have the local logs
            my_downtime = self.get_stop_time_from_logs()
        return my_downtime > self.max_downtime

    def is_lazy(self):
        """returns True if this instance is on line for a while and it's not
           getting any jobs. It makes sense only if this machine is a slave.
           (must be implemented in the Slave class)"""
        return False

    def is_running(self):
        """returns True if instance is running"""
        return self._get_state() == 'running'

    def is_stopped(self):
        """returns True if instance is stopped"""
        return self._get_state() == 'stopped'

    def is_loaned(self):
        """returns True if the instance is loaned"""
        return self._get_tag("moz-loaned-to")

    def bad_type(self):
        """returns True if the instance type is not in KNOWN_TYPES"""
        bad_type = False
        if not self._get_moz_type() in KNOWN_TYPES:
            bad_type = True
        return bad_type

    def bad_state(self):
        """returns True if the instance type is not in KNOWN_TYPES"""
        bad_state = False
        if self._get_moz_state() != 'ready':
            bad_state = True
        return bad_state

    def loaned_message(self):
        """if the machine is loaned, returns the following message:
           Loaned to USER in BUG, STATUS
           where:
           USER is the content of moz-loaned-to tag,
           BUG is the content of moz-bug tag (unknown if N/A)
           STATUS is the uptime if the machine is running, 'stopped' otherwise
           if the machine is not loaned it returns an empty string"""
        # instance_name (instance id, region) followd by:
        # Loaned to xxxxxxx@mozilla.com in an unknown bug, stopped
        # or Loaned to xxxxxx@mozilla.com in bug xxx, up for x hours
        msg = ""
        if not self.is_loaned():
            return msg
        loaned_to = self._get_loaned_string()
        bug = self._get_bug_string()
        status = 'stopped'
        if not self.is_stopped():
            status = "up for {0}".format(self.get_uptime(default="unknown"))
        msg = "{me} Loaned to: {loaned_to}, in {bug}, {status}".format(
              me=self.__repr__(),
              loaned_to=loaned_to,
              bug=bug,
              status=status)
        return msg

    def stopped_message(self):
        """if the instance is stopped, it returns the following string:
           instance_name (instance id, region) down for X hours"""
        if not self.is_stopped():
            return None
        stop_time = self.get_stop_time_from_logs()
        if not stop_time:
            stop_time = self.get_uptime(default="unknown")
        else:
            stop_time = timedelta_to_time_string(stop_time)
        return "{0} down for {1}".format(self.__repr__(), stop_time)

    def running_message(self):
        """if the instance is running, it returns the following string:
           instance_name (instance id, region) up for X hours"""
        return "{0} up for {1}".format(self.__repr__(),
                                       self.get_uptime(default="unknown"))

    def unknown_state_message(self):
        """returns the following message:
           Unknown state REASON
           where REASON is the content of moz-state tag
           it returns an empty string is moz-state is 'ready'"""
        return "{0} ({1}, {2}) Unknown state: '{3}'".format(
            self.get_name(), self.get_id(), self.get_region(),
            self._get_moz_state())

    def unknown_type_message(self):
        """returns the following message:
           Unknown type TYPE
           where TYPE is the content of moz-type tag
           it returns an empty sting is moz-state is 'ready'"""
        return "{0} ({1}, {2}) Unknown type: '{2}'".format(
            self.get_name(), self.get_id(), self.get_region(),
            self._get_moz_type())

    def longrunning_message(self):
        """returns the running_message and appends (no info from buildapi)"""
        message = self.running_message()
        return " ".join([message, "(no info from buildapi)"])

    def _event_log_file(self, event):
        """returns the json file from the event directory"""
        if not self.events_dir:
            return
        instance_json = os.path.join(self.events_dir, event, self.get_id())
        if os.path.exists(instance_json):
            return instance_json
        return

    def _get_stop_log(self):
        """gets the cloudtrail log file about the last stop event for the
           current instance"""
        return self._event_log_file('StopInstances')

    def _get_start_log(self):
        """gets the cloudtrail log file about the last start event for the
           current instance"""
        # currently start events are not processed, so it always returns None
        return self._event_log_file('StartInstances')

    def _get_terminate_log(self):
        """gets the cloudtrail log file about the last terminate event for the
           current instance"""
        # currently start events are not processed, so it always returns None
        return self._event_log_file('TerminateInstances')

    def _get_time_from_json(self, json_file):
        """reads a json log and returns the eventTime"""
        try:
            with open(json_file) as json_f:
                data = json.loads(json_f.read())
                event = parse_aws_time(data['eventTime'])
                now = time.time()
                tdelta = (now - event)/3600
                return tdelta
        except TypeError:
            # json_file is None; aws_sanity_checker has no events-dir set
            pass
        except IOError:
            # file does not exist
            pass
        except ValueError:
            # bad json filex
            log.debug('JSON cannot load %s', json_file)

    def get_stop_time_from_logs(self):
        """time in hours since the last stop event. Returns None if the event
           does not exist"""
        stop_time = self._get_time_from_json(self._get_stop_log())
        if stop_time:
            # stop time could be None, when there are no stop events
            # stop time is in seconds, self.max_downtime in hours
            stop_time = stop_time * 3600
        return stop_time

    def __repr__(self):
        # returns:
        # try-linux64-ec2-044 (i-a8ccfb88, us-east-1)
        return "{name} ({instance_id}, {region})".format(
            name=self.get_name(),
            instance_id=self.get_id(),
            region=self.get_region())


class Slave(AWSInstance):
    """AWS slave"""
    def when_last_job_ended(self):
        """converts get_last_job_endtime into a human readable format"""
        last_job = self.get_last_job_endtime()
        if last_job and last_job != 'meh':
            delta = self.now - last_job
            last_job = timedelta_to_time_string(delta)
        return last_job

    def get_last_job_endtime(self, timeout=5):
        """gets the last endtime from buildapi"""
        # discard tmp and None instances as they are not on buildapi
        if self.get_name in ['tmp', None]:
            self.last_job_endtime = self.now
            return self.last_job_endtime
        if self.last_job_endtime:
            return self.last_job_endtime
        url = self.get_buildapi_json_url()
        endtime = self.now
        try:
            json_data = urllib2.urlopen(url, timeout=timeout)
            data = json.load(json_data)
            try:
                endtime = max([job['endtime'] for job in data])
                log.debug("{instance}: max endtime: {endtime}".format(
                    instance=self.get_id(), endtime=endtime))
            except TypeError:
                # somehow endtime is not set
                # ignore and use None
                log.debug("{instance}: endtime is not set".format(
                    instance=self.get_id()))
            except ValueError:
                # no jobs completed, ignore
                log.debug("{instance}: no jobs completed".format(
                    instance=self.get_id()))
        except urllib2.HTTPError as error:
            log.debug('http error {0}, url: {1}'.format(error.code, url))
        except urllib2.URLError as error:
            # in python < 2.7 this exception intercepts timeouts
            log.debug('url: {0} - error {1}'.format(url, error.reason))
        # in python > 2.7, timeout is a socket.timeout exception
        except socket.timeout as error:
            log.debug('connection timed out, url: {0}'.format(url))
        self.last_job_endtime = endtime
        return self.last_job_endtime

    def get_buildapi_url(self):
        """returns buildapi's url"""
        return BUILDAPI_URL.format(slave_name=self.get_name())

    def get_buildapi_json_url(self):
        """returns buildapi's json url"""
        return BUILDAPI_URL_JSON.format(slave_name=self.get_name())

    def is_lazy(self):
        """Checks if this instance is online for more than EXPECTED_MAX_UPTIME,
           and it's not taking jobs"""
        if not self.is_running():
            return False

        # get all the machines running for more than expected
        if not super(Slave, self).is_long_running():
            return False

        delta = self.now - self.get_last_job_endtime()
        if delta < self.max_uptime:
            # this instance got a job recently
            return False
        # no recent jobs, this machine is long running
        return True

    def longrunning_message(self):
        """if the slave is long runnring, it returns the following string:
           up for 147 hours BUILDAPI_INFO"""
        message = self.running_message()
        if message:
            message = "{0} ({1} since last build)".format(
                message, self.when_last_job_ended())
        return message


def aws_instance_factory(instance, events_dir):
    aws_instance = AWSInstance(instance)
    # is aws_instance a slave ?
    if aws_instance.get_instance_type() in SLAVE_TAGS:
        aws_instance = Slave(instance, events_dir)
    return aws_instance
