import json
import logging
from base64 import b64encode
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import IntEnum, auto
from ipaddress import ip_address
from math import isfinite
from re import compile as _compile
from socket import (socket, SOCK_STREAM, AF_INET, AF_INET6, AF_UNSPEC,
                    getaddrinfo)
from ssl import SSLSocket
from time import perf_counter, sleep, time
from typing import AnyStr, Set, Collection, Any, Iterable, Optional
from urllib.parse import quote, unquote, urlsplit

import requests
from requests import RequestException
from socks import (socksocket, SOCKS4, SOCKS5, HTTP, GeneralProxyError,
                   HTTPError)

from PyRoxy import GeoIP, Tools
from PyRoxy.Exceptions import ProxyInvalidHost, ProxyInvalidPort, ProxyParseError
from PyRoxy.Tools import Patterns

__version__ = "1.0b7"
__auther__ = "MH_ProDev"
__all__ = ["ProxyUtiles", "ProxyType", "ProxySocket", "ProxyChecker",
           "Proxy", "GeoIP", "Tools", "CheckAttempt", "CheckResult",
           "CheckReport"]

logger = logging.getLogger(__name__)


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
    "socks4a": ProxyType.SOCKS4,
    "socks5": ProxyType.SOCKS5,
    "socks5h": ProxyType.SOCKS5,
}

# The "h" suffix in socks5h (and SOCKS4a) means the proxy resolves the
# destination name.  Resolution matters for IPv6: local resolution turns an
# AAAA-only name into an IPv6 address (a 16-byte SOCKS5 address), while remote
# resolution forwards the name itself.
_LOCAL_DNS_SCHEMES = frozenset({"socks4", "socks5"})

_HOST_LABEL = _compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _remoteDnsForScheme(scheme: str, proxy_type: ProxyType) -> bool:
    """Return True when ``scheme`` asks the proxy to resolve names."""
    if proxy_type not in (ProxyType.SOCKS4, ProxyType.SOCKS5):
        return False
    return scheme.strip().lower() not in _LOCAL_DNS_SCHEMES


def _validateRetryOptions(retries, retry_backoff):
    try:
        retries = int(retries)
    except (TypeError, ValueError) as exc:
        raise ValueError("retries must be a non-negative integer") from exc
    if retries < 0:
        raise ValueError("retries must be a non-negative integer")
    try:
        retry_backoff = float(retry_backoff)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "retry_backoff must be a non-negative number") from exc
    if not isfinite(retry_backoff) or retry_backoff < 0:
        raise ValueError("retry_backoff must be a non-negative number")
    return retries, retry_backoff


def _stripZoneId(host: str) -> str:
    """Return ``host`` without an IPv6 scope id (``fe80::1%eth0``)."""
    return host.split("%", 1)[0] if "%" in host else host


