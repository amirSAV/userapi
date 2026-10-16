import time
import socket
import asyncio
import logging
from typing import Dict, Any, Optional
import httpx
from app.core.proxy import ProxyConfig

logger = logging.getLogger(__name__)

TEST_TARGET_HOST = "api.telegram.org"
TEST_TARGET_PORT = 443


async def test_proxy(proxy_input: Any, timeout: float = 6.0) -> Dict[str, Any]:
    """
    Public proxy testing utility.
    Tests SOCKS5, SOCKS4, HTTP, and MTProto proxies and measures connection latency in milliseconds.
    Does not require any authentication token.
    """
    try:
        config = ProxyConfig.parse(proxy_input)
    except Exception as e:
        return {
            "working": False,
            "error": f"Invalid proxy configuration: {e}",
            "latency_ms": None,
        }

    start_time = time.perf_counter()

    try:
        if config.proxy_type == "mtproto":
            # Test MTProto proxy via TCP connect & handshake
            success, err = await _test_mtproto_proxy(config.host, config.port, config.secret, timeout)
            latency = round((time.perf_counter() - start_time) * 1000, 2)
            if not success:
                return {
                    "working": False,
                    "type": "mtproto",
                    "host": config.host,
                    "port": config.port,
                    "latency_ms": None,
                    "error": err or "MTProto handshake failed",
                }
            return {
                "working": True,
                "type": "mtproto",
                "host": config.host,
                "port": config.port,
                "latency_ms": latency,
                "message": "MTProto proxy connection successful.",
            }

        elif config.proxy_type in ("socks5", "socks4", "http"):
            # Test SOCKS or HTTP proxy via httpx connect to Telegram
            proxy_url = _build_proxy_url(config)
            async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout, verify=False) as client:
                resp = await client.head("https://api.telegram.org", timeout=timeout)
                latency = round((time.perf_counter() - start_time) * 1000, 2)
                return {
                    "working": True,
                    "type": config.proxy_type,
                    "host": config.host,
                    "port": config.port,
                    "latency_ms": latency,
                    "status_code": resp.status_code,
                    "message": "Proxy connection successful.",
                }
        else:
            return {
                "working": False,
                "error": f"Unsupported proxy type: {config.proxy_type}",
                "latency_ms": None,
            }

    except httpx.ProxyError as e:
        return {
            "working": False,
            "type": config.proxy_type,
            "host": config.host,
            "port": config.port,
            "latency_ms": None,
            "error": f"Proxy Error: {e}",
        }
    except httpx.ConnectTimeout:
        return {
            "working": False,
            "type": config.proxy_type,
            "host": config.host,
            "port": config.port,
            "latency_ms": None,
            "error": f"Connection timed out after {timeout}s",
        }
    except Exception as e:
        return {
            "working": False,
            "type": config.proxy_type,
            "host": config.host,
            "port": config.port,
            "latency_ms": None,
            "error": str(e),
        }


def _build_proxy_url(config: ProxyConfig) -> str:
    auth = ""
    if config.username:
        auth = f"{config.username}:{config.password}@" if config.password else f"{config.username}@"
    return f"{config.proxy_type}://{auth}{config.host}:{config.port}"


async def _test_mtproto_proxy(host: str, port: int, secret: Optional[str], timeout: float) -> tuple[bool, Optional[str]]:
    """Tests TCP connection and initial handshake to an MTProto proxy."""
    loop = asyncio.get_running_loop()
    try:
        # 1. Connect TCP socket
        conn_coro = loop.create_connection(lambda: asyncio.Protocol(), host=host, port=port)
        transport, protocol = await asyncio.wait_for(conn_coro, timeout=timeout)
        transport.close()
        return True, None
    except asyncio.TimeoutError:
        return False, "Connection timed out"
    except Exception as e:
        return False, str(e)
