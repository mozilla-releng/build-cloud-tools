# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from setuptools import setup

setup(
    name='build-cloud-tools',
    version='1.0.0',
    description='Mozilla Release Engineering tools for managing cloud infrastructure',
    author='Rail Aliiev',
    author_email='rail@mozilla.com',
    url='https://github.com/mozilla/build-cloud-tools',
    install_requires=[
        'Fabric==1.8.0',
        'MySQL-python==1.2.5',
        'PyYAML==3.11',
        'SQLAlchemy==0.8.3',
        'argparse>=1.2.1',
        'boto==2.27.0',
        'dnspython==1.12.0',
        'docopt==0.6.1',
        'ecdsa==0.10',
        'iso8601==0.1.10',
        'netaddr==0.7.12',
        'paramiko==1.12.0',
        'pycrypto==2.6.1',
        'repoze.lru==0.6',
        'requests==2.0.1',
        'simplejson==3.3.1',
        'ssh==1.8.0',
        'wsgiref==0.1.2',
        'cfn-pyplates',
        'IPy==0.81',
    ],
    extras_require={
        'test': [
            'coverage==3.7.1',
            'flake8',
            'mock',
            'nose',
            'pytest',
            'pytest-cov',
        ],
    },
    packages=[
        'cloudtools',
        'cloudtools.aws',
        'cloudtools.fabric',
        'cloudtools.scripts',
    ],
    entry_points={
        "console_scripts": [
            '%(s)s = cloudtools.scripts.%(s)s:main' % dict(s=s)
            for s in [
                'aws_create_instance',
                'get_spot_amis',
                'aws_clean_log_dir',
                'aws_create_ami',
                'aws_create_win_ami',
                'aws_deploy_stack',
                'aws_get_cloudtrail_logs',
                'aws_manage_instances',
                'aws_manage_routingtables',
                'aws_manage_securitygroups',
                'aws_manage_subnets',
                'aws_manage_users',
                'aws_process_cloudtrail_logs',
                'aws_publish_amis',
                'aws_sanity_checker',
                'aws_stop_idle',
                'aws_terminate_by_ami_id',
                'aws_watch_pending',
                'check_dns',
                'copy_ami',
                'delete_old_spot_amis',
                'ec22ip',
                'free_ips',
                'spot_sanity_check',
                'tag_spot_instances',
            ]
        ],
    },
    license='MPL2',
)
