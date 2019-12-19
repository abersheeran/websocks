from websocks.rule import judge


def test_ipv4():
    assert not judge("127.0.0.1")
    assert not judge("192.168.0.100")
    assert judge("172.15.1.1")
    assert not judge("172.16.0.0")
    assert judge("1.1.1.1")
    assert judge("8.8.8.8")


def test_domain():
    assert judge("google.com")
    assert judge("translate.google.com")
    assert not judge("google.cn")
    assert not judge("translate.google.cn")
    assert not judge("bilibili.com")
