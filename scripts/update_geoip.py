#!/usr/bin/env python3
"""Download a current GeoLite2-Country database into the package.

The default source is a public GeoLite2 mirror.  If you have a MaxMind
account/licence, pass your own download URL with ``--url`` (or set
``PYROXY_GEOIP_URL``).  The new file is validated as a Country MMDB before it
atomically replaces the bundled database.
"""

import argparse
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from maxminddb import open_database

DEFAULT_URL = (
    "https://github.com/P3TERX/GeoLite.mmdb/raw/download/"
    "GeoLite2-Country.mmdb"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = (
    PROJECT_ROOT / "PyRoxy" / "GeoIP" / "Sqlite" / "GeoLite2-Country.mmdb"
)


def _close_package_reader():
    try:
        from PyRoxy import GeoIP
    except ImportError:
        return
    GeoIP.close()


def update(url: str, target: Path, timeout: int = 120):
    target = target.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        fd, temporary_name = tempfile.mkstemp(
            prefix=".geolite2-", suffix=".mmdb", dir=str(target.parent)
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as temporary:
                shutil.copyfileobj(response.raw, temporary)

            reader = open_database(str(temporary_path))
            try:
                metadata = reader.metadata()
            finally:
                reader.close()

            if metadata.database_type != "GeoLite2-Country":
                raise RuntimeError(
                    "downloaded database is %r, expected GeoLite2-Country"
                    % metadata.database_type
                )

            # On Windows an open MMDB reader prevents os.replace().
            _close_package_reader()
            os.replace(str(temporary_path), str(target))
            return target, metadata
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("PYROXY_GEOIP_URL", DEFAULT_URL),
        help="MMDB download URL (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_TARGET,
        help="destination path (default: bundled package database)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="download timeout in seconds (default: %(default)s)",
    )
    args = parser.parse_args()

    target, metadata = update(args.url, args.output, args.timeout)
    build_date = datetime.fromtimestamp(
        metadata.build_epoch, timezone.utc
    ).isoformat()
    print("Updated:", target)
    print("Database:", metadata.database_type)
    print("Build:", build_date)
    print("Nodes:", metadata.node_count)


if __name__ == "__main__":
    main()
