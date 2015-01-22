# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


def nametag(name):
    return {'Key': 'Name', 'Value': name}


def sgcidr(cidr, proto, from_port, to_port=None):
    if to_port is None:
        to_port = from_port
    return {
        'CidrIp': cidr,
        'IpProtocol': proto,
        'FromPort': from_port,
        'ToPort': to_port,
    }
