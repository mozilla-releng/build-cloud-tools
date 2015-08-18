# build-cloud-tools [![Build Status](https://travis-ci.org/mozilla/build-cloud-tools.png)](https://travis-ci.org/mozilla/build-cloud-tools)

## Installation

### Fedora 22

    sudo dnf install mariadb-devel python-devel procmail
    mkdir ~/builds && cd ~/builds
    # or to replicate the aws-manager servers:
    # sudo mkdir /builds && sudo chown $(whoami) /builds && cd /builds
    sudo easy_install virtualenv
    virtualenv aws_manager
    git clone git@github.com:mozilla/build-cloud-tools.git aws_manager/cloud-tools
    source aws_manager/bin/activate
    pip install -e aws_manager/cloud-tools
