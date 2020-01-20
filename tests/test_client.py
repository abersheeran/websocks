from websocks.client import ServerURL


def test_server_url():
    server_url = ServerURL("wss://user:pass@localhost:443")
    assert server_url.username == "user"
    assert server_url.password == "pass"
    assert str(server_url) == "wss://localhost:443"
