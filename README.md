# PyRoxy

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE.md)

PyRoxy is a small Python library for parsing, validating, checking and
serializing HTTP, HTTPS, SOCKS4 and SOCKS5 proxies. It also includes a
GeoIP country lookup backed by a bundled GeoLite2 database.

## Installation

```bash
pip install .
```

For development and tests:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

## Quick start

```python
from PyRoxy import Proxy, ProxyType, ProxyUtiles, ProxyChecker

# Parse one proxy
proxy = Proxy.fromString("socks5://user:pass@127.0.0.1:1080")
print(proxy)                 # socks5://user:pass@127.0.0.1:1080
print(proxy.host, proxy.port, proxy.type)

# Parse a list, removing duplicates
proxies = ProxyUtiles.parseAll([
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8080",
    "socks5://user:pass@127.0.0.1:1080",
], ptype=ProxyType.HTTP)
print(len(proxies))

# Read a proxy list file (UTF-8 with or without BOM)
proxies = ProxyUtiles.readFromFile("proxies.txt")

# Check proxies concurrently (default concurrency is capped at 100)
working = ProxyChecker.checkAll(proxies, timeout=5)
```

## Accepted proxy formats

```text
http://host:port
https://host:port
socks4://host:port
socks4a://host:port
socks5://host:port
socks5h://host:port
http://user:password@host:port
socks5://user:password@host:port
host:port
host:port:user:password
user:password@host:port
http://[2001:db8::1]:8080
http://user:password@[2001:db8::1]:8080
```

Credentials are percent-encoded when a proxy is serialized. IPv6 hosts are
wrapped in brackets in URLs.

`socks4://` and `socks5://` resolve the destination locally, so an AAAA-only
name is sent as a 16-byte IPv6 address. `socks4a://` and `socks5h://` forward
the name and let the proxy resolve it. A `ProxyType` passed directly keeps the
historical PySocks default (remote resolution for SOCKS).

A proxy URL with no explicit port uses the URL scheme default:

| Scheme | Default port |
| --- | ---: |
| `http` | 80 |
| `https` | 443 |
| `socks4` / `socks4a` | 1080 |
| `socks5` / `socks5h` | 1080 |

`Proxy("host")` without a port uses the library default for the selected proxy
type: HTTP 8080, HTTPS 443, SOCKS4/SOCKS5 1080.

Hostnames are preserved instead of being resolved during construction. This
avoids blocking DNS calls and keeps the original proxy address. GeoIP country
information is only available for IP-literal hosts.

IPv6 is supported for proxy hosts and for HTTPS/HTTP CONNECT and SOCKS5
destinations. SOCKS4 cannot carry IPv6 destinations; PyRoxy raises a clear
error instead of sending an invalid SOCKS4 request. `parseAllIPPort` accepts
bracketed endpoints such as `[2001:db8::1]:1080`.

Scoped link-local literals such as `fe80::1%eth0` are accepted. The zone id is
percent-encoded as `%25` in serialized proxy URLs and in HTTP `CONNECT`
authorities (RFC 6874), and it never reaches the GeoIP lookup. SOCKS5 has no
field for a zone id, so a scoped SOCKS5 destination raises a clear error.

`https://` proxy URLs are handled by the checking API the way `requests`
handles them: TLS is established with the proxy before `CONNECT`. The
low-level `Proxy.open_socket()` path implements a plaintext HTTP `CONNECT`
handshake, so use an `http://` proxy with it.

## Checking proxies

`Proxy.check()` sends a real HTTP request through the proxy and returns
`True` only for a successful (`2xx` or `3xx`) response:

```python
proxy = Proxy.fromString("http://127.0.0.1:8080")
if proxy.check("https://example.com", timeout=5):
    print("proxy works")
```

`ProxyChecker.checkAll()` uses a bounded thread pool. The `threads` argument is
the maximum number of worker threads, not a per-proxy multiplier. It returns
the set of working proxies, which is also available as `report.working` in the
detailed API below.

### Detailed results

`Proxy.check_detailed()` returns a `CheckResult` with the status code, reason,
latency and, for transport failures, the exception type and message. It never
raises for network errors.

```python
result = proxy.check_detailed("https://example.com", timeout=5)
print(result.success, result.status_code, result.elapsed)
print(result.detail)   # "HTTP 200 OK" or the transport error
print(result.asDict())  # JSON-safe; proxy exported as host:port
```

Transport failures and `5xx` responses can be retried with exponential
backoff. Every attempt is kept, so a report shows what happened and when:

```python
result = proxy.check_detailed("https://example.com", retries=2)
print(result.attempt_count)
for attempt in result.attempts:
    print(attempt.number, attempt.status_code, attempt.elapsed,
          attempt.error_type)
```

`4xx` responses are not retried: they mean the proxy answered, just not the
way the check wanted (for example `407` when credentials are missing).

`ProxyChecker.checkAllDetailed()` returns a `CheckReport` that keeps the order
of the input, drops duplicates, and aggregates the run. It accepts the same
`retries` and `retry_backoff` options:

