import sys
from pathlib import Path

from PyRoxy import ProxyChecker, ProxyUtiles

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python test.py <proxy-list-file>")
        raise SystemExit(2)

    path = Path(sys.argv[1])
    proxies = ProxyUtiles.readFromFile(path)
    print("Parsed proxies:", len(proxies))
    print("Working proxies:", len(ProxyChecker.checkAll(proxies)))
