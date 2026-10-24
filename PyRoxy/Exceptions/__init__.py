__all__ = ["ProxyInvalidHost", "ProxyInvalidPort", "ProxyParseError"]


class ProxyParseError(Exception):
    pass


class ProxyInvalidPort(ProxyParseError):

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


class ProxyInvalidHost(ProxyParseError):

    def __init__(self, host: str):
        ProxyParseError.__init__(self, "'%s' is an invalid proxy host" % host)
