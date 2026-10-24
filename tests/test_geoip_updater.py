import contextlib
import io
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import requests

from PyRoxy import GeoIP
from PyRoxy.GeoIP import updater

BUNDLED = Path(GeoIP.__file__).parent / "Sqlite" / "GeoLite2-Country.mmdb"
PAYLOAD = BUNDLED.read_bytes()


class FakeResponse:
    def __init__(self, payload=PAYLOAD, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.read = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                "HTTP %d" % self.status_code, response=self)

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self.payload), chunk_size):
            self.read += 1
            yield self.payload[start:start + chunk_size]


def fake_get(response=None, error=None, calls=None):
    def get(url, stream=False, timeout=None):
        if calls is not None:
            calls.append(url)
        if error is not None:
            raise error
        return response() if callable(response) else response

    return get


class UpdaterTestCase(unittest.TestCase):

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.addCleanup(GeoIP.close)
        self.addCleanup(GeoIP.reload, str(BUNDLED))
        self.addCleanup(GeoIP.close)
        self.directory = Path(self._temporary.name)

    def target(self, name="GeoLite2-Country.mmdb"):
        return self.directory / name


class ValidationTests(UpdaterTestCase):

    def test_rejects_non_mmdb_file(self):
        path = self.target("garbage.mmdb")
        path.write_bytes(b"not an mmdb")
        with self.assertRaises(updater.GeoIPUpdateError):
            updater._validate(path)

    def test_read_metadata_missing_file(self):
        with self.assertRaises(updater.GeoIPUpdateError):
            updater.read_metadata(self.target("missing.mmdb"))

    def test_read_metadata_of_bundled_database(self):
        metadata = updater.read_metadata(BUNDLED)
        self.assertEqual(metadata.database_type, "GeoLite2-Country")
        self.assertGreater(metadata.build_epoch, 0)

    def test_resolve_target_defaults_to_active_database(self):
        self.assertEqual(updater._resolve_target(),
                         Path(GeoIP.database_path()).resolve())


class DownloadTests(UpdaterTestCase):

    def test_install_replaces_database_and_leaves_no_temporary(self):
        target = self.target()
        target.write_bytes(b"old")
        with mock.patch.object(updater.requests, "get",
                               fake_get(FakeResponse())):
            metadata = updater.update(
                url="https://example.invalid/db",
                path=target,
                reload=False,
                retries=0,
            )
        self.assertEqual(metadata.database_type, "GeoLite2-Country")
        self.assertEqual(target.read_bytes(), PAYLOAD)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()),
                         [target.name])
        self.assertEqual(updater.read_metadata(target).database_type,
                         "GeoLite2-Country")

    def test_failed_download_keeps_old_database(self):
        target = self.target()
        target.write_bytes(b"old database")
        with mock.patch.object(
                updater.requests, "get",
                fake_get(error=requests.ConnectionError("boom"))):
            with self.assertRaises(updater.GeoIPUpdateError):
                updater.update(url="https://example.invalid/db",
                               path=target, retries=0)
        self.assertEqual(target.read_bytes(), b"old database")
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()),
                         [target.name])

    def test_invalid_download_keeps_old_database(self):
        target = self.target()
        target.write_bytes(b"old database")
        with mock.patch.object(updater.requests, "get",
                               fake_get(FakeResponse(payload=b"html"))):
            with self.assertRaises(updater.GeoIPUpdateError):
                updater.update(url="https://example.invalid/db",
                               path=target, retries=0)
        self.assertEqual(target.read_bytes(), b"old database")

    def test_sha256_mismatch_is_rejected(self):
        target = self.target()
        target.write_bytes(b"old database")
        with mock.patch.object(updater.requests, "get",
                               fake_get(FakeResponse())):
            with self.assertRaises(updater.GeoIPUpdateError):
                updater.update(url="https://example.invalid/db",
                               path=target,
                               expected_sha256="0" * 64,
                               retries=0)
        self.assertEqual(target.read_bytes(), b"old database")

    def test_sha256_match_is_accepted(self):
        import hashlib
        target = self.target()
        with mock.patch.object(updater.requests, "get",
                               fake_get(FakeResponse())):
            metadata = updater.update(
                url="https://example.invalid/db",
                path=target,
                expected_sha256=hashlib.sha256(PAYLOAD).hexdigest().upper(),
                reload=False,
                retries=0,
            )
        self.assertEqual(metadata.database_type, "GeoLite2-Country")

    def test_retries_transient_failure(self):
        target = self.target()
        calls = []
        responses = [requests.ConnectionError("flaky"), FakeResponse()]

        def get(url, stream=False, timeout=None):
            calls.append(url)
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch.object(updater.requests, "get", get), \
                mock.patch.object(updater.time, "sleep") as sleep, \
                mock.patch.object(updater.logger, "warning"):
            updater.update(url="https://example.invalid/db", path=target,
                           reload=False, retries=1)
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once()
        self.assertEqual(updater.read_metadata(target).database_type,
                         "GeoLite2-Country")

    def test_client_error_is_not_retried(self):
        target = self.target()
        calls = []
        with mock.patch.object(
                updater.requests, "get",
                fake_get(FakeResponse(status_code=404), calls=calls)):
            with self.assertRaises(requests.HTTPError):
                updater.update(url="https://example.invalid/db",
                               path=target, retries=3)
        self.assertEqual(len(calls), 1)

    def test_server_error_is_retried(self):
        target = self.target()
        calls = []
        responses = [FakeResponse(status_code=503), FakeResponse()]

        def get(url, stream=False, timeout=None):
            calls.append(url)
            return responses.pop(0)

        with mock.patch.object(updater.requests, "get", get), \
                mock.patch.object(updater.time, "sleep"), \
                mock.patch.object(updater.logger, "warning"):
            updater.update(url="https://example.invalid/db", path=target,
                           reload=False, retries=1)
        self.assertEqual(len(calls), 2)


