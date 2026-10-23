# PyRoxy
<<<<<<< HEAD

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
pip install -e ".[test]"
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

A proxy URL with no explicit port uses the URL scheme default:

| Scheme | Default port |
| --- | ---: |
| `http` | 80 |
| `https` | 443 |
| `socks4` | 1080 |
| `socks5` / `socks5h` | 1080 |

`Proxy("host")` without a port uses the library default for the selected proxy
type: HTTP 8080, HTTPS 443, SOCKS4/SOCKS5 1080.

Hostnames are preserved instead of being resolved during construction. This
avoids blocking DNS calls and keeps the original proxy address. GeoIP country
information is only available for IP-literal hosts.

IPv6 is supported for proxy hosts and for HTTPS/HTTP CONNECT and SOCKS5
destinations. SOCKS4 cannot carry IPv6 destinations; PyRoxy raises a clear
error instead of sending an invalid SOCKS4 request.

## Checking proxies

`Proxy.check()` sends a real HTTP request through the proxy and returns
`True` only for a successful (`2xx` or `3xx`) response:

```python
proxy = Proxy.fromString("http://127.0.0.1:8080")
if proxy.check("https://example.com", timeout=5):
    print("proxy works")
```

`ProxyChecker.checkAll()` uses a bounded thread pool. The `threads` argument is
the maximum number of worker threads, not a per-proxy multiplier.

## GeoIP

The bundled database is loaded lazily on the first lookup:

```python
from PyRoxy import GeoIP

record = GeoIP.get("8.8.8.8")
print(record["country"]["iso_code"])
print(GeoIP.metadata().build_epoch)  # database build timestamp
```

The bundled GeoLite2-Country database was built on **2026-10-20**. To refresh
it from a source checkout with the project script:

```bash
python scripts/update_geoip.py
```

The updater validates the MMDB file and atomically replaces the bundled
database. You can pass a custom download URL with `--url`, or set
`PYROXY_GEOIP_URL`:

```bash
python scripts/update_geoip.py --url https://example.com/GeoLite2-Country.mmdb
export PYROXY_GEOIP_URL=https://example.com/GeoLite2-Country.mmdb
```

To use another database without replacing the bundled file, set
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
python -m unittest discover -s tests -v
python -m compileall -q PyRoxy
```

## License

MIT. See [LICENSE.md](LICENSE.md).
=======
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
