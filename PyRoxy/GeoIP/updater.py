"""Download, validate and install a GeoLite2-Country MMDB.

The module is usable as a library::

    from PyRoxy import GeoIP

    GeoIP.update()                  # always download a fresh database
    GeoIP.ensure_current()          # download only when older than 30 days
    GeoIP.is_outdated(max_age_days=7)

and as a command line tool::

    python -m PyRoxy.GeoIP.updater --check
    python -m PyRoxy.GeoIP.updater --if-outdated
"""

import argparse
import hashlib
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from maxminddb import open_database

logger = logging.getLogger(__name__)

DEFAULT_URL = (
    "https://github.com/P3TERX/GeoLite.mmdb/raw/download/"
    "GeoLite2-Country.mmdb"
)
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_TIMEOUT = 120
DEFAULT_RETRIES = 2

EXIT_OK = 0
EXIT_OUTDATED = 1
EXIT_ERROR = 2

_CHUNK_SIZE = 64 * 1024
_SECONDS_PER_DAY = 24 * 60 * 60


class GeoIPUpdateError(RuntimeError):
    """Raised when a GeoIP database cannot be downloaded or validated."""


def _resolve_target(path=None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    from . import database_path
    return Path(database_path()).expanduser().resolve()


def _is_writable(path: Path) -> bool:
    """Return True when ``path`` can be replaced by this process."""
    if path.exists():
        return os.access(str(path), os.W_OK)
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return parent.is_dir() and os.access(str(parent), os.W_OK)


def default_target() -> Path:
    """Return the path an update without an explicit destination writes to.

    An explicit ``PYROXY_GEOIP_DB`` always wins.  Otherwise the active
    database is updated when it is writable (the usual case in a source
    checkout) and the per-user cache is used when the package database lives
    in a read-only location such as ``site-packages``.
    """
    from . import cache_path, database_path

    configured = os.environ.get("PYROXY_GEOIP_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    active = Path(database_path()).expanduser().resolve()
    if _is_writable(active):
        return active
    return Path(cache_path()).expanduser().resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate(path: Path):
    try:
        reader = open_database(str(path))
    except Exception as exc:
        raise GeoIPUpdateError(
            "downloaded file is not a valid MMDB database: %s" % exc
        ) from exc
    try:
        metadata = reader.metadata()
    finally:
        reader.close()

    if metadata.database_type != "GeoLite2-Country":
        raise GeoIPUpdateError(
            "downloaded database is %r, expected GeoLite2-Country"
            % metadata.database_type
        )
    return metadata


def read_metadata(path=None):
    """Return the MaxMind metadata of ``path`` without touching the reader.

    ``path`` defaults to the active database.  A missing or invalid file
    raises :class:`GeoIPUpdateError`.
    """
    target = _resolve_target(path)
    if not target.is_file():
        raise GeoIPUpdateError("GeoIP database not found: %s" % target)
    return _validate(target)


def database_age(path=None) -> float:
    """Return the age of the database in days (negative if from the future)."""
    metadata = read_metadata(path)
    now = datetime.now(timezone.utc).timestamp()
    return (now - float(metadata.build_epoch)) / _SECONDS_PER_DAY


def is_outdated(max_age_days=DEFAULT_MAX_AGE_DAYS, path=None) -> bool:
    """Return True when the database is missing, invalid or too old.

    ``max_age_days=None`` only checks that the database is present and valid.
    """
    try:
        age = database_age(path)
    except GeoIPUpdateError:
        return True
    if max_age_days is None:
        return False
    return age > float(max_age_days)


def _download_once(url: str, target: Path, timeout, expected_sha256=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".geolite2-", suffix=".mmdb", dir=str(target.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            with requests.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                    if chunk:
                        output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

        if expected_sha256:
            actual_sha256 = _sha256(temporary_path)
            expected_sha256 = expected_sha256.strip().lower()
            if actual_sha256.lower() != expected_sha256:
                raise GeoIPUpdateError(
                    "SHA-256 mismatch: expected %s, got %s"
                    % (expected_sha256, actual_sha256)
                )

        return temporary_path, _validate(temporary_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _download(url: str, target: Path, timeout, expected_sha256=None,
              retries=DEFAULT_RETRIES, backoff=0.5):
    """Download with a small bounded retry for transient failures."""
    attempts = max(0, int(retries)) + 1
    for attempt in range(attempts):
        try:
            return _download_once(url, target, timeout, expected_sha256)
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status is None or status < 500 or attempt + 1 >= attempts:
                raise
        except (requests.RequestException, OSError) as exc:
            if attempt + 1 >= attempts:
                raise GeoIPUpdateError(
                    "download from %s failed: %s" % (url, exc)
                ) from exc
        delay = backoff * (2 ** attempt)
        logger.warning("GeoIP download attempt %d failed, retrying in %.1fs",
                       attempt + 1, delay)
        time.sleep(delay)
    raise GeoIPUpdateError("download from %s failed" % url)


def update(url=None, path=None, timeout=DEFAULT_TIMEOUT,
           expected_sha256=None, reload=True, retries=DEFAULT_RETRIES):
    """Download a GeoLite2-Country database and install it atomically.

    ``url`` defaults to ``PYROXY_GEOIP_URL`` and then to a public GeoLite2
    mirror.  ``path`` defaults to :func:`default_target`, i.e. the active
    database when writable and the per-user cache otherwise.  The downloaded
    file is validated before replacing the destination; a failed download or
    validation leaves the old file intact.
    """
    from . import close as close_db
    from . import reload as reload_db

    target = default_target() if path is None else _resolve_target(path)
    source = url or os.environ.get("PYROXY_GEOIP_URL") or DEFAULT_URL
    temporary_path, metadata = _download(
        source, target, timeout, expected_sha256, retries
    )
    try:
        # Windows cannot replace a file while an MMDB reader has it open.
        close_db()
        os.replace(str(temporary_path), str(target))
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    if reload:
        reload_db(target)
    return metadata


def ensure_current(max_age_days=DEFAULT_MAX_AGE_DAYS, url=None, path=None,
                   timeout=DEFAULT_TIMEOUT, expected_sha256=None,
                   reload=True, retries=DEFAULT_RETRIES,
                   raise_on_error=False) -> bool:
    """Update the database only when it is older than ``max_age_days``.

    Returns ``True`` when a new database was installed and ``False`` when the
    existing one was already current (or, unless ``raise_on_error`` is set,
    when the update failed).  This is safe to call at application start-up:
    by default a failed download is logged and the old database stays in use.
    """
    target = default_target() if path is None else _resolve_target(path)
    if not is_outdated(max_age_days, target):
        return False
    if path is None and not target.is_file():
        # A read-only install keeps updates in the per-user cache.  Until that
        # cache exists the bundled database is still the active one, so there
        # is no reason to download a fresh copy of an already fresh file.
        from . import database_path
        active = Path(database_path()).expanduser()
        if active.is_file() and not is_outdated(max_age_days, active):
            return False
    try:
        update(url=url, path=target, timeout=timeout, reload=reload,
               expected_sha256=expected_sha256, retries=retries)
    except Exception as exc:
        if raise_on_error:
            raise
        logger.warning("GeoIP database update failed, keeping %s: %s",
                       target, exc)
        return False
    return True


def _describe(path: Path) -> str:
    metadata = read_metadata(path)
    build_date = datetime.fromtimestamp(
        metadata.build_epoch, timezone.utc
    ).isoformat()
    age = (datetime.now(timezone.utc).timestamp()
           - float(metadata.build_epoch)) / _SECONDS_PER_DAY
    return ("%s\nDatabase: %s\nBuild: %s\nAge: %.1f days"
            % (path, metadata.database_type, build_date, age))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m PyRoxy.GeoIP.updater",
        description="Download and atomically install GeoLite2-Country.mmdb.",
    )
    parser.add_argument(
        "--url",
        help="MMDB URL (default: PYROXY_GEOIP_URL or the public mirror)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="destination path (default: the active database, or the "
             "per-user cache when the package database is read-only)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="download timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--sha256",
        dest="expected_sha256",
        help="optional expected SHA-256 of the downloaded file",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="retries for transient download failures (default: %(default)s)",
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=DEFAULT_MAX_AGE_DAYS,
        metavar="DAYS",
        help="age in days after which a database counts as outdated "
             "(default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only report database status; exits 1 when outdated",
    )
    parser.add_argument(
        "--if-outdated",
        action="store_true",
        help="download only when the database is older than --max-age",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="do not activate the downloaded database in this process",
    )
    args = parser.parse_args(argv)

    target = default_target() if args.output is None else \
        _resolve_target(args.output)

    if args.check:
        try:
            report = _describe(target)
        except GeoIPUpdateError as exc:
            print("Missing or invalid:", target)
            print("Reason:", exc)
            print("Status: outdated")
            parser.exit(EXIT_OUTDATED)
        outdated = is_outdated(args.max_age, target)
        print(report)
        print("Status:", "outdated" if outdated else "up to date")
        if outdated:
            parser.exit(EXIT_OUTDATED)
        return

    try:
        if args.if_outdated:
            updated = ensure_current(
                max_age_days=args.max_age,
                url=args.url,
                path=target,
                timeout=args.timeout,
                expected_sha256=args.expected_sha256,
                reload=not args.no_reload,
                retries=args.retries,
                raise_on_error=True,
            )
            if not updated:
                print("Already up to date:", target)
                return
        else:
            update(
                url=args.url,
                path=target,
                timeout=args.timeout,
                expected_sha256=args.expected_sha256,
                reload=not args.no_reload,
                retries=args.retries,
            )
    except Exception as exc:
        parser.exit(EXIT_ERROR, "error: %s\n" % exc)

    print(_describe(target))


if __name__ == "__main__":
    main()
