import json
import os
import socket as socket_module
import stat
import struct
import tempfile
import threading
import unittest
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from socket import (AF_INET, AF_INET6, IPPROTO_TCP, SHUT_WR, SOCK_STREAM,
                    socket)
from unittest import mock

import requests
from maxminddb.errors import InvalidDatabaseError
from socks import GeneralProxyError

from PyRoxy import (CheckReport, CheckResult, GeoIP, Proxy, ProxyChecker,
                    ProxyType, ProxyUtiles)
from PyRoxy.Exceptions import ProxyInvalidHost, ProxyInvalidPort
from PyRoxy.Tools import Patterns, Random


# ---------------------------------------------------------------------------
# Low-level helpers used by the IPv6 tests below.  They intentionally speak
# the wire protocols themselves so the assertions are about bytes on the
# socket, not about PyRoxy's own client code doing the same thing twice.
# ---------------------------------------------------------------------------


def _read_exact(conn, count):
    data = b""
    while len(data) < count:
        chunk = conn.recv(count - len(data))
        if not chunk:
            raise RuntimeError("connection closed")
        data += chunk
    return data


def _pipe_through(left, right):
    """Relay bytes in both directions until both sides close."""

    def pipe(source, destination):
        try:
            while True:
                data = source.recv(65536)
                if not data:
                    break
                destination.sendall(data)
        except OSError:
            pass
        finally:
            with suppress(OSError):
                destination.shutdown(SHUT_WR)

    threads = [
        threading.Thread(target=pipe, args=(left, right), daemon=True),
        threading.Thread(target=pipe, args=(right, left), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def _ipv6_loopback_available():
    try:
        with socket(AF_INET6, SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
        return True
    except OSError:
        return False


IPV6_LOOPBACK = _ipv6_loopback_available()


class _EchoServer:
    """Echo every byte back, bound to an explicit address family."""

    def __init__(self, family=AF_INET, host="127.0.0.1"):
        self.server = socket(family, SOCK_STREAM)
        self.server.bind((host, 0))
        self.server.listen(1)
        self.server.settimeout(5)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.server.accept()
        except OSError:
            return
        with conn:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                conn.sendall(data)

    def close(self):
        self.server.close()
        self.thread.join(timeout=5)


class _Socks5Server:
    """Minimal SOCKS5 server that records the requested destination.

    With ``connect_target`` it dials the requested address (which may be an
    IPv6 literal) and relays the tunnel, so a real IPv6 destination can be
    reached through it.
    """

    def __init__(self, family=AF_INET, host="127.0.0.1", connect_target=False):
        self.server = socket(family, SOCK_STREAM)
        self.server.bind((host, 0))
        self.server.listen(1)
        self.server.settimeout(5)
        self.port = self.server.getsockname()[1]
        self.seen = {}
        self.connect_target = connect_target
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.server.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5)
            greeting = _read_exact(conn, 2)
            _read_exact(conn, greeting[1])
            conn.sendall(b"\x05\x00")
            header = _read_exact(conn, 4)
            atyp = header[3]
            if atyp == 1:
                host = str(ip_address(_read_exact(conn, 4)))
            elif atyp == 4:
                host = str(ip_address(_read_exact(conn, 16)))
            else:
                length = _read_exact(conn, 1)[0]
                host = _read_exact(conn, length).decode("ascii")
            port = struct.unpack(">H", _read_exact(conn, 2))[0]
            self.seen.update(host=host, port=port, atyp=atyp)
            conn.sendall(b"\x05\x00\x00\x01" + b"\x00" * 4 + b"\x00\x00")
            if not self.connect_target:
                return
            upstream = socket(
                AF_INET6 if ":" in host else AF_INET, SOCK_STREAM)
            upstream.settimeout(5)
            upstream.connect((host, port))
            upstream.settimeout(None)
            conn.settimeout(None)
            _pipe_through(conn, upstream)
            upstream.close()

    def close(self):
        self.server.close()
        self.thread.join(timeout=5)


class _HttpConnectServer:
    """Minimal HTTP proxy that records and (optionally) opens CONNECT."""

    def __init__(self, family=AF_INET, host="127.0.0.1", connect_target=False):
        self.server = socket(family, SOCK_STREAM)
        self.server.bind((host, 0))
        self.server.listen(1)
        self.server.settimeout(5)
        self.port = self.server.getsockname()[1]
        self.head = ""
        self.connect_target = connect_target
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.server.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            self.head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1")
            destination = self.head.split("\r\n", 1)[0].split(" ")[1]
            host, _, port = destination.rpartition(":")
            host = host.strip("[]")
            upstream = None
            if self.connect_target:
                upstream = socket(
                    AF_INET6 if ":" in host else AF_INET, SOCK_STREAM)
                upstream.settimeout(5)
                upstream.connect((host, int(port)))
                upstream.settimeout(None)
            conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            if upstream is None:
                return
            conn.settimeout(None)
            _pipe_through(conn, upstream)
            upstream.close()

    def close(self):
        self.server.close()
        self.thread.join(timeout=5)


class ProxyParsingTests(unittest.TestCase):

    def test_auth_ipv6_and_domains(self):
        proxy = Proxy.fromString("http://user:pass@1.2.3.4:8080")
        self.assertEqual(proxy.user, "user")
        self.assertEqual(proxy.password, "pass")
        self.assertEqual(str(proxy), "http://user:pass@1.2.3.4:8080")

        ipv6 = Proxy.fromString("socks5://user:pass@[2001:db8::1]:1080")
        self.assertEqual(ipv6.host, "2001:db8::1")
        self.assertEqual(ipv6.type, ProxyType.SOCKS5)
        self.assertIn("[2001:db8::1]", str(ipv6))

        self.assertIsNotNone(Proxy.fromString("http://example.info:8080"))
        self.assertIsNotNone(
            Proxy.fromString("http://proxy.example.online:8080"))

    def test_legacy_and_schemeless_formats(self):
        self.assertIsNotNone(Proxy.fromString("1.2.3.4:8080"))
        self.assertIsNotNone(Proxy.fromString("1.2.3.4:8080:user:pass"))
        self.assertIsNotNone(
            Proxy.fromString("http://1.2.3.4:8080:user:pass"))

    def test_default_ports(self):
        self.assertEqual(Proxy("1.2.3.4").port, 8080)
        self.assertEqual(Proxy.fromString("http://1.2.3.4").port, 80)
        self.assertEqual(Proxy.fromString("https://1.2.3.4").port, 443)
        self.assertEqual(Proxy.fromString("socks5://1.2.3.4").port, 1080)

    def test_roundtrip(self):
        values = [
            Proxy.fromString("http://user:p%40ss@1.2.3.4:8080"),
            Proxy.fromString("socks5://user:pass@[2001:db8::1]:1080"),
            Proxy.fromString("https://1.2.3.4:443"),
        ]
        for proxy in values:
            self.assertEqual(Proxy.fromString(str(proxy)), proxy)

    def test_invalid_urls(self):
        self.assertIsNone(Proxy.fromString("http://1.2.3.4:8080/path"))
        self.assertIsNone(Proxy.fromString("http://1.2.3.4:8080?q=1"))
        self.assertIsNone(Proxy.fromString("http://1.2.3.4:99999"))

    def test_dedupe(self):
        proxies = ProxyUtiles.parseAll(["1.2.3.4:8080"] * 5)
        self.assertEqual(len(proxies), 1)

    def test_parse_all_applies_default_type_without_scheme(self):
        proxies = ProxyUtiles.parseAll(
            ["1.2.3.4", "proxy.example", "user:pass@1.2.3.4",
             "proxy.example:9999"],
            ProxyType.SOCKS5)
        self.assertEqual(len(proxies), 4)
        self.assertEqual({proxy.type for proxy in proxies},
                         {ProxyType.SOCKS5})
        self.assertEqual({proxy.port for proxy in proxies}, {1080, 9999})
        self.assertIn("socks5h://user:pass@1.2.3.4:1080",
                      {str(proxy) for proxy in proxies})

        bare = Proxy.fromString("1.2.3.4", ProxyType.SOCKS4)
        self.assertEqual(bare.type, ProxyType.SOCKS4)
        self.assertEqual(bare.port, 1080)

    def test_parse_normal_alias_and_bracket_ptype(self):
        self.assertEqual(
            ProxyUtiles.parseNormal(["http://1.2.3.4:8080"]),
            ProxyUtiles.parseNoraml(["http://1.2.3.4:8080"]))
        result = ProxyUtiles.parseAll(["[2001:db8::1]:1080"],
                                      ProxyType.SOCKS5)
        self.assertEqual(next(iter(result)).type, ProxyType.SOCKS5)
        normal = ProxyUtiles.parseNormal(["1.2.3.4"], ProxyType.SOCKS4)
        self.assertEqual(next(iter(normal)).type, ProxyType.SOCKS4)

    def test_validation(self):
        for port in ("", "abc", None, 70000, True):
            with self.assertRaises(ProxyInvalidPort):
                Proxy("1.2.3.4", port)
        with self.assertRaises(ProxyInvalidHost):
            Proxy("999.1.1.1", 80)
        self.assertEqual(Proxy("localhost", 8080).host, "localhost")

    def test_ipv6_socket_family(self):
        with Proxy("::1", 8080).open_socket() as sock:
            self.assertEqual(sock.family, AF_INET6)
        with Proxy("fe80::1%eth0", 1080).open_socket() as sock:
            self.assertEqual(sock.family, AF_INET6)

    def test_ipv6_only_hostname_uses_inet6(self):
        records = [(AF_INET6, SOCK_STREAM, IPPROTO_TCP, "",
                    ("::1", 80, 0, 0))]
        with mock.patch("PyRoxy.getaddrinfo", return_value=records):
            self.assertEqual(Proxy._familyForHost("v6only.example", 80),
                             AF_INET6)

    def test_ipv6_endpoint_parsing(self):
        match = Patterns.HostPort.match("[2001:db8::1]:1080")
        self.assertEqual(match.group("ipv6"), "2001:db8::1")
        self.assertEqual(match.group("port"), "1080")
        self.assertEqual(
            Patterns.HostPort.match("1.2.3.4:8080").group("ipv4"),
            "1.2.3.4")
        self.assertIsNone(Patterns.HostPort.match("2001:db8::1"))

        parsed = ProxyUtiles.parseAllIPPort(
            ["[2001:db8::1]:1080", "1.2.3.4:8080", "not-an-endpoint"])
        self.assertEqual({proxy.host for proxy in parsed},
                         {"2001:db8::1", "1.2.3.4"})
        self.assertEqual(
            {proxy.port for proxy in parsed}, {1080, 8080})

        # A bare literal keeps the default port instead of being split at the
        # last colon, and a bracketed literal without a port behaves the same.
        self.assertEqual(
            {proxy.host for proxy in ProxyUtiles.parseAll([
                "2001:db8::1", "[2001:db8::1]"])},
            {"2001:db8::1"})
        self.assertEqual(
            {proxy.port for proxy in ProxyUtiles.parseAll(["2001:db8::1"])},
            {8080})

    def test_remote_dns_schemes_and_scoped_literals(self):
        cases = {
            "socks5://1.2.3.4:1080": (ProxyType.SOCKS5, False),
            "socks5h://1.2.3.4:1080": (ProxyType.SOCKS5, True),
            "socks4://1.2.3.4:1080": (ProxyType.SOCKS4, False),
            "socks4a://1.2.3.4:1080": (ProxyType.SOCKS4, True),
        }
        for value, (proxy_type, remote_dns) in cases.items():
            proxy = Proxy.fromString(value)
            self.assertEqual(proxy.type, proxy_type, value)
            self.assertEqual(proxy.remote_dns, remote_dns, value)
            self.assertEqual(Proxy.fromString(str(proxy)), proxy, value)

        # A ProxyType built directly keeps the historical PySocks default,
        # while a scheme string keeps the scheme's resolution semantics.
        self.assertTrue(Proxy("1.2.3.4", 1080, ProxyType.SOCKS5).remote_dns)
        self.assertFalse(Proxy("1.2.3.4", 1080, "socks5").remote_dns)
        self.assertTrue(Proxy("1.2.3.4", 1080, "socks5h").remote_dns)
        self.assertFalse(Proxy("1.2.3.4", 8080).remote_dns)

        scoped = Proxy("fe80::1%eth0", 8080)
        self.assertEqual(scoped.host, "fe80::1%eth0")
        self.assertEqual(str(scoped), "http://[fe80::1%25eth0]:8080")
        self.assertEqual(Proxy.fromString(str(scoped)), scoped)

    def test_wrap_detaches_original_socket(self):
        server = socket(AF_INET, SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def accept():
            conn, _ = server.accept()
            conn.close()

        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        client = socket(AF_INET, SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        wrapped = Proxy("1.2.3.4", 8080).wrap(client)
        try:
            self.assertEqual(client.fileno(), -1)
            self.assertNotEqual(wrapped.fileno(), -1)
        finally:
            wrapped.close()
            client.close()
            server.close()


class IPv6ProxySocketTests(unittest.TestCase):

    @staticmethod
    def _recv_exact(conn, count):
        data = b""
        while len(data) < count:
            chunk = conn.recv(count - len(data))
            if not chunk:
                raise RuntimeError("connection closed")
            data += chunk
        return data

    def test_http_connect_ipv6_authority_and_auth(self):
        server = socket(AF_INET, SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(2)
        port = server.getsockname()[1]
        received = []

        def serve():
            conn, _ = server.accept()
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            received.append(data)
            conn.sendall(
                b"HTTP/1.1 200 Connection established\r\n"
                b"Proxy-Agent: test\r\n\r\nhello")
            conn.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            proxy = Proxy("127.0.0.1", port, user="u", password="p")
            with proxy.open_socket() as sock:
                sock.settimeout(2)
                sock.connect(("[2001:db8::1]", 443))
                self.assertEqual(sock.recv(5), b"hello")
        finally:
            thread.join(timeout=2)
            server.close()

        request = received[0].decode("latin-1")
        self.assertIn("CONNECT [2001:db8::1]:443 HTTP/1.1", request)
        self.assertIn("Host: [2001:db8::1]:443", request)
        self.assertIn("Proxy-Authorization: Basic dTpw", request)

    def test_socks5_ipv6_destination(self):
        server = socket(AF_INET, SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(2)
        port = server.getsockname()[1]
        seen = {}

        def serve():
            conn, _ = server.accept()
            greeting = self._recv_exact(conn, 2)
            self._recv_exact(conn, greeting[1])
            conn.sendall(b"\x05\x00")
            header = self._recv_exact(conn, 4)
            seen["atyp"] = header[3]
            if header[3] == 4:
                seen["host"] = str(ip_address(
                    self._recv_exact(conn, 16)))
                seen["port"] = struct.unpack(
                    ">H", self._recv_exact(conn, 2))[0]
            conn.sendall(
                b"\x05\x00\x00\x01" + struct.pack(">I", 0x7f000001) +
                struct.pack(">H", 0))
            conn.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            proxy = Proxy("127.0.0.1", port, ProxyType.SOCKS5)
            with proxy.open_socket() as sock:
                sock.settimeout(2)
                sock.connect(("[2001:db8::1]", 80))
        finally:
            thread.join(timeout=2)
            server.close()

        self.assertEqual(seen["atyp"], 4)
        self.assertEqual(seen["host"], "2001:db8::1")
        self.assertEqual(seen["port"], 80)

    def test_socks4_rejects_ipv6_destination(self):
        with self.assertRaises(GeneralProxyError):
            with Proxy("127.0.0.1", 1080,
                       ProxyType.SOCKS4).open_socket() as sock:
                sock.connect(("2001:db8::1", 80))


@unittest.skipUnless(IPV6_LOOPBACK, "IPv6 loopback is not available")
class IPv6TargetTests(unittest.TestCase):
    """End-to-end IPv6: proxy over ::1 and a real IPv6 destination."""

    def test_socks5_proxy_and_target_over_ipv6(self):
        echo = _EchoServer(AF_INET6, "::1")
        server = _Socks5Server(AF_INET6, "::1", connect_target=True)
        try:
            proxy = Proxy("::1", server.port, ProxyType.SOCKS5)
            with proxy.open_socket() as sock:
                self.assertEqual(sock.family, AF_INET6)
                sock.settimeout(5)
                # Bracketed form must be accepted and peeled for the wire.
                sock.connect(("[::1]", echo.port))
                sock.sendall(b"ping")
                self.assertEqual(_read_exact(sock, 4), b"ping")
        finally:
            server.close()
            echo.close()

        self.assertEqual(server.seen, {"atyp": 4, "host": "::1",
                                       "port": echo.port})

    def test_http_connect_proxy_and_target_over_ipv6(self):
        echo = _EchoServer(AF_INET6, "::1")
        server = _HttpConnectServer(AF_INET6, "::1", connect_target=True)
        try:
            with Proxy("::1", server.port).open_socket() as sock:
                self.assertEqual(sock.family, AF_INET6)
                sock.settimeout(5)
                sock.connect(("::1", echo.port))
                sock.sendall(b"pong")
                self.assertEqual(_read_exact(sock, 4), b"pong")
        finally:
            server.close()
            echo.close()

        first_line = server.head.split("\r\n", 1)[0]
        self.assertEqual(first_line,
                         "CONNECT [::1]:%d HTTP/1.1" % echo.port)
        self.assertIn("Host: [::1]:%d" % echo.port, server.head)

    def test_socks5_local_resolution_of_aaaa_record(self):
        server = _Socks5Server()
        real_getaddrinfo = socket_module.getaddrinfo

        def fake_getaddrinfo(host, port, *args, **kwargs):
            if host == "v6only.example":
                return [(AF_INET6, SOCK_STREAM, IPPROTO_TCP, "",
                         ("::1", port, 0, 0))]
            return real_getaddrinfo(host, port, *args, **kwargs)

        try:
            proxy = Proxy.fromString("socks5://127.0.0.1:%d" % server.port)
            self.assertFalse(proxy.remote_dns)
            with mock.patch("socket.getaddrinfo",
                            side_effect=fake_getaddrinfo):
                with proxy.open_socket() as sock:
                    sock.settimeout(5)
                    sock.connect(("v6only.example", 443))
        finally:
            server.close()

        self.assertEqual(server.seen, {"atyp": 4, "host": "::1",
                                       "port": 443})

    def test_socks5h_forwards_ipv6_name_to_proxy(self):
        server = _Socks5Server()
        try:
            proxy = Proxy.fromString("socks5h://127.0.0.1:%d" % server.port)
            self.assertTrue(proxy.remote_dns)
            with proxy.open_socket() as sock:
                sock.settimeout(5)
                sock.connect(("v6only.example", 443))
        finally:
            server.close()

        self.assertEqual(server.seen, {"atyp": 3, "host": "v6only.example",
                                       "port": 443})

    def test_scoped_ipv6_connect_authority(self):
        server = _HttpConnectServer()
        try:
            with Proxy("127.0.0.1", server.port).open_socket() as sock:
                sock.settimeout(5)
                sock.connect(("fe80::1%eth0", 80))
        finally:
            server.close()

        self.assertTrue(server.head.startswith(
            "CONNECT [fe80::1%25eth0]:80 HTTP/1.1"), server.head)
        self.assertIn("Host: [fe80::1%25eth0]:80", server.head)

    def test_socks5_rejects_scoped_ipv6_target(self):
        with self.assertRaises(GeneralProxyError):
            with Proxy("127.0.0.1", 1080,
                       ProxyType.SOCKS5).open_socket() as sock:
                sock.connect(("fe80::1%eth0", 80))


class FileTests(unittest.TestCase):

    def test_read_from_file_readonly_and_dedupe(self):
        path = Path(tempfile.gettempdir()) / "pyroxy_test_list.txt"
        path.write_text(
            "1.2.3.4:8080\n"
            "1.2.3.4:8080\n"
            "socks5://5.6.7.8:1080\n"
            "http://user:pass@9.9.9.9:3128\n",
            encoding="utf-8",
        )
        os.chmod(path, stat.S_IREAD)
        try:
            self.assertEqual(len(ProxyUtiles.readFromFile(path)), 3)
        finally:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            path.unlink()


class GeoIPTests(unittest.TestCase):

    def test_failed_reload_keeps_previous_database(self):
        GeoIP.close()
        self.assertEqual(GeoIP.get("8.8.8.8")["country"]["iso_code"], "US")
        original = GeoIP.database_path()

        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.mmdb"
            with self.assertRaises(OSError):
                GeoIP.reload(missing)
            self.assertEqual(GeoIP.database_path(), original)
            self.assertEqual(
                GeoIP.get("8.8.8.8")["country"]["iso_code"], "US")

            corrupt = Path(directory) / "corrupt.mmdb"
            corrupt.write_bytes(b"not an mmdb")
            with self.assertRaises(InvalidDatabaseError):
                GeoIP.reload(corrupt)
            self.assertEqual(GeoIP.database_path(), original)
            self.assertEqual(
                GeoIP.get("8.8.8.8")["country"]["iso_code"], "US")
        GeoIP.close()

    def test_lazy_reader_and_lookup(self):
        GeoIP.close()
        record = GeoIP.get("8.8.8.8")
        self.assertEqual(record["country"]["iso_code"], "US")
        self.assertTrue(GeoIP.database_path().is_file())
        db_metadata = GeoIP.metadata()
        self.assertEqual(db_metadata.database_type, "GeoLite2-Country")
        self.assertGreaterEqual(db_metadata.build_epoch, 1735689600)
        GeoIP.reload()
        self.assertEqual(
            GeoIP.get("2001:4860:4860::8888")["country"]["iso_code"], "US")
        GeoIP.close()


class CheckTests(unittest.TestCase):

    class FakeResponse:
        def __init__(self, status_code, reason="OK"):
            self.status_code = status_code
            self.reason = reason
            self.closed = False

        def close(self):
            self.closed = True

    class FakeSession:
        def __init__(self, response):
            self.response = response
            self.proxies = None
            self.trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, timeout):
            return self.response

    def test_check_success(self):
        session = self.FakeSession(self.FakeResponse(200))
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            self.assertTrue(
                Proxy("1.2.3.4", 8080, user="u", password="p").check(
                    "https://example.com"))
        self.assertFalse(session.trust_env)
        self.assertEqual(session.proxies["http"],
                         "http://u:p@1.2.3.4:8080")
        self.assertTrue(session.response.closed)

    def test_check_failure(self):
        session = self.FakeSession(self.FakeResponse(502))
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            self.assertFalse(Proxy("1.2.3.4", 8080).check(
                "https://example.com"))

    def test_check_request_exception(self):
        session = self.FakeSession(self.FakeResponse(200))
        session.get = mock.Mock(side_effect=requests.RequestException("fail"))
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            self.assertFalse(Proxy("1.2.3.4", 8080).check(
                "https://example.com"))

    def test_check_with_local_http_proxy(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            proxy = Proxy("127.0.0.1", server.server_port)
            self.assertTrue(proxy.check("http://example.com", timeout=2))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_check_all_bounded_and_empty(self):
        self.assertEqual(ProxyChecker.checkAll([]), set())
        with mock.patch.object(Proxy, "check", return_value=True):
            result = ProxyChecker.checkAll([
                Proxy("1.2.3.4", 8080),
                Proxy("5.6.7.8", 8080),
            ], threads=1)
        self.assertEqual(len(result), 2)
        with self.assertRaises(ValueError):
            ProxyChecker.checkAll([Proxy("1.2.3.4", 8080)], threads=0)

    def test_check_detailed_success(self):
        session = self.FakeSession(self.FakeResponse(204, "No Content"))
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            result = Proxy("1.2.3.4", 8080).check_detailed(
                "https://example.com")
        self.assertIsInstance(result, CheckResult)
        self.assertTrue(result.success)
        self.assertTrue(result.ok)
        self.assertTrue(result)
        self.assertEqual(result.status_code, 204)
        self.assertEqual(result.reason, "No Content")
        self.assertIsNone(result.error)
        self.assertIsNone(result.error_type)
        self.assertGreaterEqual(result.elapsed, 0.0)
        self.assertEqual(result.detail, "HTTP 204 No Content")
        self.assertEqual(str(result), "OK HTTP 204 No Content (%.2fs)"
                         % result.elapsed)

        payload = result.asDict()
        self.assertEqual(payload["proxy"], "1.2.3.4:8080")
        self.assertEqual(payload["proxy_type"], "HTTP")
        self.assertTrue(payload["success"])
        self.assertEqual(payload["status_code"], 204)
        json.dumps(payload)

    def test_check_detailed_http_failure_keeps_status(self):
        session = self.FakeSession(self.FakeResponse(502, "Bad Gateway"))
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            result = Proxy("1.2.3.4", 8080).check_detailed(
                "https://example.com")
        self.assertFalse(result.success)
        self.assertFalse(result)
        self.assertEqual(result.status_code, 502)
        self.assertEqual(result.reason, "Bad Gateway")
        self.assertIsNone(result.error)
        self.assertEqual(result.detail, "HTTP 502 Bad Gateway")

    def test_check_detailed_transport_failure(self):
        session = self.FakeSession(self.FakeResponse(200))
        session.get = mock.Mock(
            side_effect=requests.exceptions.ProxyError("refused"))
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            result = Proxy("1.2.3.4", 8080).check_detailed(
                "https://example.com")
        self.assertFalse(result.success)
        self.assertIsNone(result.status_code)
        self.assertEqual(result.error_type, "ProxyError")
        self.assertEqual(result.error, "refused")
        self.assertEqual(result.detail, "refused")

    def test_check_detailed_catches_value_error(self):
        session = self.FakeSession(self.FakeResponse(200))
        session.get = mock.Mock(side_effect=ValueError("bad url"))
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            result = Proxy("1.2.3.4", 8080).check_detailed("nonsense")
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "ValueError")
        self.assertEqual(result.error, "bad url")

    def test_check_detailed_retries_transport_errors(self):
        session = self.FakeSession(self.FakeResponse(200))
        session.get = mock.Mock(side_effect=[
            requests.exceptions.ProxyError("refused"),
            self.FakeResponse(200, "OK"),
        ])
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            result = Proxy("1.2.3.4", 8080).check_detailed(
                "https://example.com", retries=1)
        self.assertTrue(result.success)
        self.assertEqual(result.attempt_count, 2)
        self.assertEqual(len(result.attempts), 2)
        self.assertEqual(result.attempts[0].error_type, "ProxyError")
        self.assertFalse(result.attempts[0].success)
        self.assertTrue(result.attempts[1].success)
        self.assertEqual(session.get.call_count, 2)
        payload = result.asDict()
        self.assertEqual(payload["attempt_count"], 2)
        self.assertEqual(len(payload["attempts"]), 2)
        self.assertEqual(payload["attempts"][0]["error_type"], "ProxyError")
        json.dumps(payload)

    def test_check_detailed_retries_server_errors(self):
        session = self.FakeSession(self.FakeResponse(502, "Bad Gateway"))
        session.get = mock.Mock(side_effect=[
            self.FakeResponse(502, "Bad Gateway"),
            self.FakeResponse(204, "No Content"),
        ])
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            result = Proxy("1.2.3.4", 8080).check_detailed(
                "https://example.com", retries=2)
        self.assertTrue(result.success)
        self.assertEqual(result.attempt_count, 2)
        self.assertEqual(result.attempts[0].status_code, 502)
        self.assertFalse(result.attempts[0].success)

    def test_check_detailed_does_not_retry_client_errors(self):
        session = self.FakeSession(self.FakeResponse(200))
        session.get = mock.Mock(side_effect=[
            self.FakeResponse(407, "Proxy Authentication Required"),
            self.FakeResponse(200, "OK"),
        ])
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            result = Proxy("1.2.3.4", 8080).check_detailed(
                "https://example.com", retries=3)
        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 407)
        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(session.get.call_count, 1)

    def test_check_detailed_stops_at_retry_limit(self):
        session = self.FakeSession(self.FakeResponse(200))
        session.get = mock.Mock(
            side_effect=requests.exceptions.ConnectTimeout("slow"))
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            result = Proxy("1.2.3.4", 8080).check_detailed(
                "https://example.com", retries=2)
        self.assertFalse(result.success)
        self.assertEqual(result.attempt_count, 3)
        self.assertEqual(session.get.call_count, 3)
        self.assertTrue(all(attempt.error_type == "ConnectTimeout"
                            for attempt in result.attempts))

    def test_check_detailed_retry_options_validation(self):
        proxy = Proxy("1.2.3.4", 8080)
        for retries in (-1, "many", None):
            with self.assertRaises(ValueError):
                proxy.check_detailed("https://example.com", retries=retries)
        for backoff in (-0.1, "slow", None, float("nan"),
                        float("inf")):
            with self.assertRaises(ValueError):
                proxy.check_detailed("https://example.com",
                                     retry_backoff=backoff)

    def test_check_all_detailed_reports_attempt_totals(self):
        proxy = Proxy("1.2.3.4", 8080)
        session = self.FakeSession(self.FakeResponse(200))
        session.get = mock.Mock(side_effect=[
            requests.exceptions.ProxyError("refused"),
            self.FakeResponse(200, "OK"),
        ])
        with mock.patch("PyRoxy.requests.Session", return_value=session):
            report = ProxyChecker.checkAllDetailed([proxy], retries=1)
        self.assertEqual(report.total, 1)
        self.assertEqual(report.total_attempts, 2)
        self.assertEqual(report.asDict()["attempt_count"], 2)
        self.assertEqual(report.results[0].attempt_count, 2)
        self.assertEqual(report.working, {proxy})

    def test_check_all_detailed_rejects_bad_retry_options(self):
        proxy = Proxy("1.2.3.4", 8080)
        with self.assertRaises(ValueError):
            ProxyChecker.checkAllDetailed([proxy], retries=-1)
        with self.assertRaises(ValueError):
            ProxyChecker.checkAllDetailed([proxy], retry_backoff=-0.5)

    def test_check_all_detailed_forwards_retries(self):
        proxy = Proxy("1.2.3.4", 8080)
        with mock.patch.object(
                Proxy, "check_detailed", autospec=True,
                return_value=CheckResult(proxy, "u", True)) as check:
            ProxyChecker.checkAllDetailed([proxy], retries=2,
                                          retry_backoff=0.1)
        check.assert_called_once_with(
            proxy, "https://httpbin.org/get", 5, 2, 0.1)

    def test_check_all_detailed_aggregates(self):
        proxies = [
            Proxy("1.2.3.4", 8080),
            Proxy("5.6.7.8", 1080, ProxyType.SOCKS5),
            Proxy("9.9.9.9", 8080),
        ]
        outcomes = {
            proxies[0]: CheckResult(proxies[0], "https://example.com", True,
                                    200, "OK", 0.2),
            proxies[1]: CheckResult(proxies[1], "https://example.com", False,
                                    None, "", 0.4, "timed out",
                                    "ReadTimeout"),
            proxies[2]: CheckResult(proxies[2], "https://example.com", True,
                                    301, "Moved Permanently", 0.1),
        }
        with mock.patch.object(
                Proxy, "check_detailed", autospec=True,
                side_effect=lambda self, url, timeout=5, retries=0,
                retry_backoff=0.0: outcomes[self]):
            report = ProxyChecker.checkAllDetailed(proxies, threads=2)

        self.assertIsInstance(report, CheckReport)
        self.assertEqual([result.proxy for result in report], proxies)
        self.assertEqual(report.total, 3)
        self.assertEqual(len(report), 3)
        self.assertEqual(report.success_count, 2)
        self.assertEqual(report.failure_count, 1)
        self.assertEqual(report.working, {proxies[0], proxies[2]})
        self.assertEqual(report.failed, {proxies[1]})
        self.assertAlmostEqual(report.success_rate, 2 / 3)
        self.assertEqual(report.status_codes, {200: 1, 301: 1})
        self.assertEqual(report.errors, {"ReadTimeout": 1})
        self.assertEqual(report.results, tuple(outcomes[p] for p in proxies))
        self.assertIn("2/3 working", report.summary())
        self.assertIn("ReadTimeout x1", report.summary())
        self.assertIn("CheckReport", repr(report))

        payload = report.asDict()
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["status_codes"], {"200": 1, "301": 1})
        self.assertEqual(payload["errors"], {"ReadTimeout": 1})
        self.assertEqual(len(payload["results"]), 3)
        self.assertEqual(json.loads(report.to_json())["success_count"], 2)
        json.dumps(payload)

    def test_check_all_detailed_empty_duplicates_and_validation(self):
        empty = ProxyChecker.checkAllDetailed([])
        self.assertEqual(empty.total, 0)
        self.assertEqual(empty.success_rate, 0.0)
        self.assertEqual(empty.working, set())
        self.assertEqual(empty.summary(), "No proxies checked.")

        proxy = Proxy("1.2.3.4", 8080)
        with mock.patch.object(
                Proxy, "check_detailed", autospec=True,
                return_value=CheckResult(proxy, "u", True)):
            report = ProxyChecker.checkAllDetailed([proxy, proxy], threads=1)
        self.assertEqual(report.total, 1)
        self.assertEqual(report.working, {proxy})

        with self.assertRaises(ValueError):
            ProxyChecker.checkAllDetailed([proxy], threads=0)

    def test_check_detailed_with_local_http_proxy(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            proxy = Proxy("127.0.0.1", server.server_port)
            result = proxy.check_detailed("http://example.com", timeout=2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

        self.assertTrue(result.success)
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.error)
        self.assertGreaterEqual(result.elapsed, 0.0)


class PatternTests(unittest.TestCase):

    def test_port_pattern(self):
        self.assertFalse(Patterns.Port.match(""))
        self.assertTrue(Patterns.Port.match("00080"))
        self.assertTrue(Patterns.Port.match("65535"))
        self.assertFalse(Patterns.Port.match("65536"))

    def test_ipv6_pattern_requires_a_colon(self):
        self.assertIsNone(Patterns.IPv6.match("1.2.3.4"))
        self.assertIsNone(Patterns.IPv6.match("[1.2.3.4]"))
        self.assertIsNotNone(Patterns.IPv6.match("2001:db8::1"))
        self.assertIsNotNone(Patterns.IPv6.match("[2001:db8::1]"))
        self.assertIsNotNone(Patterns.IPv6.match("fe80::1%eth0"))

    def test_proxy_pattern_auth_and_ipv6(self):
        auth = Patterns.Proxy.search("http://user:pass@1.2.3.4:8080")
        self.assertEqual(auth.group(2), "1.2.3.4")
        self.assertEqual(auth.group(3), "8080")
        ipv6 = Patterns.Proxy.search("socks5://[2001:db8::1]:1080")
        self.assertEqual(ipv6.group(2), "[2001:db8::1]")
        self.assertEqual(ipv6.group(3), "1080")


class RandomTests(unittest.TestCase):

    def test_random_ranges_and_choice(self):
        for _ in range(1000):
            self.assertIn(Random.rand_int(3, 7), range(3, 8))
            self.assertIn(Random.rand_choice("a", "b"), ("a", "b"))
            self.assertGreaterEqual(Random.rand_float(2, 3), 2)
            self.assertLess(Random.rand_float(2, 3), 3)
        self.assertEqual(Random.rand_int(5, 5), 5)
        self.assertEqual(Random.rand_bits(0), 0)
        self.assertIn(Random.rand_bits(1), (0, 1))

    def test_random_strings_and_ips(self):
        value = Random.rand_str(32)
        self.assertEqual(len(value), 32)
        self.assertTrue(all(char.isascii() for char in value))
        chars = Random.rand_char(32)
        self.assertEqual(len(chars), 32)
        self.assertTrue(all(32 <= ord(char) <= 126 for char in chars))
        ip_address(Random.rand_ipv4())
        ip_address(Random.rand_ipv6())

    def test_random_errors(self):
        with self.assertRaises(ValueError):
            Random.rand_choice()
        with self.assertRaises(ValueError):
            Random.rand_int(5, 4)
        with self.assertRaises(ValueError):
            Random.rand_bits(-1)


if __name__ == "__main__":
    unittest.main()
