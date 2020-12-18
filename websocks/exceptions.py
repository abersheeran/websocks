class WebSocksError(Exception):
    pass


class WebSocksImplementationError(WebSocksError):
    pass


class WebSocksClosed(ConnectionResetError):
    pass


class WebSocksRefused(ConnectionRefusedError):
    pass
