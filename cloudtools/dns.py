from socket import gethostbyname, gaierror, gethostbyaddr, herror, \
    gethostbyname_ex


def get_ip(hostname):
    try:
        return gethostbyname(hostname)
    except gaierror:
        return None


def get_ptr(ip):
    try:
        return gethostbyaddr(ip)[0]
    except herror:
        return None


def get_cname(cname):
    try:
        return gethostbyname_ex(cname)[0]
    except:  # noqa: E722
        return None
