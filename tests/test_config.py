import pytest

from websocks.config import TCP_FORMAT, UDP_FORMAT


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


@pytest.mark.parametrize(
    "uri",
    [
        "normal://test:test@host:8900/?algorithm=chacha20-poly1305",
        "normal://test:test@HOST:679/?algorithm=aes-128-gcm",
    ],
)
def test_udp_format(uri):
    assert UDP_FORMAT.match(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "normal://test:test@host:8900/?algorithm=chacha20",
        "normal://test:test@HOST:679/?algorithm=aes-128-cbc",
        "normal://:test@example.com",
        "normal://test:@example.com",
        "normal://test:test@example.com:s1d/?algorithm=aes-128-gcm",
    ],
)
def test_error_udp_format(uri):
    assert UDP_FORMAT.match(uri) is None
