import os
import stat
import struct
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from socket import AF_INET, AF_INET6, SOCK_STREAM, socket
from unittest import mock

import requests
from socks import GeneralProxyError

from PyRoxy import (GeoIP, Proxy, ProxyChecker, ProxyType, ProxyUtiles)
from PyRoxy.Exceptions import ProxyInvalidPort
from PyRoxy.Tools import Patterns, Random


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

    def test_parse_normal_alias_and_bracket_ptype(self):
        self.assertEqual(
            ProxyUtiles.parseNormal(["http://1.2.3.4:8080"]),
            ProxyUtiles.parseNoraml(["http://1.2.3.4:8080"]))
        result = ProxyUtiles.parseAll(["[2001:db8::1]:1080"],
                                      ProxyType.SOCKS5)
        self.assertEqual(next(iter(result)).type, ProxyType.SOCKS5)

    def test_validation(self):
        for port in ("", "abc", None, 70000, True):
            with self.assertRaises(ProxyInvalidPort):
                Proxy("1.2.3.4", port)
        with self.assertRaises(Exception):
            Proxy("999.1.1.1", 80)
        self.assertEqual(Proxy("localhost", 8080).host, "localhost")

    def test_ipv6_socket_family(self):
        with Proxy("::1", 8080).open_socket() as sock:
            self.assertEqual(sock.family, AF_INET6)

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
        def __init__(self, status_code):
            self.status_code = status_code
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


class PatternTests(unittest.TestCase):

    def test_port_pattern(self):
        self.assertFalse(Patterns.Port.match(""))
        self.assertTrue(Patterns.Port.match("00080"))
        self.assertTrue(Patterns.Port.match("65535"))
        self.assertFalse(Patterns.Port.match("65536"))

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
