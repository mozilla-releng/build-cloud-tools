#!/usr/bin/env python
import json
import uuid
import time

from random import choice
from fabric.api import run, put, env, local, settings
from boto.ec2 import connect_to_region
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType

import logging
log = logging.getLogger()


def create_master(conn, name, options, config):
    """Creates an AMI instance with the given name and config. The config must
    specify things like ami id."""

    # Make sure we don't request the same things twice
    token = str(uuid.uuid4())[:16]

    # Wait for the snapshot to be ready
    snap = conn.get_all_snapshots([config['repo_snapshot_id']])[0]
    while not snap.status == "completed":
        log.info("waiting for snapshot... (%s)", snap.status)
        snap.update()
        time.sleep(10)

    bdm = BlockDeviceMapping()
    bdm["/dev/sdh"] = BlockDeviceType(delete_on_termination=True,
                                      snapshot_id=config['repo_snapshot_id'])
    bdm["/dev/sda1"] = BlockDeviceType(delete_on_termination=True)

    subnet_id = choice(config.get('subnet_ids'))

    reservation = conn.run_instances(
        image_id=config['ami'],
        key_name=options.key_name,
        instance_type=config['instance_type'],
        client_token=token,
        subnet_id=subnet_id,
        security_group_ids=config.get('security_group_ids', []),
        block_device_map=bdm,
        disable_api_termination=True,
    )

    instance = reservation.instances[0]
    log.info("instance %s created, waiting to come up", instance)
    # Wait for the instance to come up
    while True:
        try:
            instance.update()
            if instance.state == 'running':
                break
            if instance.state == 'terminated':
                log.error("%s got terminated", instance)
                return
        except:
            log.exception("hit error waiting for instance to come up")
        time.sleep(10)
        log.info("waiting...")

    instance.add_tag('Name', name)
    instance.add_tag('moz-type', 'puppetmaster')

    instance.add_tag('moz-state', 'pending')
    puppetize(instance, name, options)


def puppetize(instance, name, options):
    env.host_string = instance.private_ip_address
    env.user = 'root'
    env.abort_on_prompts = True
    env.disable_known_hosts = True
    while True:
        try:
            run("date")
            run("test -d /data || mkdir /data")
            # TODO: Use label!
            run("test -d /data/lost+found || mount /dev/xvdl /data")
            run("echo '/dev/xvdl /data ext4 rw 0 0' >> /etc/fstab")
            break
        except:
            log.exception("waiting...")
            time.sleep(10)

    hostname = "{name}.srv.releng.aws-{region}.mozilla.com".format(
        name=name, region=options.region)
    run("hostname %s" % hostname)

    # Set up yum repos
    run('rm -f /etc/yum.repos.d/*')
    put('releng-public.repo', '/etc/yum.repos.d/releng-public.repo')
    run("sed -i 's,http://puppet/,file:///data/,g' /etc/yum.repos.d/releng-public.repo")
    run('yum clean all')

    # Get puppet installed
    run('yum install -q -y puppet mercurial')

    # /var/lib/puppet skel
    run("test -d /var/lib/puppet/ssl || mkdir -m 771 /var/lib/puppet/ssl")
    run("test -d /var/lib/puppet/ssl/ca || mkdir -m 755 /var/lib/puppet/ssl/ca")
    run("test -d /var/lib/puppet/ssl/certs || mkdir -m 755 /var/lib/puppet/ssl/certs")
    run("test -d /var/lib/puppet/ssl/public_keys || mkdir -m 755 /var/lib/puppet/ssl/public_keys")
    run("test -d /var/lib/puppet/ssl/private_keys || mkdir -m 750 /var/lib/puppet/ssl/private_keys")
    run("chown puppet:root /var/lib/puppet/ssl /var/lib/puppet/ssl/ca "
        "/var/lib/puppet/ssl/certs /var/lib/puppet/ssl/public_keys "
        "/var/lib/puppet/ssl/private_keys")

    # generate certs
    local("test -d certs.{h} || (mkdir certs.{h} && "
          "./ca-scripts/generate-cert.sh {h} certs.{h})".format(h=hostname))

    # put files to puppet dirs
    put("certs.%s/ca_crt.pem" % hostname, "/var/lib/puppet/ssl/ca/ca_pub.pem",
        mode=0644)
    put("certs.%s/ca_crt.pem" % hostname, "/var/lib/puppet/ssl/certs/ca.pem",
        mode=0644)
    put("certs.%s/ca_crl.pem" % hostname, "/var/lib/puppet/ssl/ca_crl.pem",
        mode=0644)
    put("certs.{h}/{h}.crt".format(h=hostname),
        "/var/lib/puppet/ssl/certs/%s.pem" % hostname, mode=0644)
    put("certs.{h}/{h}.key".format(h=hostname),
        "/var/lib/puppet/ssl/private_keys/%s.pem" % hostname, mode=0600)
    put("certs.{h}/{h}.pub".format(h=hostname),
        "/var/lib/puppet/ssl/public_keys/%s.pem" % hostname, mode=0644)

    run("if [ -e /etc/puppet/production ]; then "
        "cd /etc/puppet/production && "
        "hg pull -u; else "
        "hg clone http://hg.mozilla.org/build/puppet /etc/puppet/production; "
        "fi")
    put("secrets/*.csv", "/etc/puppet/production/manifests/extlookup/")

    with settings(warn_only=True):
        result = run("bash /etc/puppet/production/setup/masterize.sh")
        assert result.return_code in (0, 2)
    instance.add_tag('moz-state', 'ready')

    log.info("Got %s", instance.private_ip_address)
    log.info("rebooting")
    run("reboot")

