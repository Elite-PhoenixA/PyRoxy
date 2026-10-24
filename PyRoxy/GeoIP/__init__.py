"""Lazy GeoIP lookups with a bundled GeoLite2-Country database.

The database is opened on the first lookup.  It can be refreshed with
:func:`update` (always download) or :func:`ensure_current` (download only when
the local copy is older than ``max_age_days``)::

    from PyRoxy import GeoIP

    GeoIP.ensure_current(max_age_days=30)
    print(GeoIP.get("8.8.8.8")["country"]["iso_code"])
"""

import os as _os
from atexit import register as _register
from pathlib import Path as _path
from threading import Lock as _Lock

from maxminddb import open_database as _open

_PACKAGE_DIR = _path(__file__).parent
_DEFAULT_DB = _PACKAGE_DIR / "Sqlite/GeoLite2-Country.mmdb"
_DB_FILENAME = "GeoLite2-Country.mmdb"

__all__ = [
    "get", "get_with_prefix_len", "close", "reload", "database_path",
    "cache_path", "metadata", "update", "is_outdated", "ensure_current",
    "database_age"
]

_reader = None
_reader_lock = _Lock()


def cache_path():
    """Return the per-user database path used when the package DB is
    read-only.

    ``PYROXY_GEOIP_HOME`` overrides the cache directory; otherwise the
    platform cache directory (``%LOCALAPPDATA%`` on Windows,
    ``$XDG_CACHE_HOME`` or ``~/.cache`` elsewhere) is used.
    """
    override = _os.environ.get("PYROXY_GEOIP_HOME")
    if override:
        return _path(override).expanduser() / _DB_FILENAME

    local_app_data = _os.environ.get("LOCALAPPDATA")
    if _os.name == "nt" and local_app_data:
        return _path(local_app_data) / "PyRoxy" / _DB_FILENAME

    xdg_cache = _os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return _path(xdg_cache).expanduser() / "pyroxy" / _DB_FILENAME
    return _path.home() / ".cache" / "pyroxy" / _DB_FILENAME


def _initial_database_path():
    configured = _os.environ.get("PYROXY_GEOIP_DB")
    if configured:
        return _path(configured).expanduser()
    cached = cache_path()
    # A database installed by GeoIP.update() takes precedence over the
    # bundled copy shipped with the package.
    if cached.is_file():
        return cached
    return _DEFAULT_DB


_DB_PATH = _initial_database_path()


def _get_reader():
    global _reader

    if _reader is None:
        with _reader_lock:
            if _reader is None:
                _reader = _open(str(_DB_PATH))
    return _reader


def _lookup_key(ip):
    """Drop an IPv6 zone id, which MaxMind databases cannot contain.

    ``ipaddress`` accepts scoped link-local literals such as
    ``fe80::1%eth0``; MaxMind does not, so the scope is removed here instead
    of raising :class:`ValueError` from deep inside the reader.
    """
    if isinstance(ip, str) and "%" in ip:
        return ip.split("%", 1)[0]
    return ip


def get(ip: str):
    return _get_reader().get(_lookup_key(ip))


def get_with_prefix_len(ip: str):
    return _get_reader().get_with_prefix_len(_lookup_key(ip))


def database_path():
    """Return the path of the currently configured GeoIP database."""
    return _DB_PATH


def metadata():
    """Return MaxMind metadata for the active database."""
    return _get_reader().metadata()


def close():
    """Close the lazily opened GeoIP database, if it is open."""
    global _reader

    with _reader_lock:
        if _reader is not None:
            _reader.close()
            _reader = None


def reload(path=None):
    """Close and reopen the database, optionally using a new path.

    This makes it possible to use a newer GeoLite2 database without
    reinstalling the package:
        GeoIP.reload("path/to/GeoLite2-Country.mmdb")

    A new path is opened *before* the current reader is replaced, so a missing
    or invalid file raises without disturbing the database already in use.
    """
    global _DB_PATH, _reader

    if path is None:
        with _reader_lock:
            if _reader is not None:
                _reader.close()
                _reader = None
        return _get_reader()

    new_path = _path(path).expanduser()
    reader = _open(str(new_path))
    with _reader_lock:
        previous = _reader
        _reader = reader
        _DB_PATH = new_path
    if previous is not None:
        previous.close()
    return reader


def update(*args, **kwargs):
    """Download and atomically install a GeoLite2-Country database.

    See :func:`PyRoxy.GeoIP.updater.update` for the full signature.
    """
    from .updater import update as _update
    return _update(*args, **kwargs)


def is_outdated(max_age_days=30, path=None):
    """Return True when the database is missing, invalid or too old."""
    from .updater import is_outdated as _is_outdated
    return _is_outdated(max_age_days=max_age_days, path=path)


def database_age(path=None):
    """Return the age of the database in days."""
    from .updater import database_age as _database_age
    return _database_age(path=path)


def ensure_current(*args, **kwargs):
    """Update the database only when it is older than ``max_age_days``.

    See :func:`PyRoxy.GeoIP.updater.ensure_current`.
    """
    from .updater import ensure_current as _ensure_current
    return _ensure_current(*args, **kwargs)


_register(close)
