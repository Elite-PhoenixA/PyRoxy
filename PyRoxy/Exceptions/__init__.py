__all__ = ["ProxyInvalidHost", "ProxyInvalidPort", "ProxyParseError"]


class ProxyParseError(Exception):
    pass


class ProxyInvalidPort(ProxyParseError):

<<<<<<< HEAD
    def __init__(self, port):
        text = str(port)
        try:
            if isinstance(port, bool):
                raise ValueError
            value = int(port)
        except (TypeError, ValueError):
            message = "'%s' is an invalid port" % text
        else:
            message = "'%s' is too %s" % (
                text, "small" if value < 1 else "long")
        ProxyParseError.__init__(self, message)
=======
    def __init__(self, port: int):
        ProxyParseError.__init__(
            self, "'%d' is too %s" % (port, "small" if port < 1 else "long"))
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d


class ProxyInvalidHost(ProxyParseError):

    def __init__(self, host: str):
<<<<<<< HEAD
        ProxyParseError.__init__(self, "'%s' is an invalid proxy host" % host)
=======
        ProxyParseError.__init__(self, "'%s' is an Invalid IP Address" % host)
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
