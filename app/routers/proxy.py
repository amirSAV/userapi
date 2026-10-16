import json
import logging
from typing import Union, Dict, Any
from fastapi import APIRouter, Body, Request
from app.database import db
from app.core.client_manager import client_manager
from app.core.proxy import ProxyConfig
from app.models.schemas import TelegramResponse, SetProxyRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Proxy Management"])


@router.post("/{token}/setProxy", response_model=TelegramResponse)
@router.post("/bot{token}/setProxy", response_model=TelegramResponse)
@router.post("/user{token}/setProxy", response_model=TelegramResponse)
async def set_proxy(token: str, req: SetProxyRequest):
    """
    Configure or update proxy settings for the specific session/token.
    Supports SOCKS5, SOCKS4, HTTP, and MTProto proxies for user sessions and bot relays.
    """
    session = db.get_session(token)
    if not session:
        if ":" in token:
            db.save_bot_relay(token)
            session = db.get_session(token)
        else:
            return TelegramResponse(ok=False, error_code=401, description="Unauthorized: Invalid token.")

    try:
        proxy_config = ProxyConfig.parse(req.proxy if not hasattr(req.proxy, "model_dump") else req.proxy.model_dump())
        if not proxy_config:
            return TelegramResponse(ok=False, error_code=400, description="Bad Request: Empty proxy specification.")

        if session.get("session_type") == "bot_relay":
            db.update_proxy(token, proxy_config.to_dict())
            return TelegramResponse(
                ok=True,
                result={
                    "proxy": proxy_config.to_dict(mask_secret=True),
                    "message": "Proxy updated for Telegram Bot relay.",
                },
            )

        await client_manager.update_client_proxy(token, proxy_config)
        return TelegramResponse(
            ok=True,
            result={
                "proxy": proxy_config.to_dict(mask_secret=True),
                "message": "Proxy updated and client reconnected successfully.",
            },
        )
    except Exception as e:
        logger.error(f"Error setting proxy for token {token[:10]}: {e}")
        return TelegramResponse(ok=False, error_code=400, description=f"Bad Request: Failed to set proxy: {e}")


@router.get("/{token}/getProxy", response_model=TelegramResponse)
@router.post("/{token}/getProxy", response_model=TelegramResponse)
@router.get("/bot{token}/getProxy", response_model=TelegramResponse)
@router.post("/bot{token}/getProxy", response_model=TelegramResponse)
@router.get("/user{token}/getProxy", response_model=TelegramResponse)
@router.post("/user{token}/getProxy", response_model=TelegramResponse)
async def get_proxy(token: str):
    """Retrieve current proxy settings for the session."""
    session = db.get_session(token)
    if not session:
        return TelegramResponse(ok=False, error_code=401, description="Unauthorized: Invalid token.")

    proxy_data = session.get("proxy")
    if not proxy_data:
        return TelegramResponse(ok=True, result={"proxy": None, "message": "No proxy configured for this session."})

    try:
        proxy_config = ProxyConfig.parse(proxy_data)
        return TelegramResponse(ok=True, result={"proxy": proxy_config.to_dict(mask_secret=True) if proxy_config else None})
    except Exception:
        return TelegramResponse(ok=True, result={"proxy": proxy_data})


@router.post("/{token}/deleteProxy", response_model=TelegramResponse)
@router.post("/bot{token}/deleteProxy", response_model=TelegramResponse)
@router.post("/user{token}/deleteProxy", response_model=TelegramResponse)
async def delete_proxy(token: str):
    """Remove proxy settings and reconnect client directly."""
    session = db.get_session(token)
    if not session:
        return TelegramResponse(ok=False, error_code=401, description="Unauthorized: Invalid token.")

    if session.get("session_type") == "bot_relay":
        db.update_proxy(token, None)
        return TelegramResponse(ok=True, result={"message": "Proxy deleted for Telegram Bot relay."})

    try:
        await client_manager.update_client_proxy(token, None)
        return TelegramResponse(ok=True, result={"message": "Proxy deleted. Client reconnected directly."})
    except Exception as e:
        return TelegramResponse(ok=False, error_code=400, description=f"Bad Request: Failed to remove proxy: {e}")


@router.api_route("/proxy/test", methods=["GET", "POST"], response_model=TelegramResponse)
async def public_test_proxy(request: Request, proxy_url: Optional[str] = None, timeout: float = 6.0):
    """
    Public utility to test proxy connectivity (SOCKS5, SOCKS4, HTTP, MTProto) without requiring any token.
    Accepts proxy as JSON body, form data, or query parameter 'proxy_url'.
    """
    from app.core.proxy_tester import test_proxy

    target = proxy_url
    if request.method == "POST":
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    target = body.get("proxy") or body
                elif isinstance(body, str):
                    target = body
            except Exception:
                pass
        elif "form" in content_type:
            try:
                form = await request.form()
                target = form.get("proxy") or form.get("proxy_url")
            except Exception:
                pass

    if isinstance(target, dict) and "proxy" in target and len(target) == 1:
        target = target["proxy"]

    if not target:
        return TelegramResponse(
            ok=False,
            error_code=400,
            description="Bad Request: 'proxy' parameter or body is required.",
        )

    res = await test_proxy(target, timeout=timeout)
    return TelegramResponse(
        ok=bool(res.get("working")),
        result=res,
        description=res.get("error") if not res.get("working") else None,
    )

