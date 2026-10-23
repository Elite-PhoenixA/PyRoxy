<<<<<<< HEAD
import logging
from base64 import b64encode
=======
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from enum import IntEnum, auto
from ipaddress import ip_address
<<<<<<< HEAD
from re import compile as _compile
from socket import (socket, SOCK_STREAM, AF_INET, AF_INET6, AF_UNSPEC,
                    getaddrinfo)
from ssl import SSLSocket
from typing import AnyStr, Set, Collection, Any, Iterable
from urllib.parse import quote, unquote, urlsplit

import requests
from requests import RequestException
from socks import (socksocket, SOCKS4, SOCKS5, HTTP, GeneralProxyError,
                   HTTPError)
=======
from multiprocessing import cpu_count
from pathlib import Path
from socket import socket, SOCK_STREAM, AF_INET, gethostbyname
from typing import AnyStr, Set, Collection, Any

from socks import socksocket, SOCKS4, SOCKS5, HTTP
from yarl import URL
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d

from PyRoxy import GeoIP, Tools
from PyRoxy.Exceptions import ProxyInvalidHost, ProxyInvalidPort, ProxyParseError
from PyRoxy.Tools import Patterns

<<<<<<< HEAD
__version__ = "1.0b7"
__auther__ = "MH_ProDev"
__all__ = ["ProxyUtiles", "ProxyType", "ProxySocket", "ProxyChecker", "Proxy"]

logger = logging.getLogger(__name__)

=======
__version__ = "1.0b5"
__auther__ = "MH_ProDev"
__all__ = ["ProxyUtiles", "ProxyType", "ProxySocket", "ProxyChecker", "Proxy"]

>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d

class ProxyType(IntEnum):
    HTTP = auto()
    HTTPS = auto()
    SOCKS4 = auto()
    SOCKS5 = auto()

    def asPySocksType(self):
        return SOCKS5 if self == ProxyType.SOCKS5 else \
            SOCKS4 if self == ProxyType.SOCKS4 else \
                HTTP

    @staticmethod
    def stringToProxyType(n: str):
<<<<<<< HEAD
        if n is None:
            return ProxyType.HTTP
        value = str(n).strip().lower()
        if value in _SCHEME_TO_TYPE:
            return _SCHEME_TO_TYPE[value]
        if value.isdigit():
            number = int(value)
            if number == 5:
                return ProxyType.SOCKS5
            if number == 4:
                return ProxyType.SOCKS4
        return ProxyType.HTTP


_DEFAULT_PORTS = {
    ProxyType.HTTP: 8080,
    ProxyType.HTTPS: 443,
    ProxyType.SOCKS4: 1080,
    ProxyType.SOCKS5: 1080,
}

_SCHEME_DEFAULT_PORTS = {
    ProxyType.HTTP: 80,
    ProxyType.HTTPS: 443,
    ProxyType.SOCKS4: 1080,
    ProxyType.SOCKS5: 1080,
}

_SCHEME_TO_TYPE = {
    "http": ProxyType.HTTP,
    "https": ProxyType.HTTPS,
    "socks4": ProxyType.SOCKS4,
    "socks5": ProxyType.SOCKS5,
    "socks5h": ProxyType.SOCKS5,
}

_HOST_LABEL = _compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


# noinspection PyShadowingBuiltins
=======
        return (ProxyType.SOCKS5 if n.lower() == "socks5" else
                ProxyType.SOCKS4 if n.lower() == "socks4" else ProxyType.HTTP
                ) if not (n.isdigit()) else (
                    ProxyType.SOCKS5 if int(n) == 5 else
                    ProxyType.SOCKS4 if int(n) == 4 else ProxyType.HTTP)


>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
class Proxy(object):
    user: Any
    password: Any
    country: Any
    port: int
    type: ProxyType
    host: AnyStr

    def __init__(self,
                 host: str,
                 port: int = 0,
                 proxy_type: ProxyType = ProxyType.HTTP,
                 user=None,
                 password=None):
