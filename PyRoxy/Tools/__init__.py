from re import compile, IGNORECASE, MULTILINE
<<<<<<< HEAD
=======
from contextlib import suppress
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
from os import urandom
from socket import inet_ntop, inet_ntoa, AF_INET6
from string import ascii_letters
from struct import pack
from struct import pack as data_pack
from sys import maxsize
<<<<<<< HEAD
from typing import Any, List
=======
from typing import Callable, Any, List
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d

__all__ = ["Patterns", "Random"]


class Random:
<<<<<<< HEAD
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
=======
    latters: List[str] = list(ascii_letters)
    rand_str: Callable[[int], str] = lambda length=16: ''.join(
        Random.rand_choice(*Random.latters) for _ in range(length))
    rand_char: Callable[[int], chr] = lambda length=16: "".join(
        [chr(Random.rand_int(0, 1000)) for _ in range(length)])
    rand_ipv4: Callable[[], str] = lambda: inet_ntoa(
        data_pack('>I', Random.rand_int(1, 0xffffffff)))
    rand_ipv6: Callable[[], str] = lambda: inet_ntop(
        AF_INET6, pack('>QQ', Random.rand_bits(64), Random.rand_bits(64)))
    rand_int: Callable[[int, int],
                       int] = lambda minimum=0, maximum=maxsize: int(
                           Random.rand_float(minimum, maximum))
    rand_choice: Callable[[List[Any]], Any] = lambda *data: data[
        (Random.rand_int(maximum=len(data) - 2) or 0)]
    rand: Callable[
        [], int] = lambda: (int.from_bytes(urandom(7), 'big') >> 3) * (2**-53)

    @staticmethod
    def rand_bits(maximum: int = 255) -> int:
        numbytes = (maximum + 7) // 8
        return int.from_bytes(urandom(numbytes),
                              'big') >> (numbytes * 8 - maximum)
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d

    @staticmethod
    def rand_float(minimum: float = 0.0,
                   maximum: float = (maxsize * 1.0)) -> float:
<<<<<<< HEAD
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
=======
        with suppress(ZeroDivisionError):
            return abs((Random.rand() * maximum) % (minimum -
                                                    (maximum + 1))) + minimum
        return 0.0
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d


class Patterns:
    Port = compile(
<<<<<<< HEAD
        r"^0*(?:6553[0-5]|655[0-2][0-9]|65[0-4][0-9]{2}|"
        r"6[0-4][0-9]{3}|[1-5][0-9]{4}|[1-9][0-9]{0,3}|0)$")
    IP = compile(r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)")
    IPPort = compile(r"^((?:\d{1,3}\.){3}\d{1,3}):(\d{1,5})$")
    Proxy = compile(
        r"^(?:\[|)(?:\s+|)((?:socks[45]h?|http(?:s|)))"
        r"(?:[]|]|)(?:\s+|)"
        r"(?:](?:\s+|)|\|(?:\s+|)|://(?:\s+|)|)"
        r"(?:(?:[^@\s/]+)@)?"
        r"((?:(?:\d{1,3}\.){3}\d{1,3}|\[[0-9A-Fa-f:]+\]|\S+[.]\w{2,}))"
        r"(?:[:]|)((?:\d+|))"
        r"(?::(.+):(.+)|)$", IGNORECASE | MULTILINE)
    URL = compile(r"\S+[.]\w{2,}")
=======
        "^((6553[0-5])|(655[0-2][0-9])|(65[0-4][0-9]"
        "{2})|(6[0-4][0-9]{3})|([1-5][0-9]{4})|([0-5]{0,5})|([0-9]{1,4}))$")
    IP = compile("(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)")
    IPPort = compile("^((?:\d{1,3}\.){3}\d{1,3}):(\d{1,5})$")
    Proxy = compile(
        r"^(?:\[|)(?:\s+|)((?:socks[45]|http(?:s|)))(?:[]|]|)(?:\s+|)(?:](?:\s+|)|\|(?:\s+|)|://(?:\s+|)|)"
        r"((?:(?:\d+.){3}\d+|\S+[.]\w{2,3}))"
        r"(?:[:]|)((?:\d+|))"
        r"(?::(.+):(.+)|)$", IGNORECASE | MULTILINE)
    URL = compile("\S+[.]\w{2,3}")
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
