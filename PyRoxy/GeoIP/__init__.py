<<<<<<< HEAD
from atexit import register as _register
from os import environ as _environ
from pathlib import Path as _path
from threading import Lock as _Lock

from maxminddb import open_database as _open

_PACKAGE_DIR = _path(__file__).parent
_DEFAULT_DB = _PACKAGE_DIR / "Sqlite/GeoLite2-Country.mmdb"
_DB_PATH = _path(
    _environ.get("PYROXY_GEOIP_DB", str(_DEFAULT_DB))).expanduser()

__all__ = [
    "get", "get_with_prefix_len", "close", "reload", "database_path",
    "metadata"
]

_reader = None
_reader_lock = _Lock()


def _get_reader():
    global _reader

    if _reader is None:
        with _reader_lock:
            if _reader is None:
                _reader = _open(str(_DB_PATH))
    return _reader


def get(ip: str):
    return _get_reader().get(ip)


def get_with_prefix_len(ip: str):
    return _get_reader().get_with_prefix_len(ip)


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
    """
    global _DB_PATH, _reader

    with _reader_lock:
        if _reader is not None:
            _reader.close()
            _reader = None
        if path is not None:
            _DB_PATH = _path(path).expanduser()
    return _get_reader()


_register(close)
=======
from pathlib import Path as _path
from maxminddb import open_database as _open

__dir__ = _path(__file__).parent
__all__ = [ "get", "get_with_prefix_len"]

_reader = _open(__dir__ / 'Sqlite/GeoLite2-Country.mmdb')

def get(ip: str):
    return _reader.get(ip)


def get_with_prefix_len(ip: str):
    return _reader.get_with_prefix_len(ip)
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
