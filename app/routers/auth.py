import json
import logging
import secrets
import io
import zipfile
from pathlib import Path
from typing import Optional, Union, Dict, Any
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body, Response
from fastapi.responses import FileResponse, Response
from telethon import TelegramClient
from telethon.sessions import StringSession, SQLiteSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

from app.config import settings
from app.database import db
from app.core.client_manager import client_manager
from app.core.proxy import ProxyConfig
from app.core.serializers import serialize_user
from app.models.schemas import (
    TelegramResponse,
    RegisterStringRequest,
    SendCodeRequest,
    SignInRequest,
    PasswordRequest,
    RegisterBotRequest,
    RotateTokenRequest,
    UnlinkSessionRequest,
    TerminateSessionRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Authentication & Session Management"])


@router.post("/auth/register", response_model=TelegramResponse)
@router.post("/session/register", response_model=TelegramResponse)
async def register_session(
    file: Optional[UploadFile] = File(None, description=".session SQLite file"),
    session_string: Optional[str] = Form(None, description="Telethon StringSession"),
    api_id: Optional[int] = Form(None, description="Telegram API ID"),
    api_hash: Optional[str] = Form(None, description="Telegram API Hash"),
    proxy: Optional[str] = Form(None, description="Proxy URL or JSON string"),
):
    """
    Registers a Telegram user session via file upload or form parameters.
    Returns a unique API token for Bot API calls.
    """
    final_api_id = api_id or settings.DEFAULT_API_ID
    final_api_hash = api_hash or settings.DEFAULT_API_HASH

    if not final_api_id or not final_api_hash:
        return TelegramResponse(
            ok=False,
            error_code=400,
            description="Bad Request: 'api_id' and 'api_hash' are required.",
        )

    proxy_config = None
    if proxy:
        try:
            if proxy.strip().startswith("{"):
                proxy_config = ProxyConfig.parse(json.loads(proxy))
            else:
                proxy_config = ProxyConfig.parse(proxy)
        except Exception as e:
            return TelegramResponse(
                ok=False,
                error_code=400,
                description=f"Bad Request: Invalid proxy specification: {e}",
            )

    file_bytes = None
    if file:
        file_bytes = await file.read()

    if not file_bytes and not session_string:
        return TelegramResponse(
            ok=False,
            error_code=400,
            description="Bad Request: You must provide either a .session file upload or a 'session_string'.",
        )

    try:
        token, user_dict = await client_manager.register_session(
            api_id=int(final_api_id),
            api_hash=final_api_hash.strip(),
            session_file_bytes=file_bytes,
            session_string=session_string.strip() if session_string else None,
            proxy_config=proxy_config,
        )
        return TelegramResponse(
            ok=True,
            result={
                "token": token,
                "user": user_dict,
                "api_endpoint": f"/{token}/getMe",
                "bot_api_endpoint": f"/bot{token}/getMe",
                "message": "Session registered successfully. Use your token like a standard Telegram bot token.",
            },
        )
    except PermissionError as e:
        return TelegramResponse(
            ok=False,
            error_code=401,
            description=f"Unauthorized: {e}",
        )
    except Exception as e:
        logger.error(f"Error registering session: {e}", exc_info=True)
        return TelegramResponse(
            ok=False,
            error_code=400,
            description=f"Bad Request: Registration failed: {e}",
        )


@router.post("/auth/register_string", response_model=TelegramResponse)
async def register_session_json(req: RegisterStringRequest):
    """Register session via JSON payload with StringSession."""
    proxy_config = None
    if req.proxy:
        try:
            proxy_config = ProxyConfig.parse(req.proxy)
        except Exception as e:
            return TelegramResponse(
                ok=False,
                error_code=400,
                description=f"Bad Request: Invalid proxy specification: {e}",
            )

    try:
        token, user_dict = await client_manager.register_session(
            api_id=req.api_id,
            api_hash=req.api_hash.strip(),
            session_string=req.session_string.strip(),
            proxy_config=proxy_config,
        )
        return TelegramResponse(
            ok=True,
            result={
                "token": token,
                "user": user_dict,
                "api_endpoint": f"/{token}/getMe",
                "bot_api_endpoint": f"/bot{token}/getMe",
                "message": "Session registered successfully.",
            },
        )
    except Exception as e:
        return TelegramResponse(
            ok=False,
            error_code=400,
            description=f"Bad Request: Registration failed: {e}",
        )


@router.post("/auth/send_code", response_model=TelegramResponse)
async def auth_send_code(req: SendCodeRequest):
    """
    Step 1 of Interactive Login:
    Sends an authentication code to the specified phone number.
    Returns auth_token and phone_code_hash for sign_in.
    """
    proxy_config = None
    if req.proxy:
        try:
            proxy_config = ProxyConfig.parse(req.proxy)
        except Exception as e:
            return TelegramResponse(ok=False, error_code=400, description=f"Bad Request: {e}")

    temp_session = StringSession()
    conn_cls, p_args = proxy_config.get_telethon_args() if proxy_config else (None, None)

    kwargs = {}
    if conn_cls:
        kwargs["connection"] = conn_cls
    if p_args:
        kwargs["proxy"] = p_args

    client = TelegramClient(temp_session, req.api_id, req.api_hash, **kwargs)
    try:
        await client.connect()
        sent_code = await client.send_code_request(req.phone_number)
        session_str = temp_session.save()
        await client.disconnect()

        auth_token = f"auth_{secrets.token_hex(16)}"
        db.save_temp_auth(
            auth_token=auth_token,
            phone=req.phone_number,
            phone_code_hash=sent_code.phone_code_hash,
            api_id=req.api_id,
            api_hash=req.api_hash,
            proxy=proxy_config.to_dict() if proxy_config else None,
            session_string=session_str,
        )

        return TelegramResponse(
            ok=True,
            result={
                "auth_token": auth_token,
                "phone": req.phone_number,
                "phone_code_hash": sent_code.phone_code_hash,
                "message": "Confirmation code sent. Proceed to /auth/sign_in with auth_token and code.",
            },
        )
    except Exception as e:
        if client.is_connected():
            await client.disconnect()
        return TelegramResponse(ok=False, error_code=400, description=f"Bad Request: {e}")


@router.post("/auth/sign_in", response_model=TelegramResponse)
async def auth_sign_in(req: SignInRequest):
    """
    Step 2 of Interactive Login:
    Submits the SMS/Telegram code. If 2FA password is required, prompts for /auth/2fa.
    Otherwise completes registration and returns user token.
    """
    record = db.get_temp_auth(req.auth_token)
    if not record:
        return TelegramResponse(ok=False, error_code=404, description="Auth token expired or not found.")

    proxy_config = ProxyConfig.parse(record.get("proxy")) if record.get("proxy") else None
    conn_cls, p_args = proxy_config.get_telethon_args() if proxy_config else (None, None)

    temp_session = StringSession(record.get("session_string") or "")
    kwargs = {}
    if conn_cls:
        kwargs["connection"] = conn_cls
    if p_args:
        kwargs["proxy"] = p_args

    client = TelegramClient(temp_session, record["api_id"], record["api_hash"], **kwargs)
    try:
        await client.connect()
        try:
            await client.sign_in(record["phone"], req.code, phone_code_hash=record["phone_code_hash"])
        except SessionPasswordNeededError:
            # Update session state for 2FA step
            db.save_temp_auth(
                auth_token=req.auth_token,
                phone=record["phone"],
                phone_code_hash=record["phone_code_hash"],
                api_id=record["api_id"],
                api_hash=record["api_hash"],
                proxy=proxy_config.to_dict() if proxy_config else None,
                session_string=temp_session.save(),
            )
            await client.disconnect()
            return TelegramResponse(
                ok=True,
                result={
                    "needs_2fa": True,
                    "auth_token": req.auth_token,
                    "message": "Two-factor authentication (2FA) is enabled on this account. Proceed to /auth/2fa.",
                },
            )

        me = await client.get_me()
        user_dict = serialize_user(me)
        final_session_string = temp_session.save()
        await client.disconnect()
        db.delete_temp_auth(req.auth_token)

        # Register session permanently
        token, _ = await client_manager.register_session(
            api_id=record["api_id"],
            api_hash=record["api_hash"],
            session_string=final_session_string,
            proxy_config=proxy_config,
        )

        return TelegramResponse(
            ok=True,
            result={
                "token": token,
                "user": user_dict,
                "api_endpoint": f"/{token}/getMe",
                "bot_api_endpoint": f"/bot{token}/getMe",
                "message": "Authentication successful.",
            },
        )
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
        if client.is_connected():
            await client.disconnect()
        return TelegramResponse(ok=False, error_code=400, description=f"Bad Request: {e}")
    except Exception as e:
        if client.is_connected():
            await client.disconnect()
        return TelegramResponse(ok=False, error_code=400, description=f"Bad Request: {e}")


@router.post("/auth/2fa", response_model=TelegramResponse)
async def auth_2fa(req: PasswordRequest):
    """
    Step 3 of Interactive Login (if 2FA is enabled):
    Submits the 2-step verification password.
    """
    record = db.get_temp_auth(req.auth_token)
    if not record:
        return TelegramResponse(ok=False, error_code=404, description="Auth token expired or not found.")

    proxy_config = ProxyConfig.parse(record.get("proxy")) if record.get("proxy") else None
    conn_cls, p_args = proxy_config.get_telethon_args() if proxy_config else (None, None)

    temp_session = StringSession(record.get("session_string") or "")
    kwargs = {}
    if conn_cls:
        kwargs["connection"] = conn_cls
    if p_args:
        kwargs["proxy"] = p_args

    client = TelegramClient(temp_session, record["api_id"], record["api_hash"], **kwargs)
    try:
        await client.connect()
        await client.sign_in(password=req.password)
        me = await client.get_me()
        user_dict = serialize_user(me)
        final_session_string = temp_session.save()
        await client.disconnect()
        db.delete_temp_auth(req.auth_token)

        token, _ = await client_manager.register_session(
            api_id=record["api_id"],
            api_hash=record["api_hash"],
            session_string=final_session_string,
            proxy_config=proxy_config,
        )

        return TelegramResponse(
            ok=True,
            result={
                "token": token,
                "user": user_dict,
                "api_endpoint": f"/{token}/getMe",
                "bot_api_endpoint": f"/bot{token}/getMe",
                "message": "2FA authentication successful.",
            },
        )
    except Exception as e:
        if client.is_connected():
            await client.disconnect()
        return TelegramResponse(ok=False, error_code=400, description=f"Bad Request: {e}")


@router.get("/auth/sessions", response_model=TelegramResponse)
async def list_sessions():
    """List registered active sessions on this server."""
    sessions = db.list_sessions()
    return TelegramResponse(ok=True, result=sessions)


@router.post("/auth/register_bot", response_model=TelegramResponse)
async def register_bot_token(req: RegisterBotRequest):
    """
    Registers an official Telegram Bot token for reverse proxy relay with proxy support.
    """
    proxy_config = None
    if req.proxy:
        try:
            proxy_config = ProxyConfig.parse(req.proxy if not hasattr(req.proxy, "model_dump") else req.proxy.model_dump())
        except Exception as e:
            return TelegramResponse(ok=False, error_code=400, description=f"Bad Request: Invalid proxy: {e}")

    db.save_bot_relay(req.bot_token.strip(), proxy=proxy_config.to_dict() if proxy_config else None)
    return TelegramResponse(
        ok=True,
        result={
            "token": req.bot_token.strip(),
            "type": "bot_relay",
            "proxy": proxy_config.to_dict(mask_secret=True) if proxy_config else None,
            "api_endpoint": f"/bot{req.bot_token.strip()}/getMe",
            "message": "Telegram Bot registered for reverse proxy relay with proxy support.",
        },
    )


@router.post("/auth/rotate_token", response_model=TelegramResponse)
@router.post("/session/rotate_token", response_model=TelegramResponse)
async def rotate_token_route(req: RotateTokenRequest):
    """
    Rotates the API token for an existing session without losing authentication or session data.
    """
    if not req.token:
        return TelegramResponse(ok=False, error_code=400, description="Bad Request: 'token' parameter is required.")
    try:
        new_tok = await client_manager.rotate_token(req.token.strip(), req.new_token.strip() if req.new_token else None)
        return TelegramResponse(
            ok=True,
            result={
                "old_token": req.token.strip(),
                "new_token": new_tok,
                "api_endpoint": f"/{new_tok}/getMe",
                "bot_api_endpoint": f"/bot{new_tok}/getMe",
                "message": "Token rotated successfully.",
            },
        )
    except KeyError:
        return TelegramResponse(ok=False, error_code=401, description="Unauthorized: Invalid token.")
    except Exception as e:
        return TelegramResponse(ok=False, error_code=400, description=f"Bad Request: {e}")


@router.post("/auth/unlink", response_model=TelegramResponse)
@router.post("/session/unlink", response_model=TelegramResponse)
async def unlink_session_route(req: UnlinkSessionRequest):
    """
    Removes session data and credentials from the server WITHOUT terminating the Telegram session.
    The account remains active and logged-in on all official devices.
    """
    if not req.token:
        return TelegramResponse(ok=False, error_code=400, description="Bad Request: 'token' parameter is required.")
    await client_manager.unlink_session(req.token.strip(), delete_file=req.delete_file)
    return TelegramResponse(
        ok=True,
        result={
            "token": req.token.strip(),
            "message": "Session unlinked and removed from server without terminating the Telegram session.",
        },
    )


@router.post("/auth/terminate", response_model=TelegramResponse)
@router.post("/session/terminate", response_model=TelegramResponse)
async def terminate_session_route(req: TerminateSessionRequest):
    """
    Terminates the Telegram session on Telegram servers (logOut) and deletes all local data.
    """
    if not req.token:
        return TelegramResponse(ok=False, error_code=400, description="Bad Request: 'token' parameter is required.")
    try:
        await client_manager.terminate_session(req.token.strip())
        return TelegramResponse(
            ok=True,
            result={
                "token": req.token.strip(),
                "message": "Session logged out from Telegram servers and removed from server.",
            },
        )
    except KeyError:
        return TelegramResponse(ok=False, error_code=401, description="Unauthorized: Invalid token.")
    except Exception as e:
        return TelegramResponse(ok=False, error_code=400, description=f"Bad Request: {e}")


@router.get("/session/export", response_model=TelegramResponse)
@router.post("/session/export", response_model=TelegramResponse)
async def export_session_metadata(token: str):
    """
    Export session details, user info, StringSession representation, and binary file download link.
    """
    export_data = db.get_session_export(token.strip())
    if not export_data:
        return TelegramResponse(ok=False, error_code=404, description="Session not found.")

    # Generate StringSession if not already present
    session_str = export_data.get("session_string")
    if not session_str and export_data.get("session_file_path"):
        f_path = Path(export_data["session_file_path"])
        if f_path.exists():
            try:
                base_name = str(f_path)[:-8] if str(f_path).endswith(".session") else str(f_path)
                s = SQLiteSession(base_name)
                session_str = StringSession.save(s)
                s.close()
            except Exception as e:
                logger.warning(f"Could not convert SQLiteSession to StringSession: {e}")

    result = {
        "token": export_data["token"],
        "session_name": export_data["session_name"],
        "session_type": export_data["session_type"],
        "session_string": session_str,
        "user_id": export_data.get("user_id"),
        "first_name": export_data.get("first_name"),
        "username": export_data.get("username"),
        "phone": export_data.get("phone"),
        "proxy": export_data.get("proxy"),
        "file_download_url": f"/session/export_file?token={export_data['token']}",
        "created_at": export_data.get("created_at"),
    }
    return TelegramResponse(ok=True, result=result)


@router.get("/session/export_file")
async def export_session_file(token: str):
    """
    Download the .session SQLite binary file directly for use in other Telethon or Pyrogram applications.
    """
    export_data = db.get_session_export(token.strip())
    if not export_data:
        raise HTTPException(status_code=404, detail="Session not found.")

    s_name = export_data.get("session_name") or f"user_{export_data.get('user_id', 'session')}"
    download_filename = f"{export_data.get('username') or export_data.get('user_id') or s_name}.session"

    file_path = export_data.get("session_file_path")
    if file_path and Path(file_path).exists():
        return FileResponse(
            path=file_path,
            filename=download_filename,
            media_type="application/octet-stream",
        )

    # If StringSession, generate SQLite file on the fly
    session_str = export_data.get("session_string")
    if session_str:
        temp_dir = settings.storage_path / "temp_exports"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_base = temp_dir / f"export_{token[:8]}"
        str_obj = StringSession(session_str)
        s = SQLiteSession(str(temp_base))
        s.set_dc(str_obj.dc_id, str_obj.server_address, str_obj.port)
        s.auth_key = str_obj.auth_key
        s.save()
        s.close()
        generated_path = temp_dir / f"export_{token[:8]}.session"
        return FileResponse(
            path=generated_path,
            filename=download_filename,
            media_type="application/octet-stream",
        )

    raise HTTPException(status_code=404, detail="Session file not found.")


@router.get("/session/export_all")
async def export_all_sessions(admin_token: Optional[str] = None):
    """
    Download a ZIP archive containing all .session files stored on the server.
    """
    # Verify admin if ADMIN_TOKEN is set
    if settings.ADMIN_TOKEN and admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid admin token.")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for f in settings.sessions_path.glob("*.session"):
            zip_file.write(f, arcname=f.name)

    zip_buffer.seek(0)
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=all_sessions_backup.zip"},
    )


