#!/usr/bin/env python
import boto.iam
import boto.exception
import os
import site
import json

site.addsitedir(os.path.join(os.path.dirname(__file__), ".."))


def get_users(conn=None):
    if not conn:
        conn = boto.iam.IAMConnection()
    users = conn.get_all_users("/")
    users = users['list_users_response']['list_users_result']['users']
    return users


def make_mfa_policy(user_name):
    return json.dumps({
        "Statement": [{
            "Action": ["iam:CreateVirtualMFADevice",
                       "iam:DeleteVirtualMFADevice",
                       "iam:ListVirtualMFADevices",
                       "iam:ResyncMFADevice",
                       "iam:DeactivateMFADevice"
                       ],
            "Resource": ["arn:aws:iam::*:mfa/%s" % user_name,
                         "arn:aws:iam::*:user/%s" % user_name,
                         ],
            "Effect": "Allow"
        }
        ]
    }, indent=2)


def enable_mfa(users):
    conn = boto.iam.IAMConnection()
    all_users = get_users(conn)
    for u in all_users:
        if u.user_name in users:
            user_name = u.user_name
            policy_json = make_mfa_policy(user_name)
            conn.put_user_policy(user_name, "manage_own_MFA", policy_json)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mfa", help="enable mfas for users", action="store_const", const="mfa", dest="action")
    parser.add_argument("--list", help="list users", action="store_const", const="list", dest="action")
    parser.add_argument("users", help="list of users to manage")

    args = parser.parse_args()

    if args.action == 'list':
        for u in get_users():
            print u.user_name

    elif args.action == "mfa":
        print "enabling MFA for", args.users
        enable_mfa(args.users)


if __name__ == '__main__':
    main()
