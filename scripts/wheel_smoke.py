"""Smoke-test an installed PyRoxy distribution.

The script is meant to run from a directory that does not contain the source
tree, so ``import PyRoxy`` resolves to the installed wheel and the checks prove
that the packaged files (not just the checkout) are usable::

    python scripts/wheel_smoke.py

It exits with status 0 when every check passes and 1 otherwise.
"""

import sys
from pathlib import Path
from socket import AF_INET6

from PyRoxy import (CheckReport, CheckResult, GeoIP, Proxy, ProxyType,
                    ProxyUtiles)
from PyRoxy.Tools import Patterns


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    import PyRoxy

    package_dir = Path(PyRoxy.__file__).resolve().parent
    database = Path(GeoIP.database_path()).resolve()

    _check(package_dir.is_dir(),
           "package directory is missing: %s" % package_dir)
    _check(database.is_file(),
           "bundled GeoIP database is missing: %s" % database)
    _check(package_dir in database.parents,
           "GeoIP database is not inside the installed package: %s" % database)

    with Proxy("::1", 8080).open_socket() as sock:
        _check(sock.family == AF_INET6,
               "IPv6 proxy host did not use an AF_INET6 socket")

    _check(GeoIP.get("8.8.8.8")["country"]["iso_code"] == "US",
           "GeoIP lookup returned no US country for 8.8.8.8")
    _check(GeoIP.get("2001:4860:4860::8888")["country"]["iso_code"] == "US",
           "GeoIP lookup failed for an IPv6 address")

    proxy = Proxy.fromString("socks5h://user:pass@[2001:db8::1]:1080")
    _check(proxy is not None and proxy.remote_dns,
           "socks5h proxy was not parsed with remote DNS")
    _check(proxy.type == ProxyType.SOCKS5, "socks5h proxy has the wrong type")
    _check(Proxy.fromString(str(proxy)) == proxy,
           "proxy URL does not round-trip: %s" % proxy)
    _check(str(Proxy("fe80::1%eth0", 8080)) == "http://[fe80::1%25eth0]:8080",
           "scoped IPv6 literal was not serialised as RFC 6874")

    _check(Patterns.HostPort.match("[::1]:8080") is not None,
           "HostPort pattern does not accept bracketed IPv6")
    parsed = ProxyUtiles.parseAllIPPort(["[2001:db8::1]:1080"])
    _check({item.host for item in parsed} == {"2001:db8::1"},
           "parseAllIPPort dropped an IPv6 endpoint")

    result = CheckResult(proxy=Proxy("1.2.3.4", 8080),
                         url="https://example.com", success=True,
                         status_code=200, reason="OK", elapsed=0.1)
    _check(bool(result) and result.ok,
           "CheckResult did not report success")
    report = CheckReport([result], "https://example.com", 0.1)
    _check(report.working == {result.proxy},
           "CheckReport lost the working proxy")
    _check(report.asDict()["total"] == 1,
           "CheckReport.asDict reported the wrong total")

    metadata = GeoIP.metadata()
    print("PyRoxy", PyRoxy.__version__, "from", package_dir)
    print("GeoIP database:", database)
    print("Database type:", metadata.database_type)
    print("All wheel smoke checks passed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - CLI failure path
        print("wheel smoke check failed:", exc, file=sys.stderr)
        raise SystemExit(1) from exc
