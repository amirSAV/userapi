import pytest
from app.core.proxy import ProxyConfig
from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate, ConnectionTcpFull


def test_parse_socks5_url():
    p = ProxyConfig.parse("socks5://testuser:secretpass@127.0.0.1:1080")
    assert p.proxy_type == "socks5"
    assert p.host == "127.0.0.1"
    assert p.port == 1080
    assert p.username == "testuser"
    assert p.password == "secretpass"

    conn, args = p.get_telethon_args()
    assert conn == ConnectionTcpFull
    assert args["proxy_type"] == "socks5"
    assert args["addr"] == "127.0.0.1"
    assert args["port"] == 1080
    assert args["username"] == "testuser"


def test_parse_socks4_url():
    p = ProxyConfig.parse("socks4://192.168.1.100:1080")
    assert p.proxy_type == "socks4"
    assert p.host == "192.168.1.100"
    assert p.port == 1080

    conn, args = p.get_telethon_args()
    assert conn == ConnectionTcpFull
    assert args["proxy_type"] == "socks4"


def test_parse_http_url():
    p = ProxyConfig.parse("http://myuser:mypass@proxy.corp.com:8080")
    assert p.proxy_type == "http"
    assert p.host == "proxy.corp.com"
    assert p.port == 8080
    assert p.username == "myuser"


def test_parse_mtproto_url():
    url = "tg://proxy?server=mtproto.example.com&port=443&secret=dd0123456789abcdef0123456789abcdef"
    p = ProxyConfig.parse(url)
    assert p.proxy_type == "mtproto"
    assert p.host == "mtproto.example.com"
    assert p.port == 443
    assert p.secret == "dd0123456789abcdef0123456789abcdef"

    conn, args = p.get_telethon_args()
    assert conn == ConnectionTcpMTProxyRandomizedIntermediate
    assert args == ("mtproto.example.com", 443, "dd0123456789abcdef0123456789abcdef")


def test_parse_dict():
    data = {
        "type": "mtproto",
        "host": "mt.tg.org",
        "port": 443,
        "secret": "112233445566778899aabbccddeeff00",
    }
    p = ProxyConfig.parse(data)
    assert p.proxy_type == "mtproto"
    assert p.host == "mt.tg.org"
    assert p.secret == "112233445566778899aabbccddeeff00"

    masked = p.to_dict(mask_secret=True)
    assert masked["secret"] != "112233445566778899aabbccddeeff00"
    assert "..." in masked["secret"]


def test_invalid_proxy():
    with pytest.raises(ValueError):
        ProxyConfig.parse("ftp://invalid.proxy.com:21")

    with pytest.raises(ValueError):
        ProxyConfig.parse({"type": "mtproto", "host": "1.2.3.4", "port": 443})  # missing secret
