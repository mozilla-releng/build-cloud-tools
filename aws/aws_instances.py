"""aws_slave module"""

import json
import time
import logging
import urllib2
import socket
import calendar

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)
BUILDAPI_URL_JSON = "http://buildapi.pvt.build.mozilla.org/buildapi/recent/{slave_name}?format=json"
BUILDAPI_URL = "http://buildapi.pvt.build.mozilla.org/buildapi/recent/{slave_name}"


KNOWN_TYPES = ('puppetmaster', 'buildbot-master', 'dev-linux64', 'infra',
               'bld-linux64', 'try-linux64', 'tst-linux32', 'tst-linux64',
               'tst-win64', 'dev', 'servo-linux64', 'packager', 'vcssync',)

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
    "servo-linux64": 8,
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
    "servo-linux64": 72,
    "packager": "meh",
    "default": 24
}


def timedelta_to_time_string(timeout):
    """converts a time delta in seconds to Xd, Yh, Zm.
    If days == 0 it returns Yh, Zm"""
    from datetime import timedelta
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
    return calendar.timegm(time.strptime(launch_time[:19], '%Y-%m-%dT%H:%M:%S'))


class AWSInstance(object):
    """AWS AWSInstance"""
    def __init__(self, instance):
        self.instance = instance
        self.now = time.time()
        self.timeout = None
        self.last_job_endtime = None
        self.max_downtime = self._get_timeout(EXPECTED_MAX_UPTIME)
        self.max_uptime = self._get_timeout(EXPECTED_MAX_DOWNTIME)

    def _get_tag(self, tag_name, default=None):
        """returns tag_name tag from instance tags"""
        instance = self.instance
        return instance.tags.get(tag_name, default)

    def _get_timeout(self, timeouts):
        """returns the timeout in seconds from timeouts"""
        default_timeout = timeouts['default']
        instance_type = self.get_instance_type()
        timeout = timeouts.get(instance_type, default_timeout)
        if not timeout is 'meh':
            # timeout h -> s
            self.timeout = timeout * 3600
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

    def _get_uptime_timestamp(self):
        """returns the uptime in timestamp format"""
        instance = self.instance
        return time.time() - launch_time_to_epoch(instance.launch_time)

    def get_uptime(self):
        """returns the uptime in human readable format"""
        return timedelta_to_time_string(self._get_uptime_timestamp())

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
        """returns True is this instance is running for a long time
        this method must be implemented in subclasses"""
        return

    def is_running(self):
        """returns True if instance is running"""
        return self._get_state() == 'running'

    def is_stopped(self):
        """returns True if instance is stopped"""
        return self._get_state() == 'stopped'

    def is_loaned(self):
        """returns True if the slave is loaned"""
        return self._get_tag("moz-loaned-to")

    def is_stale(self):
        """returns True if a running instance is running for a longer time than
           expected (EXPECTED_MAX_UPTIME); for stopped instances, returns True
           if the instance is stopped for more than EXPECTED_MAX_DOWNTIME
           Loaned instances and moz-type with timeout == meh cannot be stale"""
        if self.is_loaned():
            # ignore loaned
            return False
        timeout = self._get_timeout(EXPECTED_MAX_UPTIME)
        if self.is_stopped():
            timeout = self._get_timeout(EXPECTED_MAX_DOWNTIME)
        if timeout == 'meh':
            return False
        return (self._get_uptime_timestamp() > timeout)

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
            status = "up for {0}".format(self.get_uptime())
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
            return ""
        return "{0} down for {1}".format(self.__repr__(), self.get_uptime())

    def running_message(self):
        """if the instance is running, it returns the following string:
           instance_name (instance id, region) up for X hours"""
        if self.is_stopped():
            return ""
        return "{0} up for {1}".format(self.__repr__(), self.get_uptime())

    def unknown_state_message(self):
        """returns the following message:
           Unknown state REASON
           where REASON is the content of moz-state tag
           it returns an empty sting is moz-state is 'ready'"""
        moz_state = self._get_moz_state()
        if moz_state == 'ready':
            moz_state = ""
        return moz_state

    def unknown_type_message(self):
        """returns the following message:
           Unknown type TYPE
           where TYPE is the content of moz-type tag
           it returns an empty sting is moz-state is 'ready'"""
        moz_type = self._get_moz_type()
        if moz_type in KNOWN_TYPES:
            moz_type = ""
        return moz_type

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

    def get_last_job_endtime(self, timeout=60):
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
                LOG.debug("max endtime: {endtime}".format(endtime=endtime))
            except TypeError:
                # somehow endtime is not set
                # ignore and use None
                pass
            except ValueError:
                # no jobs completed
                # ignore
                pass
        except urllib2.HTTPError as error:
            LOG.debug('http error {0}, url: {1}'.format(error.code, url))
        except urllib2.URLError as error:
            # in python < 2.7 this exception intercepts timeouts
            LOG.debug('url: {1} - error {1}'.format(url, error.reason))
        # in python > 2.7, timeout is a socket.timeout exception
        except socket.timeout as error:
            LOG.debug('connection timed out, url: {0}'.format(url))
        self.last_job_endtime = endtime
        return self.last_job_endtime

    def get_buildapi_url(self):
        """returns buildapi's url"""
        return BUILDAPI_URL.format(slave_name=self.get_name())

    def get_buildapi_json_url(self):
        """returns buildapi's json url"""
        return BUILDAPI_URL_JSON.format(slave_name=self.get_name())

    def is_long_running(self):
        """A slave is long running if it's running and the last job
           ended long time ago, more than expected uptime
           returns a tuple with Name, timeout, and timeout
           (in human readable format)"""
        if not self.is_running():
            return False
        delta = self.now - self.get_last_job_endtime()
        if delta > self.timeout:
            return True
        return False

    def longrunning_message(self):
        """if the slave is long runnring, it returns the following string:
           up for 147 hours BUILDAPI_INFO"""
        message = self.running_message()
        if message:
            message = "{0} ({1} since last build)".format(
                message, self.when_last_job_ended())
        return message
