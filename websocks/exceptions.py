class WebsocksError(Exception):
    pass


class WebsocksImplementationError(WebsocksError):
    pass


class WebsocksClosed(WebsocksError):
    pass


class WebsocksRefused(WebsocksError):
    pass