class LocalServerTests(UpdaterTestCase):

    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/GeoLite2-Country.mmdb":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(PAYLOAD)))
                self.send_header("Content-Type", "application/octet-stream")
                self.end_headers()
                self.wfile.write(PAYLOAD)

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.url = ("http://127.0.0.1:%d/GeoLite2-Country.mmdb"
                   % cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_update_downloads_over_http(self):
        target = self.target()
        metadata = updater.update(url=self.url, path=target, reload=False,
                                  retries=0)
        self.assertEqual(metadata.database_type, "GeoLite2-Country")
        self.assertEqual(target.read_bytes(), PAYLOAD)

    def test_cli_flow_over_http(self):
        target = self.target()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                contextlib.redirect_stderr(io.StringIO()):
            updater.main(["--if-outdated", "--url", self.url,
                          "--output", str(target), "--max-age", "-1",
                          "--no-reload"])
        self.assertIn("GeoLite2-Country", output.getvalue())
        self.assertEqual(target.read_bytes(), PAYLOAD)

        with contextlib.redirect_stdout(output):
            updater.main(["--check", "--output", str(target)])
        self.assertIn("up to date", output.getvalue())

    def test_missing_remote_file_fails(self):
        with self.assertRaises(requests.HTTPError):
            updater.update(url=self.url.replace(".mmdb", "-404.mmdb"),
                           path=self.target(), retries=0)


class StalenessTests(UpdaterTestCase):

    def test_fresh_database_is_not_outdated(self):
        self.assertFalse(
            updater.is_outdated(max_age_days=100000, path=BUNDLED))
        self.assertFalse(updater.is_outdated(max_age_days=None, path=BUNDLED))

    def test_zero_max_age_marks_database_outdated(self):
        self.assertTrue(updater.is_outdated(max_age_days=-1, path=BUNDLED))

    def test_missing_or_invalid_database_is_outdated(self):
        self.assertTrue(updater.is_outdated(path=self.target("missing.mmdb")))
        broken = self.target("broken.mmdb")
        broken.write_bytes(b"nope")
        self.assertTrue(updater.is_outdated(path=broken))

    def test_database_age(self):
        age = updater.database_age(BUNDLED)
        self.assertGreaterEqual(age, 0)
        self.assertLess(age, 3650)


class EnsureCurrentTests(UpdaterTestCase):

    def test_fresh_database_does_not_download(self):
        target = self.target()
        target.write_bytes(PAYLOAD)
        calls = []
        with mock.patch.object(updater.requests, "get",
                               fake_get(FakeResponse(), calls=calls)):
            updated = updater.ensure_current(max_age_days=100000,
                                             path=target)
        self.assertFalse(updated)
        self.assertEqual(calls, [])

    def test_outdated_database_downloads(self):
        target = self.target()
        calls = []
        with mock.patch.object(updater.requests, "get",
                               fake_get(FakeResponse(), calls=calls)):
            updated = updater.ensure_current(max_age_days=-1, path=target,
                                             reload=False)
        self.assertTrue(updated)
        self.assertEqual(len(calls), 1)
        self.assertEqual(updater.read_metadata(target).database_type,
                         "GeoLite2-Country")

    def test_missing_cache_uses_fresh_active_database(self):
        cache = self.target("cache") / "GeoLite2-Country.mmdb"
        calls = []
        with mock.patch.object(updater, "default_target",
                               return_value=cache), \
                mock.patch.object(GeoIP, "database_path",
                                  return_value=BUNDLED), \
                mock.patch.object(updater, "update") as update, \
                mock.patch.object(updater.requests, "get",
                                  fake_get(FakeResponse(), calls=calls)):
            updated = updater.ensure_current(max_age_days=100000)
        self.assertFalse(updated)
        self.assertEqual(calls, [])
        update.assert_not_called()
        self.assertFalse(cache.exists())

    def test_missing_cache_with_outdated_active_database_downloads(self):
        cache = self.target("cache") / "GeoLite2-Country.mmdb"
        calls = []
        with mock.patch.object(updater, "default_target",
                               return_value=cache), \
                mock.patch.object(GeoIP, "database_path",
                                  return_value=BUNDLED), \
                mock.patch.object(updater.requests, "get",
                                  fake_get(FakeResponse(), calls=calls)):
            updated = updater.ensure_current(max_age_days=-1, reload=False)
        self.assertTrue(updated)
        self.assertEqual(len(calls), 1)
        self.assertTrue(cache.is_file())

    def test_explicit_missing_path_still_downloads(self):
        target = self.target("explicit.mmdb")
        calls = []
        with mock.patch.object(GeoIP, "database_path",
                               return_value=BUNDLED), \
                mock.patch.object(updater.requests, "get",
                                  fake_get(FakeResponse(), calls=calls)):
            updated = updater.ensure_current(max_age_days=100000,
                                             path=target, reload=False)
        self.assertTrue(updated)
        self.assertEqual(len(calls), 1)
        self.assertTrue(target.is_file())

    def test_update_failure_is_tolerated_by_default(self):
        target = self.target()
        with mock.patch.object(
                updater.requests, "get",
                fake_get(error=requests.ConnectionError("offline"))), \
                mock.patch.object(updater.logger, "warning"):
            self.assertFalse(updater.ensure_current(
                max_age_days=-1, path=target, retries=0))
        self.assertFalse(target.exists())

    def test_update_failure_can_be_raised(self):
        target = self.target()
        with mock.patch.object(
                updater.requests, "get",
                fake_get(error=requests.ConnectionError("offline"))):
            with self.assertRaises(updater.GeoIPUpdateError):
                updater.ensure_current(max_age_days=-1, path=target,
                                       retries=0, raise_on_error=True)


class PackageApiTests(UpdaterTestCase):

    def test_package_helpers_delegate_to_updater(self):
        with mock.patch.object(updater, "update",
                               return_value="metadata") as update:
            self.assertEqual(GeoIP.update(path=self.target()), "metadata")
        update.assert_called_once()

        with mock.patch.object(updater, "ensure_current",
                               return_value=True) as ensure_current:
            self.assertTrue(GeoIP.ensure_current(max_age_days=7))
        ensure_current.assert_called_once_with(max_age_days=7)

        with mock.patch.object(updater, "is_outdated",
                               return_value=True) as is_outdated:
            self.assertTrue(GeoIP.is_outdated(max_age_days=3))
        is_outdated.assert_called_once_with(max_age_days=3, path=None)

        with mock.patch.object(updater, "database_age", return_value=4.5):
            self.assertEqual(GeoIP.database_age(), 4.5)

    def test_package_update_installs_and_reloads(self):
        target = self.target()
        with mock.patch.object(updater.requests, "get",
                               fake_get(FakeResponse())):
            GeoIP.update(url="https://example.invalid/db", path=target,
                         retries=0)
        self.assertEqual(GeoIP.database_path(), target)
        self.assertEqual(GeoIP.get("8.8.8.8")["country"]["iso_code"], "US")


class TargetTests(UpdaterTestCase):

    def test_explicit_environment_database_wins(self):
        path = self.target("custom.mmdb")
        with mock.patch.dict(os.environ, {"PYROXY_GEOIP_DB": str(path)}):
            self.assertEqual(updater.default_target(), path.resolve())

    def test_active_database_is_used_when_writable(self):
        with mock.patch.dict(os.environ, {"PYROXY_GEOIP_DB": ""}):
            self.assertEqual(updater.default_target(),
                             Path(GeoIP.database_path()).resolve())

    def test_cache_is_used_when_package_database_is_read_only(self):
        cached = self.target("cache.mmdb")
        with mock.patch.dict(os.environ, {"PYROXY_GEOIP_DB": ""}), \
                mock.patch.object(updater, "_is_writable",
                                  return_value=False), \
                mock.patch.object(GeoIP, "cache_path", return_value=cached):
            self.assertEqual(updater.default_target(), cached.resolve())

    def test_cache_path_environment_override(self):
        with mock.patch.dict(os.environ,
                             {"PYROXY_GEOIP_HOME": str(self.directory)}):
            self.assertEqual(GeoIP.cache_path(),
                             self.directory / "GeoLite2-Country.mmdb")

    @unittest.skipIf(os.name == "nt", "XDG_CACHE_HOME is POSIX only")
    def test_cache_path_honours_xdg_cache_home(self):
        environment = {"XDG_CACHE_HOME": str(self.directory)}
        with mock.patch.dict(os.environ, environment):
            os.environ.pop("PYROXY_GEOIP_HOME", None)
            self.assertEqual(GeoIP.cache_path(),
                             self.directory / "pyroxy"
                             / "GeoLite2-Country.mmdb")


class CommandLineTests(UpdaterTestCase):

    def _run(self, argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                contextlib.redirect_stderr(io.StringIO()):
            updater.main(argv)
        return output.getvalue()

    def test_check_reports_up_to_date(self):
        target = self.target()
        target.write_bytes(PAYLOAD)
        text = self._run(["--check", "--output", str(target)])
        self.assertIn("up to date", text)
        self.assertIn("GeoLite2-Country", text)

    def test_check_exits_one_when_outdated(self):
        target = self.target()
        target.write_bytes(PAYLOAD)
        with self.assertRaises(SystemExit) as caught:
            self._run(["--check", "--output", str(target), "--max-age", "-1"])
        self.assertEqual(caught.exception.code, updater.EXIT_OUTDATED)

    def test_check_exits_one_when_missing(self):
        with self.assertRaises(SystemExit) as caught:
            self._run(["--check", "--output",
                       str(self.target("missing.mmdb"))])
        self.assertEqual(caught.exception.code, updater.EXIT_OUTDATED)

    def test_if_outdated_skips_current_database(self):
        target = self.target()
        target.write_bytes(PAYLOAD)
        with mock.patch.object(updater.requests, "get",
                               side_effect=fake_get(FakeResponse())) as get:
            text = self._run(["--if-outdated", "--output", str(target),
                              "--max-age", "100000"])
        self.assertIn("Already up to date", text)
        get.assert_not_called()

    def test_if_outdated_downloads_when_stale(self):
        target = self.target()
        with mock.patch.object(updater.requests, "get",
                               fake_get(FakeResponse())):
            text = self._run(["--if-outdated", "--output", str(target),
                              "--max-age", "-1", "--no-reload"])
        self.assertIn("GeoLite2-Country", text)
        self.assertTrue(target.is_file())

    def test_errors_exit_with_status_two(self):
        target = self.target()
        with mock.patch.object(
                updater.requests, "get",
                fake_get(error=requests.ConnectionError("offline"))):
            with self.assertRaises(SystemExit) as caught:
                self._run(["--output", str(target), "--retries", "0"])
        self.assertEqual(caught.exception.code, updater.EXIT_ERROR)


if __name__ == "__main__":
    unittest.main()