<<<<<<< HEAD
        if isinstance(proxy_type, str):
            mapped = _SCHEME_TO_TYPE.get(proxy_type.strip().lower())
            if mapped is None:
                raise ValueError("Unknown proxy type: %r" % proxy_type)
            proxy_type = mapped
        elif not isinstance(proxy_type, ProxyType):
            try:
                proxy_type = ProxyType(proxy_type)
            except (TypeError, ValueError):
                raise TypeError("proxy_type must be a ProxyType")

        host = self._normalizeHost(host)
        port = self._normalizePort(port, proxy_type)

        self.host = host
        self.type = proxy_type
        self.port = port
        self.country = None
        if self._isIP(host):
            record = GeoIP.get(host)
            if record:
                info = record.get("country") or \
                    record.get("registered_country") or {}
                self.country = info.get("iso_code")

        if user is not None:
            user = str(user)
        if password is not None:
            password = str(password)
        self.user = user or None
        self.password = password or None

    def __eq__(self, other):
        if not isinstance(other, Proxy):
            return NotImplemented
        return (self.type, self.host, self.port, self.user,
                self.password) == (other.type, other.host, other.port,
                                   other.user, other.password)

    def __hash__(self):
        return hash((self.type, self.host, self.port, self.user,
                     self.password))

    def _formatHost(self):
        return "[%s]" % self.host if ":" in self.host else self.host

    def __str__(self):
        auth = ""
        if self.user is not None or self.password is not None:
            auth = quote(self.user or "", safe="")
            if self.password is not None:
                auth += ":" + quote(self.password, safe="")
            auth += "@"
        return "%s://%s%s:%d" % (self.type.name.lower(), auth,
                                 self._formatHost(), self.port)

    def __repr__(self):
        country = str(self.country or "??").upper()
        return "<%s %s Proxy %s:%d>" % (self.type.name, country,
                                        self._formatHost(), self.port)

    @staticmethod
    def _isIP(host: str) -> bool:
        try:
            ip_address(host)
            return True
        except ValueError:
            return False

    @staticmethod
    def _normalizeHost(host: str) -> str:
        if not isinstance(host, str):
            raise ProxyInvalidHost(host)
        host = host.strip()
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        if not host:
            raise ProxyInvalidHost(host)

        try:
            return str(ip_address(host))
        except ValueError:
            pass

        if ":" in host:
            raise ProxyInvalidHost(host)

        if host.endswith("."):
            host = host[:-1]
        labels = host.split(".")
        if not host or all(label.isdigit() for label in labels):
            raise ProxyInvalidHost(host)

        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise ProxyInvalidHost(host)

        if len(ascii_host) > 253:
            raise ProxyInvalidHost(host)
        if any(not _HOST_LABEL.match(label)
               for label in ascii_host.split(".")):
            raise ProxyInvalidHost(host)
        return ascii_host.lower()

    @staticmethod
    def _normalizePort(port, proxy_type: ProxyType) -> int:
        if isinstance(port, bool) or not isinstance(port, int):
            raise ProxyInvalidPort(port)
        if port == 0:
            return _DEFAULT_PORTS[proxy_type]
        if not 1 <= port <= 65535:
            raise ProxyInvalidPort(port)
        return port

    @classmethod
    def fromString(cls, string: str):
        if not isinstance(string, str):
            return None
        value = string.strip()
        if not value:
            return None
        try:
            if "://" in value:
                try:
                    return cls._fromUrl(value)
                except (ValueError, ProxyParseError):
                    return cls._fromLegacy(value)
            return cls._fromBare(value)
        except (ValueError, ProxyParseError, UnicodeError):
            return None

    @classmethod
    def _fromUrl(cls, value: str):
        parsed = urlsplit(value)
        proxy_type = _SCHEME_TO_TYPE.get(parsed.scheme.lower())
        if proxy_type is None:
            return None
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            return None
        host = parsed.hostname
        if not host:
            return None
        port = parsed.port
        user = unquote(parsed.username) if parsed.username is not None else None
        password = unquote(parsed.password) \
            if parsed.password is not None else None
        return cls(host, port if port is not None
                   else _SCHEME_DEFAULT_PORTS[proxy_type], proxy_type,
                   user, password)

    @classmethod
    def _fromLegacy(cls, value: str):
        proxy_type = ProxyType.HTTP
        if "://" in value:
            scheme, value = value.split("://", 1)
            proxy_type = _SCHEME_TO_TYPE.get(scheme.lower())
            if proxy_type is None:
                return None
        value = value.strip()
        if not value or "/" in value or "?" in value or "#" in value \
                or any(char.isspace() for char in value):
            return None
        parts = value.split(":")
        if len(parts) >= 4:
            host, port_text, user = parts[0], parts[1], parts[2]
            password = ":".join(parts[3:])
            if not port_text.isdigit() or not user or not password:
                return None
            return cls(host, int(port_text), proxy_type,
                       unquote(user), unquote(password))
        if len(parts) == 2:
            host, port_text = parts
            if not host or not port_text.isdigit():
                return None
            return cls(host, int(port_text), proxy_type)
        if len(parts) == 1 and parts[0]:
            return cls(parts[0], _DEFAULT_PORTS[proxy_type], proxy_type)
        return None

    @classmethod
    def _fromBare(cls, value: str):
        user = password = None
        if "@" in value:
            userinfo, value = value.rsplit("@", 1)
            if ":" in userinfo:
                user_text, password_text = userinfo.split(":", 1)
                user = unquote(user_text)
                password = unquote(password_text)
            else:
                user = unquote(userinfo)
        value = value.strip()
        if not value:
            return None

        if value.startswith("["):
            end = value.find("]")
            if end < 0:
                return None
            host = value[1:end]
            tail = value[end + 1:]
            if tail:
                if not tail.startswith(":"):
                    return None
                port_text = tail[1:]
                if not port_text.isdigit():
                    return None
                port = int(port_text)
            else:
                port = 0
            return cls(host, port, ProxyType.HTTP, user, password)

        try:
            ip_address(value)
            return cls(value, 0, ProxyType.HTTP, user, password)
        except ValueError:
            pass

        parts = value.split(":")
        if len(parts) == 1:
            return cls(value, 0, ProxyType.HTTP, user, password)
        if len(parts) == 2:
            host, port_text = parts
            if not port_text.isdigit():
                return None
            return cls(host, int(port_text), ProxyType.HTTP, user, password)
        if len(parts) >= 4 and user is None:
            host, port_text = parts[0], parts[1]
            if not port_text.isdigit():
                return None
            user = unquote(parts[2])
            password = unquote(":".join(parts[3:]))
            return cls(host, int(port_text), ProxyType.HTTP, user, password)
        return None

    def ip_port(self):
        return "%s:%d" % (self._formatHost(), self.port)

    @staticmethod
    def validate(host: str, port: int):
        Proxy._normalizeHost(host)
        if isinstance(port, bool) or not isinstance(port, int) \
                or not 0 <= port <= 65535:
            raise ProxyInvalidPort(port)
        return True

    @staticmethod
    def _familyForHost(host: str, port: int,
                       sock_type=SOCK_STREAM) -> int:
        """Choose an address family that can reach the proxy host."""
        if ":" in host:
            return AF_INET6
        if Proxy._isIP(host):
            return AF_INET
        try:
            infos = getaddrinfo(host, port, AF_UNSPEC, sock_type)
        except OSError:
            return AF_INET
        families = {info[0] for info in infos}
        # Prefer IPv4 for dual-stack names, matching the old behaviour for
        # normal proxies, but fall back to IPv6 when it is the only option.
        if AF_INET in families:
            return AF_INET
        if AF_INET6 in families:
            return AF_INET6
        return AF_INET

    # noinspection PyShadowingBuiltins
    def open_socket(self,
                    family=None,
                    type=SOCK_STREAM,
                    proto=-1,
                    fileno=None):
        if family is None:
            family = self._familyForHost(self.host, self.port, type)
