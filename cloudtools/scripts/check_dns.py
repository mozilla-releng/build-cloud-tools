#!/usr/bin/env python
import argparse
import logging
from multiprocessing import Pool

from cloudtools.aws import get_aws_connection
from cloudtools.dns import get_ip, get_ptr, get_cname

log = logging.getLogger(__name__)


def check_A(args):
    fqdn, ip = args
    log.debug("Checking A %s %s", fqdn, ip)
    dns_ip = get_ip(fqdn)
    if dns_ip != ip:
        log.error("%s A entry %s doesn't match real ip %s", fqdn, dns_ip, ip)
    else:
        log.debug("%s A entry %s matches real ip %s", fqdn, dns_ip, ip)


def check_PTR(args):
    fqdn, ip = args
    log.debug("Checking PTR %s %s", fqdn, ip)
    ptr = get_ptr(ip)
    if ptr != fqdn:
        log.error("%s PTR entry %s doesn't match real ip %s", fqdn, ptr, ip)
    else:
        log.debug("%s PTR entry %s matches real ip %s", fqdn, ptr, ip)


def check_CNAME(args):
    fqdn, cname = args
    log.debug("Checking CNAME %s %s", fqdn, cname)
    real_cname = get_cname(cname)
    if fqdn != real_cname:
        log.error("%s should point to %s, but it points to %s", cname, fqdn,
                  real_cname)
    else:
        log.debug("%s properly points to %s", cname, fqdn)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--region", dest="region", required=True,
                        help="optional list of regions")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Supress logging messages")

    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    if args.verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.WARNING)

    conn = get_aws_connection(args.region)

    pool = Pool()
    res = conn.get_all_instances()
    instances = reduce(lambda a, b: a + b, [r.instances for r in res])
    a_checks = []
    ptr_checks = []
    cname_checks = []
    for i in instances:
        # TODO: ignore EB
        name = i.tags.get("Name")
        if not name:
            log.warning("%s has no Name tag, skipping...", i)
            continue
        fqdn = i.tags.get("FQDN")
        if not fqdn:
            log.warning("%s has no FQDN tag, skipping...", i)
            continue
        ip = i.private_ip_address
        if not ip:
            log.warning("%s no ip assigned, skipping...", i)
            continue
        cname = "%s.build.mozilla.org" % name
        a_checks.append([fqdn, ip])
        ptr_checks.append([fqdn, ip])
        cname_checks.append([fqdn, cname])
    pool.map(check_A, a_checks)
    pool.map(check_PTR, ptr_checks)
    pool.map(check_CNAME, cname_checks)
    pool.close()
    pool.join()


if __name__ == '__main__':
    main()
