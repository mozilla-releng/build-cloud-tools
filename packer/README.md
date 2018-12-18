# Building a CentOS 6.5 base AMI

Packer is a tool for building machine images.  Here we use it to build a CentOS 6.5 base AMI similar to the way `aws_create_ami.py` creates an AMI.

To install packer, see: [https://www.packer.io/intro/getting-started/install.html](https://www.packer.io/intro/getting-started/install.html)

### AWS credentials
Before you run packer, you must setup your AWS credentials in your shell environment.  This is identical to setting up credentials for use with AWS Cli.\
For configuring AWS credentials, see: [https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html)\
For setting up a session token using mfa, see: [https://github.com/mozilla-platform-ops/aws_mfa_scripts](https://github.com/mozilla-platform-ops/aws_mfa_scripts)

### Building the AMI
`cd packer; packer build centos65-hvm-64-base.json`

This will launch an ec2 instance in us-east-1, mount an EBS volume, install centos 6.5 to the EBS volume using the puppet again package repositories, and then register an AMI from that EBS volume.  The AMI will also be copied to us-west-2.