=======
        if Patterns.URL.match(host): host = gethostbyname(host)
        assert self.validate(host, port)
        self.host = host
        self.type = proxy_type
        self.port = port
        self.country = GeoIP.get(host)
        if self.country:
            self.country = self.country["registered_country"]["iso_code"]
        self.user = user or None
        self.password = password or None

    def __str__(self):
        return "%s://%s:%d%s" % (self.type.name.lower(), self.host, self.port,
                                 (":%s:%s" % (self.user, self.password)
                                  if self.password and self.user else ""))

    def __repr__(self):
        return "<%s %s Proxy %s:%d>" % (self.type.name, self.country.upper(),
                                        self.host, self.port)

    @staticmethod
    def fromString(string: str):
        with suppress(Exception):
            proxy: Any = Patterns.Proxy.search(string)
            return Proxy(
                proxy.group(2),
                int(proxy.group(3))
                if proxy.group(3) and proxy.group(3).isdigit() else 80,
                ProxyType.stringToProxyType(proxy.group(1)), proxy.group(4),
                proxy.group(5))
        return None

    def ip_port(self):
        return "%s:%d" % (self.host, self.port)

    @staticmethod
    def validate(host: str, port: int):
        with suppress(ValueError):
            if not ip_address(host):
                raise ProxyInvalidHost(host)
            if not Tools.Patterns.Port.match(str(port)):
                raise ProxyInvalidPort(port)
            return True
        raise ProxyInvalidHost(host)

    # noinspection PyShadowingBuiltins
    def open_socket(self,
                    family=AF_INET,
                    type=SOCK_STREAM,
                    proto=-1,
                    fileno=None):
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
        return ProxySocket(self, family, type, proto, fileno)

    def wrap(self, sock: Any):
        if isinstance(sock, socket):