```python
report = ProxyChecker.checkAllDetailed(proxies, timeout=5, threads=50,
                                       retries=1)
print(report.summary())
print(report.working)        # same set as checkAll()
print(report.failed)
print(report.success_rate)   # 0.0 - 1.0
print(report.status_codes)   # Counter({200: 7, 502: 1})
print(report.errors)         # Counter({'ProxyError': 1})
print(report.to_json(indent=2))
```

`CheckReport` is iterable and indexable (`report[0]`), and `len(report)` is the
number of checks performed. Credentials are never included in `asDict()` or
`to_json()`; those export `host:port` only.

## GeoIP

The bundled database is loaded lazily on the first lookup:

```python
from PyRoxy import GeoIP

record = GeoIP.get("8.8.8.8")
print(record["country"]["iso_code"])
print(GeoIP.metadata().build_epoch)  # database build timestamp
```

The bundled GeoLite2-Country database was built on **2026-10-20**. GeoLite2
data is refreshed periodically, so update it when you need current country
information.

### Updating at runtime

```python
from PyRoxy import GeoIP

GeoIP.update()                       # always download a fresh database
GeoIP.ensure_current()               # download only when older than 30 days
GeoIP.ensure_current(max_age_days=7)

print(GeoIP.is_outdated())           # missing, invalid or older than 30 days
print(GeoIP.database_age())          # age of the local database in days
```

The download is validated as a GeoLite2-Country MMDB and replaces the
destination atomically, then the reader is reloaded. A failed download or an
invalid/truncated file leaves the existing database untouched and usable.
`ensure_current()` logs a warning and keeps the old database; pass
`raise_on_error=True` to surface the failure instead.

The update is never triggered implicitly by a lookup, so call it explicitly
(for example at application start-up) when freshness matters.

### Update destination

`update()` writes to the active database when it is writable (the bundled file
in a source checkout). When the package database lives in a read-only location
such as `site-packages`, it writes to a per-user cache instead:
`%LOCALAPPDATA%\PyRoxy` on Windows, `$XDG_CACHE_HOME/pyroxy` or
`~/.cache/pyroxy` elsewhere. A database in the cache takes precedence over the
bundled one at import time. Set `PYROXY_GEOIP_HOME` to choose another cache
directory, pass `path=`/`--output` for a specific file, or set
`PYROXY_GEOIP_DB` to make a specific file the active database.

### Updating from the command line

```bash
python -m PyRoxy.GeoIP.updater --check        # status; exit 1 when outdated
python -m PyRoxy.GeoIP.updater --if-outdated  # download only when stale
python -m PyRoxy.GeoIP.updater                # always download
```

`scripts/update_geoip.py` and the `pyroxy-geoip` console script installed with
the package are equivalent entry points.

Options: `--url`, `--output`, `--timeout`, `--retries`, `--sha256`,
`--max-age DAYS`, `--no-reload`, `--check` and `--if-outdated`. Exit status is
`0` for success/up to date, `1` when `--check` finds an outdated database, and
`2` for errors.

```bash
python scripts/update_geoip.py --url https://example.com/GeoLite2-Country.mmdb
export PYROXY_GEOIP_URL=https://example.com/GeoLite2-Country.mmdb
python -m PyRoxy.GeoIP.updater --if-outdated --max-age 7 --sha256 <hex>
```

Transient connection failures and 5xx responses are retried (two retries with
exponential backoff by default); 4xx responses and checksum mismatches fail
immediately.

To use another database without replacing the active file, set
`PYROXY_GEOIP_DB` or call `GeoIP.reload(path)`:

```bash
set PYROXY_GEOIP_DB=C:\data\GeoLite2-Country.mmdb   # Windows
export PYROXY_GEOIP_DB=/data/GeoLite2-Country.mmdb  # Linux/macOS
```

```python
GeoIP.reload("/data/GeoLite2-Country.mmdb")
print(GeoIP.database_path())
GeoIP.close()
```

The default download URL points to a public GeoLite2 mirror. If you have a
MaxMind account/licence, pass your own licensed download URL instead. GeoLite2
data is subject to the MaxMind GeoLite2 EULA; see
`PyRoxy/GeoIP/Sqlite/LICENSE.txt`.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m coverage run -m unittest discover -s tests -v
python -m coverage report        # fails below the 75% threshold
```

Coverage configuration lives in `pyproject.toml` (branch coverage over the
`PyRoxy` package). CI runs the suite on Linux, Windows and macOS, and a
separate job builds the sdist and wheel, verifies that the wheel contains the
bundled GeoIP database, installs it into a clean virtualenv and runs
`scripts/wheel_smoke.py` plus the full test suite against that installation.

To repeat the wheel check locally:

```bash
python -m build
python -m venv /tmp/pyroxy-wheel
/tmp/pyroxy-wheel/bin/pip install dist/*.whl
cd /tmp && /tmp/pyroxy-wheel/bin/python /path/to/PyRoxy/scripts/wheel_smoke.py
```

## License

MIT. See [LICENSE.md](LICENSE.md).
