#!/usr/bin/env python3
"""Download a current GeoLite2-Country database into the package.

This is a thin wrapper around ``python -m PyRoxy.GeoIP.updater``.  The default
source is a public GeoLite2 mirror; pass your own MaxMind download URL with
``--url`` (or set ``PYROXY_GEOIP_URL``).  Use ``--check`` to report whether the
local database is stale and ``--if-outdated`` to download only when it is.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyRoxy.GeoIP.updater import main  # noqa: E402

if __name__ == "__main__":
    main()