<<<<<<< HEAD
            if isinstance(sock, SSLSocket):
                raise TypeError(
                    "Cannot wrap an SSLSocket; wrap the socket before TLS")
            family, sock_type, proto = sock.family, sock.type, sock.proto
            fd = sock.detach()
            try:
                return self.open_socket(family, sock_type, proto, fd)
            except Exception:
                from os import close
                close(fd)
                raise
        if not hasattr(sock, "proxies"):
            raise TypeError(
                "wrap() expects a socket or an object with 'proxies'")
=======
            return self.open_socket(sock.family, sock.type, sock.proto,
                                    sock.fileno())
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
        sock.proxies = self.asRequest()
        return sock

    def asRequest(self):
<<<<<<< HEAD
        url = self.__str__()
        return {"http": url, "https": url}

    # noinspection PyUnreachableCode
    def check(self, url: Any = "https://httpbin.org/get", timeout=5):
        """Check the proxy by making a real HTTP request through it.

        The old implementation only performed a TCP/CONNECT handshake and
        silently swallowed every exception.  Using requests verifies that the
        proxy can actually reach an HTTP(S) endpoint, works with HTTP and
        SOCKS proxies, and reports failures instead of hiding them.
        """
        try:
            target = str(url)
            with requests.Session() as session:
                session.trust_env = False
                session.proxies = self.asRequest()
                response = session.get(target, timeout=timeout)
                try:
                    return 200 <= response.status_code < 400
                finally:
                    response.close()
        except (RequestException, ValueError, OSError, UnicodeError) as exc:
            logger.debug("Proxy %s check failed: %s", self.ip_port(), exc)
            return False


def _isIPv6Literal(host: str) -> bool:
    try:
        return ip_address(host).version == 6
    except ValueError:
        # Zone IDs or a malformed literal still use IPv6-style authority
        # formatting; the proxy will return the definitive error.
        return ":" in host


def _formatTargetHost(host: str) -> bytes:
    if _isIPv6Literal(host):
        return ("[" + host + "]").encode("ascii")
    return host.encode("idna")


def _resolveTarget(host: str, port: int) -> str:
    try:
        infos = getaddrinfo(host, port, AF_UNSPEC, SOCK_STREAM)
    except OSError as exc:
        raise GeneralProxyError(
            "Unable to resolve target %s: %s" % (host, exc))
    for family, _, _, _, sockaddr in infos:
        if family in (AF_INET, AF_INET6):
            return sockaddr[0]
    raise GeneralProxyError("Unable to resolve target %s" % host)


def _negotiateHTTP(sock, dest_addr, dest_port):
    """HTTP CONNECT negotiation with correct IPv6 authority formatting."""
    proxy_type, proxy_addr, proxy_port, rdns, username, password = sock.proxy

    if rdns:
        target = dest_addr
        peer = (dest_addr, dest_port)
    else:
        target = _resolveTarget(dest_addr, dest_port)
        peer = (target, dest_port)

    authority = _formatTargetHost(target) + b":" + \
        str(dest_port).encode("ascii")
    headers = [
        b"CONNECT " + authority + b" HTTP/1.1",
        b"Host: " + authority,
        b"Proxy-Connection: Keep-Alive",
    ]
    if username and password:
        headers.append(b"Proxy-Authorization: Basic " +
                       b64encode(username + b":" + password))
    sock.sendall(b"\r\n".join(headers) + b"\r\n\r\n")

    # buffering=0 prevents read-ahead from consuming bytes that belong to
    # the tunneled protocol (for example an SSH/SMTP banner).
    response = sock.makefile("rb", buffering=0)
    try:
        status_line = response.readline()
        if not status_line:
            raise GeneralProxyError("Connection closed unexpectedly")
        # Consume all response headers.  Leaving them in the socket would
        # corrupt the tunneled stream.
        while True:
            line = response.readline()
            if not line or line in (b"\r\n", b"\n"):
                break
    finally:
        response.close()

    parts = status_line.split(b" ", 2)
    if len(parts) < 2:
        raise GeneralProxyError("HTTP proxy server sent invalid response")

    proto, status_text = parts[0], parts[1]
    if not proto.startswith(b"HTTP/"):
        raise GeneralProxyError(
            "Proxy server does not appear to be an HTTP proxy")
    try:
        status_code = int(status_text)
    except ValueError:
        raise HTTPError(
            "HTTP proxy server did not return a valid HTTP status")

    if status_code != 200:
        status_msg = parts[2].decode("latin-1", "replace") \
            if len(parts) > 2 else ""
        error = "%d: %s" % (status_code, status_msg)
        if status_code in (400, 403, 405):
            error += ("\n[*] Note: The HTTP proxy server may not support "
                      "CONNECT tunneling")
        raise HTTPError(error)

    sock.proxy_sockname = sock.getsockname()
    sock.proxy_peername = peer