# noinspection PyShadowingBuiltins
class Proxy(object):
    user: Any
    password: Any
    country: Any
    port: int
    type: ProxyType
    host: AnyStr
    remote_dns: bool

    def __init__(self,
                 host: str,
                 port: int = 0,
                 proxy_type: ProxyType = ProxyType.HTTP,
                 user=None,
                 password=None,
                 remote_dns=None):
        if isinstance(proxy_type, str):
            scheme = proxy_type.strip().lower()
            mapped = _SCHEME_TO_TYPE.get(scheme)
            if mapped is None:
                raise ValueError("Unknown proxy type: %r" % proxy_type)
            proxy_type = mapped
            if remote_dns is None:
                remote_dns = _remoteDnsForScheme(scheme, proxy_type)
        elif not isinstance(proxy_type, ProxyType):
            try:
                proxy_type = ProxyType(proxy_type)
            except (TypeError, ValueError) as exc:
                raise TypeError("proxy_type must be a ProxyType") from exc

        host = self._normalizeHost(host)
        port = self._normalizePort(port, proxy_type)

        self.host = host
        self.type = proxy_type
        self.port = port
        # Only SOCKS can defer name resolution; PySocks resolves locally by
        # default, which is what a bare ProxyType meant before schemes existed.
        self.remote_dns = (True if remote_dns is None else bool(remote_dns)) \
            if proxy_type in (ProxyType.SOCKS4, ProxyType.SOCKS5) else False
        self.country = None
        if self._isIP(host):
            record = GeoIP.get(_stripZoneId(host))
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
                self.password, self.remote_dns) == (
                    other.type, other.host, other.port, other.user,
                    other.password, other.remote_dns)

    def __hash__(self):
        return hash((self.type, self.host, self.port, self.user,
                     self.password, self.remote_dns))

    def _formatHost(self):
        if ":" not in self.host:
            return self.host
        # Percent-encode the zone id of a scoped literal (RFC 6874) so the
        # serialized URL is valid and round-trips through _normalizeHost.
        return "[%s]" % quote(self.host, safe=":")

    def __str__(self):
        auth = ""
        if self.user is not None or self.password is not None:
            auth = quote(self.user or "", safe="")
            if self.password is not None:
                auth += ":" + quote(self.password, safe="")
            auth += "@"
        scheme = self.type.name.lower()
        if self.remote_dns:
            scheme = "socks5h" if self.type == ProxyType.SOCKS5 else "socks4a"
        return "%s://%s%s:%d" % (scheme, auth, self._formatHost(), self.port)

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

        # A scoped literal arrives percent-encoded when it came from a URL.
        candidate = unquote(host) if "%25" in host else host
        try:
            return str(ip_address(candidate))
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
        except UnicodeError as exc:
            raise ProxyInvalidHost(host) from exc

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
    def fromString(cls, string: str, default_type=ProxyType.HTTP):
        """Parse one proxy string, returning ``None`` when it is invalid.

        ``default_type`` is used for inputs without a scheme, so callers can
        parse a bare host list as SOCKS proxies.
        """
        if not isinstance(string, str):
            return None
        if not isinstance(default_type, ProxyType):
            default_type = ProxyType.stringToProxyType(default_type)
        value = string.strip()
        if not value:
            return None
        try:
            if "://" in value:
                try:
                    return cls._fromUrl(value)
                except (ValueError, ProxyParseError):
                    return cls._fromLegacy(value, default_type)
            return cls._fromBare(value, default_type)
        except (ValueError, ProxyParseError, UnicodeError):
            return None

    @classmethod
    def _fromUrl(cls, value: str):
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        proxy_type = _SCHEME_TO_TYPE.get(scheme)
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
                   user, password, remote_dns=_remoteDnsForScheme(
                       scheme, proxy_type))

    @classmethod
    def _fromLegacy(cls, value: str, default_type=ProxyType.HTTP):
        proxy_type = default_type
        scheme = None
        if "://" in value:
            scheme, value = value.split("://", 1)
            scheme = scheme.lower()
            proxy_type = _SCHEME_TO_TYPE.get(scheme)
            if proxy_type is None:
                return None
        value = value.strip()
        if not value or "/" in value or "?" in value or "#" in value \
                or any(char.isspace() for char in value):
            return None
        remote_dns = None if scheme is None else _remoteDnsForScheme(
            scheme, proxy_type)
        parts = value.split(":")
        if len(parts) >= 4:
            host, port_text, user = parts[0], parts[1], parts[2]
            password = ":".join(parts[3:])
            if not port_text.isdigit() or not user or not password:
                return None
            return cls(host, int(port_text), proxy_type,
                       unquote(user), unquote(password),
                       remote_dns=remote_dns)
        if len(parts) == 2:
            host, port_text = parts
            if not host or not port_text.isdigit():
                return None
            return cls(host, int(port_text), proxy_type,
                       remote_dns=remote_dns)
        if len(parts) == 1 and parts[0]:
            return cls(parts[0], _DEFAULT_PORTS[proxy_type], proxy_type,
                       remote_dns=remote_dns)
        return None

    @classmethod
    def _fromBare(cls, value: str, default_type=ProxyType.HTTP):
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
            return cls(host, port, default_type, user, password)

        try:
            ip_address(value)
            return cls(value, 0, default_type, user, password)
        except ValueError:
            pass

        parts = value.split(":")
        if len(parts) == 1:
            return cls(value, 0, default_type, user, password)
        if len(parts) == 2:
            host, port_text = parts
            if not port_text.isdigit():
                return None
            return cls(host, int(port_text), default_type, user, password)
        if len(parts) >= 4 and user is None:
            host, port_text = parts[0], parts[1]
            if not port_text.isdigit():
                return None
            user = unquote(parts[2])
            password = unquote(":".join(parts[3:]))
            return cls(host, int(port_text), default_type, user, password)
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
        return ProxySocket(self, family, type, proto, fileno)

    def wrap(self, sock: Any):
        if isinstance(sock, socket):
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
        sock.proxies = self.asRequest()
        return sock

    def asRequest(self):
        url = self.__str__()
        return {"http": url, "https": url}

    def check(self, url: Any = "https://httpbin.org/get", timeout=5):
        """Return True when the proxy can reach ``url``.

        This is a thin boolean wrapper around :meth:`check_detailed`; it is
        kept for backwards compatibility.  Use ``check_detailed`` when the
        status code, latency or failure reason matters.
        """
        return self.check_detailed(url, timeout).success

    def check_detailed(self, url: Any = "https://httpbin.org/get",
                       timeout=5, retries=0,
                       retry_backoff=0.0) -> "CheckResult":
        """Check the proxy with a real HTTP request and report the outcome.

        Uses ``requests`` so that HTTP(S) and SOCKS proxies are exercised the
        same way a caller would use them.  A 2xx/3xx response counts as a
        success.  Transport failures are returned as a failed
        :class:`CheckResult` instead of raising.

        ``retries`` retries transport failures and 5xx responses with an
        exponential backoff starting at ``retry_backoff`` seconds.  Every
        attempt is kept in :attr:`CheckResult.attempts`.
        """
        retries, retry_backoff = _validateRetryOptions(retries,
                                                       retry_backoff)
        target = str(url)
        started = perf_counter()
        history = []
        result = None
        for number in range(1, retries + 2):
            attempt_started = perf_counter()
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    session.proxies = self.asRequest()
                    response = session.get(target, timeout=timeout)
                    try:
                        status = response.status_code
                        attempt = CheckAttempt(
                            number=number,
                            elapsed=perf_counter() - attempt_started,
                            success=200 <= status < 400,
                            status_code=status,
                            reason=str(response.reason or ""),
                        )
                    finally:
                        response.close()
            except (RequestException, ValueError, OSError,
                    UnicodeError) as exc:
                logger.debug("Proxy %s check failed: %s", self.ip_port(),
                             exc)
                attempt = CheckAttempt(
                    number=number,
                    elapsed=perf_counter() - attempt_started,
                    success=False,
                    error=str(exc) or type(exc).__name__,
                    error_type=type(exc).__name__,
                )
            history.append(attempt)
            result = CheckResult(
                proxy=self,
                url=target,
                success=attempt.success,
                status_code=attempt.status_code,
                reason=attempt.reason,
                elapsed=attempt.elapsed,
                error=attempt.error,
                error_type=attempt.error_type,
                attempts=tuple(history),
            )
            if result.success:
                break
            retryable = result.error_type is not None or (
                result.status_code is not None and result.status_code >= 500)
            if not retryable or number > retries:
                break
            if retry_backoff:
                sleep(retry_backoff * (2 ** (number - 1)))
        return replace(result, elapsed=perf_counter() - started)


