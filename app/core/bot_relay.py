import logging
from typing import Optional, Dict, Any
from fastapi import Request, UploadFile, Response
from fastapi.responses import JSONResponse
import httpx

from app.config import settings
from app.database import db
from app.core.proxy import ProxyConfig

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


def get_httpx_proxy_url(proxy_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Converts a stored proxy configuration dict to an HTTP/SOCKS proxy URL string for httpx."""
    if not proxy_data:
        if settings.DEFAULT_PROXY:
            return settings.DEFAULT_PROXY
        return None

    p_type = proxy_data.get("type", "socks5").lower()
    host = proxy_data.get("host", "")
    port = proxy_data.get("port", 1080)
    username = proxy_data.get("username")
    password = proxy_data.get("password")

    if p_type == "mtproto":
        # Note: api.telegram.org is HTTP/HTTPS, MTProto proxy is for Telegram MTProto protocol.
        # If fallback default proxy exists, use it.
        logger.warning("MTProto proxy specified for Bot API HTTP relay. Bot API uses HTTP/HTTPS/SOCKS proxy.")
        if settings.DEFAULT_PROXY and not settings.DEFAULT_PROXY.startswith("tg://") and not settings.DEFAULT_PROXY.startswith("mtproto://"):
            return settings.DEFAULT_PROXY
        return None

    auth = ""
    if username:
        auth = f"{username}:{password}@" if password else f"{username}@"

    return f"{p_type}://{auth}{host}:{port}"


async def forward_bot_request(
    token: str,
    method: str,
    request: Request,
    params: Dict[str, Any],
    files: Dict[str, UploadFile],
) -> Response:
    """
    Forward incoming Bot API request to official Telegram Bot API (api.telegram.org)
    routing through the session's configured proxy (SOCKS5/HTTP).
    """
    session = db.get_session(token)
    proxy_data = session.get("proxy") if session else None
    proxy_url = get_httpx_proxy_url(proxy_data)

    target_url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"
    http_method = request.method.upper()

    client_kwargs: Dict[str, Any] = {
        "timeout": 60.0,
        "follow_redirects": True,
    }
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            if files:
                # Prepare multipart upload
                multipart_files = {}
                data_fields = {}
                for k, v in params.items():
                    data_fields[k] = str(v)
                for k, f in files.items():
                    file_content = await f.read()
                    multipart_files[k] = (f.filename or "file", file_content, f.content_type or "application/octet-stream")

                resp = await client.request(
                    method=http_method,
                    url=target_url,
                    data=data_fields,
                    files=multipart_files,
                )
            elif "application/json" in request.headers.get("content-type", "").lower() and http_method == "POST":
                resp = await client.post(target_url, json=params)
            else:
                resp = await client.request(method=http_method, url=target_url, params=params)

            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "application/json"),
            )
    except httpx.ProxyError as e:
        logger.error(f"Proxy error relaying to {target_url}: {e}")
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error_code": 502, "description": f"Bad Gateway: Proxy connection failed: {e}"},
        )
    except httpx.ConnectTimeout as e:
        logger.error(f"Connect timeout relaying to {target_url}: {e}")
        return JSONResponse(
            status_code=504,
            content={"ok": False, "error_code": 504, "description": f"Gateway Timeout: {e}"},
        )
    except Exception as e:
        logger.error(f"Error relaying request to Telegram Bot API: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error_code": 500, "description": f"Internal Server Error: {e}"},
        )