=======
        return {
            "http": self.__str__(),
            "https": self.__str__().replace("http://", "https://")
        }

    # noinspection PyUnreachableCode
    def check(self, url: Any = "https://httpbin.org/get", timeout=5):
        if not isinstance(url, URL): url = URL(url)
        with suppress(Exception):
            with self.open_socket() as sock:
                sock.settimeout(timeout)
                sock.connect((url.host, url.port or 80))
                return True
        return False
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d


# noinspection PyShadowingBuiltins
class ProxySocket(socksocket):
<<<<<<< HEAD
    _proxy_negotiators = dict(socksocket._proxy_negotiators)
    _proxy_negotiators[HTTP] = _negotiateHTTP

    def __init__(self,
                 proxy: Proxy,
                 family=None,
                 type=SOCK_STREAM,
                 proto=0,
                 fileno=None):
        if family is None:
            family = Proxy._familyForHost(proxy.host, proxy.port, type)
=======

    def __init__(self,
                 proxy: Proxy,
                 family=-1,
                 type=-1,
                 proto=-1,
                 fileno=None):
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
        super().__init__(family, type, proto, fileno)
        if proxy.port:
            if proxy.user and proxy.password:
                self.setproxy(proxy.type.asPySocksType(),
                              proxy.host,
                              proxy.port,
                              username=proxy.user,
                              password=proxy.password)
                return
            self.setproxy(proxy.type.asPySocksType(), proxy.host, proxy.port)
            return
        if proxy.user and proxy.password:
            self.setproxy(proxy.type.asPySocksType(),
                          proxy.host,
                          username=proxy.user,
                          password=proxy.password)
            return
        self.setproxy(proxy.type.asPySocksType(), proxy.host)

<<<<<<< HEAD
    def connect(self, dest_pair, catch_errors=None):
        # PySocks rejects bracketed IPv6 destinations before negotiation.
        # Normalize the address here and let the SOCKS5/HTTP negotiators
        # handle the bare IPv6 literal.
        if isinstance(dest_pair, (list, tuple)) and len(dest_pair) == 2:
            host, port = dest_pair
            if isinstance(host, str):
                host = host.strip()
                if host.startswith("[") and host.endswith("]"):
                    host = host[1:-1]
                if ":" in host and self.proxy[0] == SOCKS4:
                    raise GeneralProxyError(
                        "SOCKS4 does not support IPv6 targets")
                dest_pair = (host, port)
        return super().connect(dest_pair, catch_errors)

=======
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d

class ProxyChecker:

    @staticmethod
    def checkAll(proxies: Collection[Proxy],
                 url: Any = "https://httpbin.org/get",
                 timeout=5,
<<<<<<< HEAD
                 threads=100):
        proxy_list = list(dict.fromkeys(proxies))
        if not proxy_list:
            return set()
        if threads is None:
            threads = 100
        try:
            threads = int(threads)
        except (TypeError, ValueError):
            raise ValueError("threads must be a positive integer")
        if threads < 1:
            raise ValueError("threads must be a positive integer")

        # Never create one worker per proxy.  The old formula could create up
        # to 1000 threads for a large list; the caller's limit is the maximum
        # concurrency, not a multiplier.
        max_workers = min(len(proxy_list), threads)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_proxy = {
                executor.submit(proxy.check, url, timeout): proxy
                for proxy in proxy_list
            }
            checked = set()
            for future in as_completed(future_to_proxy):
                try:
                    if future.result():
                        checked.add(future_to_proxy[future])
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("Proxy check crashed for %s: %s",
                                 repr(future_to_proxy[future]), exc)
            return checked
=======
                 threads=1000):
        with ThreadPoolExecutor(
                max(min(round(len(proxies) * cpu_count()), threads),
                    1)) as executor:
            future_to_proxy = {
                executor.submit(proxy.check, url, timeout): proxy
                for proxy in proxies
            }
            return {
                future_to_proxy[future]
                for future in as_completed(future_to_proxy) if future.result()
            }
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d


