class WebsocksError(Exception):
    pass


class WebsocksImplementationError(WebsocksError):
    pass


class WebsocksClosed(ConnectionResetError):
    pass


class WebsocksRefused(ConnectionRefusedError):
    pass
