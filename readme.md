# build-cloud-tools

## Installation

### Fedora 22

    sudo easy_install pip
    sudo pip install boto
    sudo dnf install mariadb-devel python-devel procmail
    git clone git@github.com:mozilla/build-cloud-tools.git cloud-tools
    cd cloud-tools
    sudo pip install -e .