@dataclass(frozen=True)
class CheckAttempt:
    """One HTTP attempt made while checking a proxy."""

    number: int
    elapsed: float
    success: bool
    status_code: Optional[int] = None
    reason: str = ""
    error: Optional[str] = None
    error_type: Optional[str] = None

    def asDict(self):
        return {
            "number": self.number,
            "success": self.success,
            "status_code": self.status_code,
            "reason": self.reason,
            "elapsed": round(self.elapsed, 6),
            "error": self.error,
            "error_type": self.error_type,
        }


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single proxy check.

    ``success`` follows the same rule as :meth:`Proxy.check`: the target
    answered with a 2xx or 3xx status.  ``error``/``error_type`` are only set
    when the request itself failed, so a proxy that returns ``502`` keeps
    ``status_code == 502`` and ``error is None``.

    Results are immutable and serialisable through :meth:`asDict`; the proxy
    is exported as ``host:port`` so credentials never leak into reports.
    """

    proxy: "Proxy"
    url: str
    success: bool
    status_code: Optional[int] = None
    reason: str = ""
    elapsed: float = 0.0
    error: Optional[str] = None
    error_type: Optional[str] = None
    attempts: tuple = ()
    checked_at: float = field(default_factory=time)

    @property
    def ok(self) -> bool:
        """Alias for :attr:`success`."""
        return self.success

    @property
    def attempt_count(self) -> int:
        """Number of attempts recorded for this check."""
        return len(self.attempts)

    def __bool__(self) -> bool:
        return self.success

    @property
    def detail(self) -> str:
        """Human-readable outcome, preferring the transport error."""
        if self.error:
            return self.error
        if self.status_code is not None:
            return ("HTTP %d %s" % (self.status_code, self.reason)).strip()
        return "no response"

    def asDict(self):
        return {
            "proxy": self.proxy.ip_port(),
            "proxy_type": self.proxy.type.name,
            "url": self.url,
            "success": self.success,
            "status_code": self.status_code,
            "reason": self.reason,
            "elapsed": round(self.elapsed, 6),
            "error": self.error,
            "error_type": self.error_type,
            "attempt_count": self.attempt_count,
            "attempts": [attempt.asDict() for attempt in self.attempts],
            "checked_at": datetime.fromtimestamp(
                self.checked_at, timezone.utc).isoformat(),
        }

    def __str__(self):
        return "%s %s (%.2fs)" % (
            "OK" if self.success else "FAIL", self.detail, self.elapsed)


class CheckReport:
    """Immutable collection of :class:`CheckResult` objects.

    Iterating yields results in the order the proxies were passed to
    :meth:`ProxyChecker.checkAllDetailed`.  ``len(report)`` is the number of
    checks, ``report.working`` is the set of proxies that passed (the value
    :meth:`ProxyChecker.checkAll` returns) and ``report.failed`` the rest.
    """

    def __init__(self, results: Iterable[CheckResult] = (), url: Any = "",
                 elapsed: float = 0.0):
        self._results = tuple(results)
        self.url = str(url)
        self.elapsed = float(elapsed)

    @property
    def results(self) -> tuple:
        return self._results

    @property
    def total(self) -> int:
        return len(self._results)

    @property
    def success_count(self) -> int:
        return sum(1 for result in self._results if result.success)

    @property
    def failure_count(self) -> int:
        return self.total - self.success_count

    @property
    def total_attempts(self) -> int:
        return sum(result.attempt_count for result in self._results)

    @property
    def success_rate(self) -> float:
        """Fraction of proxies that worked, between 0.0 and 1.0."""
        if not self.total:
            return 0.0
        return self.success_count / self.total

    @property
    def working(self) -> Set[Proxy]:
        return {result.proxy for result in self._results if result.success}

    @property
    def failed(self) -> Set[Proxy]:
        return {result.proxy for result in self._results if not result.success}

    @property
    def status_codes(self) -> Counter:
        codes = Counter()
        for result in self._results:
            if result.status_code is not None:
                codes[result.status_code] += 1
        return codes

    @property
    def errors(self) -> Counter:
        """Failure reasons keyed by exception type or ``HTTP <code>``."""
        failures = Counter()
        for result in self._results:
            if result.success:
                continue
            if result.error_type:
                failures[result.error_type] += 1
            elif result.status_code is not None:
                failures["HTTP %d" % result.status_code] += 1
            else:
                failures["unknown"] += 1
        return failures

    def __iter__(self):
        return iter(self._results)

    def __len__(self):
        return self.total

    def __getitem__(self, index):
        return self._results[index]

    def __repr__(self):
        return "<CheckReport %d/%d working in %.2fs>" % (
            self.success_count, self.total, self.elapsed)

    def summary(self) -> str:
        """Return a short human-readable summary of the run."""
        if not self.total:
            return "No proxies checked."
        head = "%d/%d working (%.1f%%) against %s in %.2fs" % (
            self.success_count, self.total, self.success_rate * 100,
            self.url, self.elapsed)
        if not self.failure_count:
            return head
        details = ", ".join(
            "%s x%d" % (name, count)
            for name, count in self.errors.most_common())
        return head + "\nFailures: " + details

    def asDict(self):
        return {
            "url": self.url,
            "elapsed": round(self.elapsed, 6),
            "total": self.total,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "attempt_count": self.total_attempts,
            "success_rate": round(self.success_rate, 6),
            "status_codes": {str(code): count
                             for code, count in self.status_codes.items()},
            "errors": dict(self.errors),
            "results": [result.asDict() for result in self._results],
        }

    def to_json(self, indent=None) -> str:
        """Serialise :meth:`asDict` as JSON."""
        return json.dumps(self.asDict(), indent=indent)


def _isIPv6Literal(host: str) -> bool:
    try:        return ip_address(host).version == 6
    except ValueError:
        # A malformed literal still uses IPv6-style authority formatting;
        # the proxy will return the definitive error.
        return ":" in host


def _formatTargetHost(host: str) -> bytes:
    if _isIPv6Literal(host):
        # RFC 6874: a zone id inside a bracketed literal is percent-encoded.
        return ("[" + quote(host, safe=":") + "]").encode("ascii")
    return host.encode("idna")


def _resolveTarget(host: str, port: int) -> str:
    try:
        # Never re-resolve a literal: this keeps an IPv6 zone id intact and
        # avoids a pointless DNS round trip for addresses such as ::1.
        return str(ip_address(host))
    except ValueError:
        pass
    try:
        infos = getaddrinfo(host, port, AF_UNSPEC, SOCK_STREAM)
    except OSError as exc:
        raise GeneralProxyError(
            "Unable to resolve target %s: %s" % (host, exc)) from exc
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
    except ValueError as exc:
        raise HTTPError(
            "HTTP proxy server did not return a valid HTTP status") from exc

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


# noinspection PyShadowingBuiltins
class ProxySocket(socksocket):
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
        super().__init__(family, type, proto, fileno)
        options = {"rdns": proxy.remote_dns}
        if proxy.user and proxy.password:
            options["username"] = proxy.user
            options["password"] = proxy.password
        if proxy.port:
            self.setproxy(proxy.type.asPySocksType(), proxy.host,
                          proxy.port, **options)
            return
        self.setproxy(proxy.type.asPySocksType(), proxy.host, **options)

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
                if "%25" in host:
                    host = unquote(host)
                proxy_type = self.proxy[0] if self.proxy else None
                is_ipv6 = False
                if ":" in host:
                    try:
                        is_ipv6 = ip_address(host).version == 6
                    except ValueError:
                        is_ipv6 = False
                if is_ipv6 and proxy_type == SOCKS4:
                    raise GeneralProxyError(
                        "SOCKS4/SOCKS4a cannot carry an IPv6 target")
                if is_ipv6 and "%" in host and proxy_type == SOCKS5:
                    raise GeneralProxyError(
                        "SOCKS5 has no field for an IPv6 zone id; "
                        "connect to a link-local target directly instead")
                dest_pair = (host, port)
        return super().connect(dest_pair, catch_errors)


class ProxyChecker:

    @staticmethod
    def _validateThreads(threads) -> int:
        if threads is None:
            threads = 100
        try:
            threads = int(threads)
        except (TypeError, ValueError) as exc:
            raise ValueError("threads must be a positive integer") from exc
        if threads < 1:
            raise ValueError("threads must be a positive integer")
        return threads

    @staticmethod
    def checkAll(proxies: Collection[Proxy],
                 url: Any = "https://httpbin.org/get",
                 timeout=5,
                 threads=100):
        """Return the set of proxies that can reach ``url``.

        Kept for backwards compatibility; :meth:`checkAllDetailed` returns
        the same information with per-proxy status codes and errors.
        """
        proxy_list = list(dict.fromkeys(proxies))
        if not proxy_list:
            return set()
        threads = ProxyChecker._validateThreads(threads)

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

    @staticmethod
    def checkAllDetailed(proxies: Collection[Proxy],
                         url: Any = "https://httpbin.org/get",
                         timeout=5,
                         threads=100,
                         retries=0,
                         retry_backoff=0.0) -> CheckReport:
        """Check every proxy and return a detailed :class:`CheckReport`.

        Results keep the order of ``proxies`` after duplicates are removed.
        The report exposes ``working``/``failed`` sets (equivalent to
        :meth:`checkAll`), aggregate counts, status-code and error
        histograms, ``asDict()`` and ``to_json()`` for reporting.  Retry
        options are forwarded to :meth:`Proxy.check_detailed`.
        """
        proxy_list = list(dict.fromkeys(proxies))
        target = str(url)
        if not proxy_list:
            return CheckReport((), target, 0.0)
        threads = ProxyChecker._validateThreads(threads)
        retries, retry_backoff = _validateRetryOptions(retries,
                                                       retry_backoff)

        started = perf_counter()
        results = [None] * len(proxy_list)
        max_workers = min(len(proxy_list), threads)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(proxy.check_detailed, target, timeout,
                                retries, retry_backoff): index
                for index, proxy in enumerate(proxy_list)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    results[index] = future.result()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("Proxy check crashed for %s: %s",
                                 repr(proxy_list[index]), exc)
                    results[index] = CheckResult(
                        proxy=proxy_list[index],
                        url=target,
                        success=False,
                        elapsed=perf_counter() - started,
                        error=str(exc) or type(exc).__name__,
                        error_type=type(exc).__name__,
                    )
        return CheckReport(results, target, perf_counter() - started)


class ProxyUtiles:

    @staticmethod
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
                proxy = Proxy.fromString(value, ptype)
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

            proxy = Proxy.fromString(value, ptype)
            if proxy is not None:
                final.add(proxy)
        return final

    @staticmethod
    def parseNoraml(proxies: Collection[str],
                    ptype: ProxyType = ProxyType.HTTP) -> Set[Proxy]:
        return {
            proxy
            for proxy in (Proxy.fromString(value, ptype)
                          for value in proxies)
            if proxy is not None
        }

    @staticmethod
    def parseNormal(proxies: Collection[str],
                    ptype: ProxyType = ProxyType.HTTP) -> Set[Proxy]:
        """Correctly-spelled alias for :meth:`parseNoraml`."""
        return ProxyUtiles.parseNoraml(proxies, ptype)

    @staticmethod
    def parseAllIPPort(proxies: Collection[str],
                       ptype: ProxyType = ProxyType.HTTP) -> Set[Proxy]:
        result = set()
        for item in proxies:
            if not isinstance(item, str):
                continue
            match = Patterns.HostPort.search(item.strip())
            if not match:
                continue
            host = match.group("ipv6") or match.group("ipv4")
            with suppress(ProxyParseError):
                result.add(Proxy(host, int(match.group("port")), ptype))
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
