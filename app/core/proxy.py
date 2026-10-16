import re
import urllib.parse
from typing import Optional, Dict, Any, Tuple, Type
from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate, ConnectionTcpFull


class ProxyConfig:
    """Helper to parse, validate, and convert proxy specifications into Telethon parameters."""

    def __init__(
        self,
        proxy_type: str,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None,
        secret: Optional[str] = None,
        rdns: bool = True,
    ):
        self.proxy_type = proxy_type.lower()
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.secret = secret
        self.rdns = rdns

        if self.proxy_type not in ("socks5", "socks4", "http", "mtproto"):
            raise ValueError(f"Unsupported proxy type: {self.proxy_type}. Supported types: socks5, socks4, http, mtproto")

        if self.proxy_type == "mtproto" and not self.secret:
            raise ValueError("MTProto proxy requires a 'secret' parameter.")

    @classmethod
    def from_url(cls, url: str) -> "ProxyConfig":
        """Parse proxy from URL (e.g., socks5://user:pass@host:1080, tg://proxy?server=... or mtproto://secret@host:443)."""
        url = url.strip()
        if url.startswith("tg://proxy") or url.startswith("https://t.me/proxy"):
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            host = params.get("server", [""])[0]
            port = int(params.get("port", [443])[0])
            secret = params.get("secret", [""])[0]
            return cls(proxy_type="mtproto", host=host, port=port, secret=secret)

        parsed = urllib.parse.urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme in ("socks5", "socks5h"):
            proxy_type = "socks5"
        elif scheme in ("socks4", "socks4a"):
            proxy_type = "socks4"
        elif scheme in ("http", "https"):
            proxy_type = "http"
        elif scheme == "mtproto":
            proxy_type = "mtproto"
            secret = parsed.username or ""
            return cls(proxy_type="mtproto", host=parsed.hostname or "", port=parsed.port or 443, secret=secret)
        else:
            raise ValueError(f"Unsupported proxy scheme: {scheme}")

        return cls(
            proxy_type=proxy_type,
            host=parsed.hostname or "",
            port=parsed.port or (1080 if "socks" in proxy_type else 8080),
            username=parsed.username,
            password=parsed.password,
            rdns=True,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProxyConfig":
        """Parse proxy from dictionary."""
        p_type = data.get("type") or data.get("proxy_type") or "socks5"
        host = data.get("host") or data.get("addr") or data.get("server") or ""
        port = int(data.get("port", 1080 if "socks" in str(p_type).lower() else 443))
        username = data.get("username") or data.get("user")
        password = data.get("password") or data.get("pass")
        secret = data.get("secret")
        rdns = bool(data.get("rdns", True))

        return cls(
            proxy_type=p_type,
            host=host,
            port=port,
            username=username,
            password=password,
            secret=secret,
            rdns=rdns,
        )

    @classmethod
    def parse(cls, value: Any) -> Optional["ProxyConfig"]:
        """Parse proxy from URL, dict, or existing ProxyConfig instance."""
        if not value:
            return None
        if isinstance(value, ProxyConfig):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            return cls.from_url(value)
        if isinstance(value, dict):
            return cls.from_dict(value)
        raise ValueError(f"Cannot parse proxy from type: {type(value)}")

    def get_telethon_args(self) -> Tuple[Optional[Type], Any]:
        """
        Returns (connection_class, proxy_arg) to pass to Telethon's TelegramClient.
        """
        if self.proxy_type == "mtproto":
            # For MTProto proxy in Telethon:
            # connection=ConnectionTcpMTProxyRandomizedIntermediate
            # proxy=(host, port, secret)
            return ConnectionTcpMTProxyRandomizedIntermediate, (self.host, self.port, self.secret)

        # For SOCKS5, SOCKS4, HTTP:
        proxy_dict = {
            "proxy_type": self.proxy_type,
            "addr": self.host,
            "port": self.port,
            "rdns": self.rdns,
        }
        if self.username:
            proxy_dict["username"] = self.username
        if self.password:
            proxy_dict["password"] = self.password

        return ConnectionTcpFull, proxy_dict

    def to_dict(self, mask_secret: bool = False) -> Dict[str, Any]:
        """Serialize proxy config to JSON-compatible dictionary."""
        d: Dict[str, Any] = {
            "type": self.proxy_type,
            "host": self.host,
            "port": self.port,
        }
        if self.proxy_type == "mtproto":
            if mask_secret and self.secret:
                d["secret"] = self.secret[:4] + "..." + self.secret[-4:] if len(self.secret) > 8 else "***"
            else:
                d["secret"] = self.secret
        else:
            if self.username:
                d["username"] = self.username
            if self.password:
                d["password"] = "***" if mask_secret else self.password
            d["rdns"] = self.rdns
        return d