class ProxyUtiles:

    @staticmethod
<<<<<<< HEAD
    def parseAll(proxies: Iterable[str],
                 ptype: ProxyType = ProxyType.HTTP) -> Set[Proxy]:
        final = set()
        for item in proxies:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if not value:
                continue

            if "://" in value or "@" in value:
                proxy = Proxy.fromString(value)
                if proxy is not None:
                    final.add(proxy)
                continue

            if value.startswith("["):
                end = value.find("]")
                if end > 0:
                    host = value[1:end]
                    tail = value[end + 1:]
                    if tail == "":
                        port = 0
                    elif tail.startswith(":") and tail[1:].isdigit():
                        port = int(tail[1:])
                    else:
                        port = None
                    if port is not None:
                        with suppress(ProxyParseError):
                            final.add(Proxy(host, port, ptype))
                        continue

            match = Patterns.IPPort.search(value)
            if match:
                with suppress(ProxyParseError):
                    final.add(Proxy(match.group(1), int(match.group(2)),
                                    ptype))
                continue

            if value.count(":") == 1:
                host, port_text = value.split(":", 1)
                if port_text.isdigit():
                    with suppress(ProxyParseError):
                        final.add(Proxy(host, int(port_text), ptype))
                    continue

            proxy = Proxy.fromString(value)
            if proxy is not None:
                final.add(proxy)
=======
    def parseAll(proxies: Collection[str],
                 ptype: ProxyType = ProxyType.HTTP) -> Set[Proxy]:
        final = {
            *ProxyUtiles.parseAllIPPort(proxies, ptype),
            *ProxyUtiles.parseNoraml(proxies)
        }
        if None in final: final.remove(None)
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
        return final

    @staticmethod
    def parseNoraml(proxies: Collection[str]) -> Set[Proxy]:
<<<<<<< HEAD
        return {
            proxy
            for proxy in map(Proxy.fromString, proxies)
            if proxy is not None
        }

    @staticmethod
    def parseNormal(proxies: Collection[str]) -> Set[Proxy]:
        """Correctly-spelled alias for :meth:`parseNoraml`."""
        return ProxyUtiles.parseNoraml(proxies)
=======
        res = set(map(Proxy.fromString, proxies))
        if None in res: res.remove(None)
        return res
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d

    @staticmethod
    def parseAllIPPort(proxies: Collection[str],
                       ptype: ProxyType = ProxyType.HTTP) -> Set[Proxy]:
<<<<<<< HEAD
        result = set()
        for item in proxies:
            if not isinstance(item, str):
                continue
            match = Patterns.IPPort.search(item.strip())
            if not match:
                continue
            with suppress(ProxyParseError):
                result.add(Proxy(match.group(1), int(match.group(2)), ptype))
        return result

    @staticmethod
    def _readLines(path: Any):
        with open(path, "r", encoding="utf-8-sig",
                  errors="replace") as read:
            return [line.strip() for line in read]

    @staticmethod
    def readFromFile(path: Any,
                     ptype: ProxyType = ProxyType.HTTP) -> Set[Proxy]:
        return ProxyUtiles.parseAll(ProxyUtiles._readLines(path), ptype)

    @staticmethod
    def readIPPortFromFile(
            path: Any,
            ptype: ProxyType = ProxyType.HTTP) -> Set[Proxy]:
        return ProxyUtiles.parseAllIPPort(ProxyUtiles._readLines(path),
                                          ptype)
=======
        resu = set()
        for pr in proxies:
            pr = Patterns.IPPort.search(pr)
            if not pr: continue
            with suppress(Exception):
                resu.add(Proxy(pr.group(1), int(pr.group(2)), ptype))
        return resu

    @staticmethod
    def readFromFile(path: Any) -> Set[Proxy]:
        if isinstance(path, Path):
            with path.open("r+") as read:
                lines = read.readlines()
        else:
            with open(path, "r+") as read:
                lines = read.readlines()

        return ProxyUtiles.parseAll([prox.strip() for prox in lines])

    @staticmethod
    def readIPPortFromFile(path: Any) -> Set[Proxy]:
        if isinstance(path, Path):
            with path.open("r+") as read:
                lines = read.readlines()
        else:
            with open(path, "r+") as read:
                lines = read.readlines()

        return ProxyUtiles.parseAllIPPort([prox.strip() for prox in lines])
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
