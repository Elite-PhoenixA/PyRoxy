from re import compile, IGNORECASE, MULTILINE
from os import urandom
from socket import inet_ntop, inet_ntoa, AF_INET6
from string import ascii_letters
from struct import pack
from struct import pack as data_pack
from sys import maxsize
from typing import Any, List

__all__ = ["Patterns", "Random"]


class Random:
    letters: List[str] = list(ascii_letters)
    latters: List[str] = letters

    @staticmethod
    def rand():
        return (int.from_bytes(urandom(7), "big") >> 3) * (2 ** -53)

    @staticmethod
    def rand_bits(maximum: int = 255) -> int:
        if maximum < 0:
            raise ValueError("maximum must not be negative")
        if maximum == 0:
            return 0
        numbytes = (maximum + 7) // 8
        return int.from_bytes(urandom(numbytes),
                              "big") >> (numbytes * 8 - maximum)

    @staticmethod
    def rand_float(minimum: float = 0.0,
                   maximum: float = (maxsize * 1.0)) -> float:
        if maximum < minimum:
            raise ValueError("maximum must not be less than minimum")
        if maximum == minimum:
            return float(minimum)
        return minimum + (maximum - minimum) * Random.rand()

    @staticmethod
    def rand_int(minimum: int = 0, maximum: int = maxsize) -> int:
        minimum = int(minimum)
        maximum = int(maximum)
        if maximum < minimum:
            raise ValueError("maximum must not be less than minimum")
        if maximum == minimum:
            return minimum
        return minimum + int(Random.rand() * (maximum - minimum + 1))

    @staticmethod
    def rand_choice(*data: Any) -> Any:
        if not data:
            raise ValueError("rand_choice requires at least one value")
        return data[Random.rand_int(0, len(data) - 1)]

    @staticmethod
    def rand_str(length: int = 16) -> str:
        if length < 0:
            raise ValueError("length must not be negative")
        return "".join(
            Random.rand_choice(*Random.latters) for _ in range(length))

    @staticmethod
    def rand_char(length: int = 16) -> str:
        if length < 0:
            raise ValueError("length must not be negative")
        return "".join(
            chr(Random.rand_int(32, 126)) for _ in range(length))

    @staticmethod
    def rand_ipv4() -> str:
        return inet_ntoa(data_pack(">I", Random.rand_int(1, 0xffffffff)))

    @staticmethod
    def rand_ipv6() -> str:
        return inet_ntop(
            AF_INET6, pack(">QQ", Random.rand_bits(64),
                           Random.rand_bits(64)))


class Patterns:
    Port = compile(
        r"^0*(?:6553[0-5]|655[0-2][0-9]|65[0-4][0-9]{2}|"
        r"6[0-4][0-9]{3}|[1-5][0-9]{4}|[1-9][0-9]{0,3}|0)$")
    IP = compile(r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)")
    # IPv4 endpoints keep the historical two-group layout so existing callers
    # of ``group(1)``/``group(2)`` keep working.  IPv6 endpoints are matched by
    # ``HostPort`` because a compressed literal cannot be parsed unambiguously
    # without the surrounding brackets.
    IPPort = compile(r"^((?:\d{1,3}\.){3}\d{1,3}):(\d{1,5})$")
    IPv6 = compile(
        r"^\[?(?=[^\]]*:)([0-9A-Fa-f:.]+(?:%[0-9A-Za-z._~-]+)?)\]?$")
    HostPort = compile(
        r"^(?:\[(?P<ipv6>[0-9A-Fa-f:.]+(?:%[0-9A-Za-z._~-]+)?)\]"
        r"|(?P<ipv4>(?:\d{1,3}\.){3}\d{1,3})):(?P<port>\d{1,5})$")
    Proxy = compile(
        r"^(?:\[|)(?:\s+|)((?:socks[45]h?|http(?:s|)))"
        r"(?:[]|]|)(?:\s+|)"
        r"(?:](?:\s+|)|\|(?:\s+|)|://(?:\s+|)|)"
        r"(?:(?:[^@\s/]+)@)?"
        r"((?:(?:\d{1,3}\.){3}\d{1,3}|\[[0-9A-Fa-f:]+\]|\S+[.]\w{2,}))"
        r"(?:[:]|)((?:\d+|))"
        r"(?::(.+):(.+)|)$", IGNORECASE | MULTILINE)
    URL = compile(r"\S+[.]\w{2,}")