# TODO: Move this into separate file(s)
configs = {
    "centos-6-x64-base": {
        "us-east-1": {
            "ami": "ami-049b1e6d",
            "subnet_id": ["subnet-33a98358", "subnet-35a9835e", " subnet-0aa98361"],
            "security_group_ids": ["sg-b36a84dc"],
            "instance_type": "m1.large",
            "repo_snapshot_id": "snap-e5d1eda1",  # This will be mounted at /data
        },
        "us-west-2": {
            "ami": "ami-16d15926",
            "subnet_id": ["subnet-b948dad0", "subnet-ba48dad3", "subnet-bf48dad6"],
            "security_group_ids": ["sg-4e2d3022"],
            "instance_type": "m1.large",
            "repo_snapshot_id": "snap-800dc8b8",  # This will be mounted at /data
        },
    },
}

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.set_defaults(
        config=None,
        region="us-west-1",
        secrets=None,
        key_name=None,
        action="create",
        instance=None,
    )
    parser.add_option("-c", "--config", dest="config", help="instance configuration to use")
    parser.add_option("-r", "--region", dest="region", help="region to use")
    parser.add_option("-k", "--secrets", dest="secrets", help="file where secrets can be found")
    parser.add_option("-s", "--key-name", dest="key_name", help="SSH key name")
    parser.add_option("-l", "--list", dest="action", action="store_const", const="list", help="list available configs")
    parser.add_option("-i", "--instance", dest="instance", help="puppetize existing instance")

    options, args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if options.action == "list":
        for config, regions in configs.items():
            print config, regions.keys()
        # All done!
        raise SystemExit(0)

    if not args:
        parser.error("at least one instance name is required")

    if not options.secrets:
        parser.error("secrets are required")

    if not options.key_name:
        parser.error("ssh key name is required")

    secrets = json.load(open(options.secrets))
    conn = connect_to_region(options.region,
            aws_access_key_id=secrets['aws_access_key_id'],
            aws_secret_access_key=secrets['aws_secret_access_key'],
            )

    if options.instance:
        instance = conn.get_all_instances([options.instance])[0].instances[0]
        puppetize(instance, args[0], options)
        raise SystemExit(0)

    if not options.config:
        parser.error("config name is required")

    try:
        config = configs[options.config][options.region]
    except KeyError:
        parser.error("unknown configuration; run with --list for list of supported configs")

    create_master(conn, args[0], options, config)
