#!/usr/bin/env python
import boto.iam
import boto.exception
import json
import random


def make_password(n=8):
    uppers = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    lowers = "abcdefghijklmnopqrstuvwxyz"
    nums = "0123456789"
    special = "`-=~!@#$%^&*()_+[]\{}|;':\",./<>?"
    all = uppers + lowers + nums + special

    pw = list(random.choice(uppers) + random.choice(lowers) + random.choice(nums) + random.choice(special) + ''.join(random.choice(all) for _ in range(n - 4)))
    random.shuffle(pw)
    return ''.join(pw)


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
                       "iam:EnableMFADevice",
                       "iam:CreateAccessKey",
                       "iam:UpdateLoginProfile",
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


def create_users(users):
    conn = boto.iam.IAMConnection()
    all_users = get_users(conn)
    remote_users = {u.user_name for u in all_users}
    for u in users:
        if u in remote_users:
            print u, "already exists"
            continue

        iam_user = conn.create_user(u)
        try:
            password = make_password()
            conn.create_login_profile(u, password)
            conn.add_user_to_group('RelEng', iam_user.user_name)
            conn.put_user_policy(iam_user.user_name, 'manage_own_MFA', make_mfa_policy(iam_user.user_name))
            print "username:", iam_user.user_name, "password:", password
        except Exception:
            conn.delete_user(u)
            print "deleted", u, password
            raise


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mfa", help="enable mfas for users", action="store_const", const="mfa", dest="action")
    parser.add_argument("--list", help="list users", action="store_const", const="list", dest="action")
    parser.add_argument("--create", help="create user", action="store_const", const="create", dest="action")
    parser.add_argument("users", help="list of users to manage", nargs='+')

    args = parser.parse_args()

    if args.action == 'list':
        for u in get_users():
            print u.user_name

    elif args.action == "mfa":
        print "enabling MFA for", args.users
        enable_mfa(args.users)

    elif args.action == 'create':
        print "creating users", args.users
        create_users(args.users)


if __name__ == '__main__':
    main()
