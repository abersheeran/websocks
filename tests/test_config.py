import pytest

from websocks.config import TCP_FORMAT


@pytest.mark.parametrize(
    "uri",
    [
        "ws://test:test@example.com",
        "ws://test:test@example.com:80",
        "wss://test:test@example.com",
        "wss://test:test@example.com:443",
    ],
)
def test_tcp_format(uri):
    assert TCP_FORMAT.match(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "ws://:test@example.com",
        "ws://test:@example.com",
        "http://test:test@example.com:80",
    ],
)
def test_error_tcp_form(uri):
    assert TCP_FORMAT.match(uri) is None
