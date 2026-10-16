import io
import json
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse, FileResponse, Response
from telethon import TelegramClient, utils
from telethon.tl import types
from telethon.tl.functions.channels import (
    JoinChannelRequest,
    EditTitleRequest as EditChannelTitleRequest,
    EditAdminRequest,
)
from telethon.tl.functions.messages import (
    ImportChatInviteRequest,
    CheckChatInviteRequest,
    EditChatTitleRequest,
)
from telethon.tl.functions.contacts import AddContactRequest as TelethonAddContactRequest
from telethon.tl.types import (
    ChannelParticipantsAdmins,
    InputMediaGeoPoint,
    InputGeoPoint,
    InputMediaContact,
    InputPhoneContact,
)

from app.config import settings
from app.database import db
from app.core.client_manager import client_manager
from app.core.serializers import (
    serialize_user,
    serialize_chat,
    serialize_message,
    serialize_chat_member,
)
from app.core.update_queue import update_manager
from app.core.bot_relay import forward_bot_request
from app.core.file_manager import (
    download_message_file,
    save_uploaded_file,
    parse_file_id,
    generate_file_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Telegram Bot API"])

# Bot-only methods that user accounts cannot perform natively
BOT_ONLY_METHODS = {
    "setmycommands": "Bad Request: Method 'setMyCommands' is restricted to Bot accounts only. Telegram user sessions (userbots) do not have a bot command scope or bot menu buttons.",
    "getmycommands": "Bad Request: Method 'getMyCommands' is restricted to Bot accounts only. Telegram user sessions do not have configured bot commands.",
    "deletemycommands": "Bad Request: Method 'deleteMyCommands' is restricted to Bot accounts only.",
    "setmydescription": "Bad Request: Method 'setMyDescription' is restricted to Bot accounts only. To change a user profile bio, use user profile settings.",
    "getmydescription": "Bad Request: Method 'getMyDescription' is restricted to Bot accounts only.",
    "setmyshortdescription": "Bad Request: Method 'setMyShortDescription' is restricted to Bot accounts only.",
    "getmyshortdescription": "Bad Request: Method 'getMyShortDescription' is restricted to Bot accounts only.",
    "setchatmenubutton": "Bad Request: Method 'setChatMenuButton' is restricted to Bot accounts only.",
    "getchatmenubutton": "Bad Request: Method 'getChatMenuButton' is restricted to Bot accounts only.",
    "answercallbackquery": "Bad Request: Method 'answerCallbackQuery' is restricted to Bot accounts only. User accounts cannot receive or respond to inline callback queries.",
    "sendinvoice": "Bad Request: Payments and invoices are restricted to Bot accounts with a Telegram Payments provider token.",
    "createinvoicelink": "Bad Request: Invoice links are restricted to Bot accounts with a Telegram Payments provider token.",
    "answerprecheckoutquery": "Bad Request: Payment checkout queries are restricted to Bot accounts.",
    "answershippingquery": "Bad Request: Shipping queries are restricted to Bot accounts.",
}


async def parse_request_params(request: Request) -> Tuple_params:
    """Extract parameters from query params, json body, or form data."""
    params: Dict[str, Any] = dict(request.query_params)
    files: Dict[str, UploadFile] = {}

    content_type = request.headers.get("content-type", "").lower()

    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                params.update(body)
        except Exception:
            pass
    elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        try:
            form = await request.form()
            for key, val in form.items():
                if isinstance(val, UploadFile):
                    files[key] = val
                else:
                    params[key] = val
        except Exception:
            pass

    return params, files


Tuple_params = tuple[Dict[str, Any], Dict[str, UploadFile]]


def telegram_success(result: Any) -> JSONResponse:
    """Format standard Telegram Bot API success response."""
    return JSONResponse(status_code=200, content={"ok": True, "result": result})


def telegram_error(status_code: int, description: str, error_code: Optional[int] = None) -> JSONResponse:
    """Format standard Telegram Bot API error response."""
    code = error_code or status_code
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error_code": code, "description": description},
    )


async def resolve_peer(client: TelegramClient, chat_id: Union[int, str]):
    """Safely resolves chat_id into a Telethon entity."""
    if chat_id is None:
        raise ValueError("chat_id parameter is required")

    target = chat_id
    if isinstance(target, str):
        target = target.strip()
        if (target.startswith("-") and target[1:].isdigit()) or target.isdigit():
            target = int(target)
        elif target == "me" or target == "self":
            return await client.get_me()

    return await client.get_entity(target)


def normalize_parse_mode(mode: Optional[str]) -> Optional[str]:
    """Map Telegram Bot API parse_mode strings to Telethon formats."""
    if not mode:
        return None
    m = mode.strip().lower()
    if m in ("html", "html5"):
        return "html"
    if m in ("markdown", "markdownv2", "md"):
        return "md"
    return mode


# Official Telegram Bot API file download endpoint: /file/bot<token>/<file_path>
@router.get("/file/bot{token}/{file_path:path}")
@router.get("/file/{token}/{file_path:path}")
@router.get("/file/user{token}/{file_path:path}")
async def download_telegram_file(token: str, file_path: str):
    """
    Downloads media files formatted like the official Telegram Bot API file download endpoint.
    If the token is an official bot relay, proxies the download through configured SOCKS5/HTTP proxy.
    If a user session, serves downloaded files from local storage.
    """
    session_record = db.get_session(token)
    is_bot_relay = (
        session_record and session_record.get("session_type") == "bot_relay"
    ) or (":" in token and not session_record)

    if is_bot_relay:
        from app.core.bot_relay import get_httpx_proxy_url
        import httpx

        proxy_url = get_httpx_proxy_url(session_record.get("proxy") if session_record else None)
        target_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        kwargs: Dict[str, Any] = {"timeout": 60.0, "follow_redirects": True}
        if proxy_url:
            kwargs["proxy"] = proxy_url

        try:
            async with httpx.AsyncClient(**kwargs) as client:
                resp = await client.get(target_url)
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type=resp.headers.get("content-type", "application/octet-stream"),
                )
        except Exception as e:
            return telegram_error(500, f"Error proxying file download: {e}")

    # For user session: search candidate locations
    candidates = [
        settings.storage_path / file_path,
        settings.files_path / file_path,
        settings.uploads_path / file_path,
        settings.files_path / token / file_path,
        settings.uploads_path / token / file_path,
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return FileResponse(path=c, filename=c.name, media_type="application/octet-stream")

    return telegram_error(404, "Bad Request: File not found")


# Unified dispatcher for all token styles: /{token}/{method}, /bot{token}/{method}, /user{token}/{method}
@router.api_route("/{token}/{method}", methods=["GET", "POST"])
@router.api_route("/bot{token}/{method}", methods=["GET", "POST"])
@router.api_route("/user{token}/{method}", methods=["GET", "POST"])
async def dispatch_bot_api(token: str, method: str, request: Request):
    """
    Main Telegram Bot API emulator endpoint.
    Routes requests either to Telethon user accounts OR relays official Telegram bots through configured proxies.
    """
    method_lower = method.lower()
    params, files = await parse_request_params(request)

    session_record = db.get_session(token)

    # Universal lifecycle management methods (supported on all tokens)
    if method_lower in ("rotatetoken",):
        try:
            new_token_val = params.get("new_token")
            new_tok = await client_manager.rotate_token(token, new_token_val)
            return telegram_success({
                "old_token": token,
                "new_token": new_tok,
                "api_endpoint": f"/{new_tok}/getMe",
                "bot_api_endpoint": f"/bot{new_tok}/getMe",
                "message": "Token rotated successfully.",
            })
        except KeyError:
            return telegram_error(401, "Unauthorized: Invalid token")
        except Exception as e:
            return telegram_error(400, f"Bad Request: {e}")

    if method_lower in ("unlink", "close"):
        if (session_record and session_record.get("session_type") == "bot_relay") or (":" in token):
            db.hard_delete_session(token)
        else:
            await client_manager.unlink_session(token)
        return telegram_success(True)

    if method_lower in ("terminate", "logout"):
        if (session_record and session_record.get("session_type") == "bot_relay") or (":" in token):
            db.hard_delete_session(token)
            return telegram_success(True)
        else:
            try:
                await client_manager.terminate_session(token)
                return telegram_success(True)
            except KeyError:
                return telegram_error(401, "Unauthorized: Invalid token")

    # Check if this token is an official Telegram bot (relay mode with proxy support)
    is_bot_relay = (
        session_record and session_record.get("session_type") == "bot_relay"
    ) or (":" in token and not session_record)

    if is_bot_relay:
        # Forward request to official Telegram Bot API via configured proxy
        return await forward_bot_request(token, method, request, params, files)

    # User Account Mode (Telethon Userbot)
    # Check for bot-only methods
    if method_lower in BOT_ONLY_METHODS:
        return telegram_error(400, BOT_ONLY_METHODS[method_lower])

    # 1. Retrieve or connect Telethon client
    try:
        client = await client_manager.get_client(token)
    except KeyError:
        return telegram_error(401, "Unauthorized: Invalid user token")
    except PermissionError as e:
        return telegram_error(401, f"Unauthorized: {e}")
    except Exception as e:
        logger.error(f"Failed to initialize client for token {token[:10]}: {e}")
        return telegram_error(500, f"Internal Server Error: {e}")

    try:
        # Route method
        handler_name = f"handle_{method_lower}"
        if handler_name in METHOD_HANDLERS:
            handler = METHOD_HANDLERS[handler_name]
            return await handler(client, token, params, files)
        else:
            return telegram_error(404, f"Not Found: method '{method}' is not supported")
    except Exception as e:
        logger.error(f"Error executing method {method}: {e}", exc_info=True)
        return telegram_error(400, f"Bad Request: {e}")


# =====================================================================
# METHOD IMPLEMENTATIONS
# =====================================================================

async def handle_getme(client: TelegramClient, token: str, params: dict, files: dict):
    me = await client.get_me()
    return telegram_success(serialize_user(me))


async def handle_getuserprofilephotos(client: TelegramClient, token: str, params: dict, files: dict):
    user_id = params.get("user_id", "me")
    offset = int(params.get("offset", 0))
    limit = int(params.get("limit", 100))

    entity = await resolve_peer(client, user_id)
    photos = await client.get_profile_photos(entity, offset=offset, limit=limit)
    total = len(photos)

    photo_results = []
    for p in photos:
        photo_results.append([
            {
                "file_id": f"user_photo_{p.id}",
                "file_unique_id": f"unique_user_photo_{p.id}",
                "width": 640,
                "height": 640,
                "file_size": 50000,
            }
        ])

    return telegram_success({"total_count": total, "photos": photo_results})


async def handle_sendmessage(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    text = params.get("text")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")
    if not text:
        return telegram_error(400, "Bad Request: text is required")

    # Check reply_markup for callback buttons (bot-only feature)
    reply_markup = params.get("reply_markup")
    if reply_markup:
        if isinstance(reply_markup, str):
            try:
                reply_markup = json.loads(reply_markup)
            except Exception:
                pass
        if isinstance(reply_markup, dict) and "inline_keyboard" in reply_markup:
            for row in reply_markup["inline_keyboard"]:
                for btn in row:
                    if "callback_data" in btn:
                        return telegram_error(
                            400,
                            "Bad Request: Inline keyboard buttons with callback_data are restricted to Bot accounts only. Telegram user sessions (userbots) cannot receive or handle inline callback queries.",
                        )

    entity = await resolve_peer(client, chat_id)
    parse_mode = normalize_parse_mode(params.get("parse_mode"))
    reply_to = int(params["reply_to_message_id"]) if params.get("reply_to_message_id") else None
    disable_preview = bool(params.get("disable_web_page_preview", False))
    schedule_date = int(params["schedule_date"]) if params.get("schedule_date") else None

    msg = await client.send_message(
        entity,
        text,
        parse_mode=parse_mode,
        reply_to=reply_to,
        link_preview=not disable_preview,
        schedule=schedule_date,
    )
    return telegram_success(serialize_message(msg))


async def handle_forwardmessage(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    from_chat_id = params.get("from_chat_id")
    message_id = params.get("message_id")

    if not chat_id or not from_chat_id or not message_id:
        return telegram_error(400, "Bad Request: chat_id, from_chat_id, and message_id are required")

    to_entity = await resolve_peer(client, chat_id)
    from_entity = await resolve_peer(client, from_chat_id)

    msgs = await client.forward_messages(to_entity, int(message_id), from_peer=from_entity)
    msg = msgs[0] if isinstance(msgs, list) else msgs
    return telegram_success(serialize_message(msg))


async def handle_copymessage(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    from_chat_id = params.get("from_chat_id")
    message_id = params.get("message_id")

    if not chat_id or not from_chat_id or not message_id:
        return telegram_error(400, "Bad Request: chat_id, from_chat_id, and message_id are required")

    to_entity = await resolve_peer(client, chat_id)
    from_entity = await resolve_peer(client, from_chat_id)

    orig_msg = await client.get_messages(from_entity, ids=int(message_id))
    if not orig_msg:
        return telegram_error(400, "Bad Request: message to copy not found")

    caption = params.get("caption") or orig_msg.raw_text
    parse_mode = normalize_parse_mode(params.get("parse_mode"))

    if orig_msg.media:
        new_msg = await client.send_file(to_entity, orig_msg.media, caption=caption, parse_mode=parse_mode)
    else:
        new_msg = await client.send_message(to_entity, caption, parse_mode=parse_mode)

    return telegram_success({"message_id": new_msg.id})


async def handle_editmessagetext(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    message_id = params.get("message_id")
    text = params.get("text")

    if not chat_id or not message_id or not text:
        return telegram_error(400, "Bad Request: chat_id, message_id, and text are required")

    entity = await resolve_peer(client, chat_id)
    parse_mode = normalize_parse_mode(params.get("parse_mode"))
    disable_preview = bool(params.get("disable_web_page_preview", False))

    msg = await client.edit_message(
        entity,
        int(message_id),
        text,
        parse_mode=parse_mode,
        link_preview=not disable_preview,
    )
    return telegram_success(serialize_message(msg))


async def handle_editmessagecaption(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    message_id = params.get("message_id")
    caption = params.get("caption", "")

    if not chat_id or not message_id:
        return telegram_error(400, "Bad Request: chat_id and message_id are required")

    entity = await resolve_peer(client, chat_id)
    parse_mode = normalize_parse_mode(params.get("parse_mode"))

    msg = await client.edit_message(entity, int(message_id), caption, parse_mode=parse_mode)
    return telegram_success(serialize_message(msg))


async def handle_deletemessage(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    message_id = params.get("message_id")

    if not chat_id or not message_id:
        return telegram_error(400, "Bad Request: chat_id and message_id are required")

    entity = await resolve_peer(client, chat_id)
    await client.delete_messages(entity, [int(message_id)])
    return telegram_success(True)


async def handle_deletemessages(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    msg_ids = params.get("message_ids")

    if not chat_id or not msg_ids:
        return telegram_error(400, "Bad Request: chat_id and message_ids are required")

    if isinstance(msg_ids, str):
        try:
            msg_ids = json.loads(msg_ids)
        except Exception:
            msg_ids = [int(i.strip()) for i in msg_ids.split(",") if i.strip()]

    entity = await resolve_peer(client, chat_id)
    await client.delete_messages(entity, [int(i) for i in msg_ids])
    return telegram_success(True)


async def handle_pinchatmessage(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    message_id = params.get("message_id")
    if not chat_id or not message_id:
        return telegram_error(400, "Bad Request: chat_id and message_id are required")

    entity = await resolve_peer(client, chat_id)
    notify = not bool(params.get("disable_notification", False))
    await client.pin_message(entity, int(message_id), notify=notify)
    return telegram_success(True)


async def handle_unpinchatmessage(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    msg_id = int(params["message_id"]) if params.get("message_id") else None
    await client.unpin_message(entity, msg_id)
    return telegram_success(True)


async def handle_unpinallchatmessages(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    await client.unpin_message(entity)
    return telegram_success(True)


# Generic media sender
async def _send_media_helper(client: TelegramClient, media_field: str, params: dict, files: dict, force_document: bool = False, voice_note: bool = False):
    chat_id = params.get("chat_id")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    caption = params.get("caption", "")
    parse_mode = normalize_parse_mode(params.get("parse_mode"))
    reply_to = int(params["reply_to_message_id"]) if params.get("reply_to_message_id") else None

    # Check if file uploaded via multipart
    upload_item = files.get(media_field) or files.get("file")
    file_to_send = None

    if upload_item:
        file_bytes = await upload_item.read()
        file_to_send = io.BytesIO(file_bytes)
        file_to_send.name = upload_item.filename or "media"
    else:
        file_to_send = params.get(media_field) or params.get("file")

    if not file_to_send:
        return telegram_error(400, f"Bad Request: {media_field} is required")

    msg = await client.send_file(
        entity,
        file_to_send,
        caption=caption,
        parse_mode=parse_mode,
        reply_to=reply_to,
        force_document=force_document,
        voice_note=voice_note,
    )
    return telegram_success(serialize_message(msg))


async def handle_sendphoto(client: TelegramClient, token: str, params: dict, files: dict):
    return await _send_media_helper(client, "photo", params, files)


async def handle_senddocument(client: TelegramClient, token: str, params: dict, files: dict):
    return await _send_media_helper(client, "document", params, files, force_document=True)


async def handle_sendvideo(client: TelegramClient, token: str, params: dict, files: dict):
    return await _send_media_helper(client, "video", params, files)


async def handle_sendaudio(client: TelegramClient, token: str, params: dict, files: dict):
    return await _send_media_helper(client, "audio", params, files)


async def handle_sendvoice(client: TelegramClient, token: str, params: dict, files: dict):
    return await _send_media_helper(client, "voice", params, files, voice_note=True)


async def handle_sendlocation(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    lat = params.get("latitude")
    lon = params.get("longitude")

    if not chat_id or lat is None or lon is None:
        return telegram_error(400, "Bad Request: chat_id, latitude, and longitude are required")

    entity = await resolve_peer(client, chat_id)
    media = InputMediaGeoPoint(InputGeoPoint(lat=float(lat), long=float(lon)))
    msg = await client.send_file(entity, media)
    return telegram_success(serialize_message(msg))


async def handle_sendcontact(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    phone = params.get("phone_number")
    first_name = params.get("first_name", "")
    last_name = params.get("last_name", "")

    if not chat_id or not phone:
        return telegram_error(400, "Bad Request: chat_id and phone_number are required")

    entity = await resolve_peer(client, chat_id)
    media = InputMediaContact(phone_number=str(phone), first_name=first_name, last_name=last_name, vcard="")
    msg = await client.send_file(entity, media)
    return telegram_success(serialize_message(msg))


async def handle_sendchataction(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    action = params.get("action", "typing")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    action_map = {
        "typing": "typing",
        "upload_photo": "photo",
        "record_video": "video",
        "upload_video": "video",
        "record_voice": "audio",
        "upload_voice": "audio",
        "upload_document": "document",
        "find_location": "geo",
    }
    telethon_action = action_map.get(action.lower(), "typing")
    async with client.action(entity, telethon_action):
        pass
    return telegram_success(True)


async def handle_getchat(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    chat_dict = serialize_chat(entity)
    return telegram_success(chat_dict)


async def handle_getchatadministrators(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    participants = await client.get_participants(entity, filter=ChannelParticipantsAdmins)
    results = [serialize_chat_member(p.participant, p) for p in participants]
    return telegram_success(results)


async def handle_getchatmembercount(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    participants = await client.get_participants(entity, limit=0)
    return telegram_success(participants.total)


async def handle_getchatmember(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    user_id = params.get("user_id")
    if not chat_id or not user_id:
        return telegram_error(400, "Bad Request: chat_id and user_id are required")

    entity = await resolve_peer(client, chat_id)
    user_entity = await resolve_peer(client, user_id)
    permissions = await client.get_permissions(entity, user_entity)

    # Construct member object
    status = "member"
    if permissions.is_creator:
        status = "creator"
    elif permissions.is_admin:
        status = "administrator"

    return telegram_success({
        "status": status,
        "user": serialize_user(user_entity),
        "can_be_edited": False,
        "can_manage_chat": permissions.is_admin,
        "can_change_info": permissions.change_info,
        "can_post_messages": permissions.post_messages,
        "can_edit_messages": permissions.edit_messages,
        "can_delete_messages": permissions.delete_messages,
        "can_invite_users": permissions.invite_users,
        "can_restrict_members": permissions.ban_users,
        "can_pin_messages": permissions.pin_messages,
    })


async def handle_leavechat(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    await client.delete_dialog(entity)
    return telegram_success(True)


async def handle_setchattitle(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    title = params.get("title")
    if not chat_id or not title:
        return telegram_error(400, "Bad Request: chat_id and title are required")

    entity = await resolve_peer(client, chat_id)
    if isinstance(entity, types.Channel):
        await client(EditChannelTitleRequest(channel=entity, title=title))
    elif isinstance(entity, types.Chat):
        await client(EditChatTitleRequest(chat_id=entity.id, title=title))
    else:
        return telegram_error(400, "Bad Request: Cannot edit title of a private chat")

    return telegram_success(True)


# Long-polling and webhooks
async def handle_getupdates(client: TelegramClient, token: str, params: dict, files: dict):
    offset = int(params["offset"]) if params.get("offset") is not None else None
    limit = int(params.get("limit", 100))
    timeout = int(params.get("timeout", 0))

    queue = update_manager.get_queue(token)
    try:
        updates = await queue.get_updates(offset=offset, limit=limit, timeout=timeout)
        return telegram_success(updates)
    except ValueError as e:
        return telegram_error(409, str(e))


async def handle_setwebhook(client: TelegramClient, token: str, params: dict, files: dict):
    url = params.get("url")
    if not url:
        return telegram_error(400, "Bad Request: url is required")

    db.update_webhook(token, url.strip())
    return telegram_success({"ok": True, "description": "Webhook was set"})


async def handle_deletewebhook(client: TelegramClient, token: str, params: dict, files: dict):
    db.update_webhook(token, None)
    return telegram_success({"ok": True, "description": "Webhook was deleted"})


async def handle_getwebhookinfo(client: TelegramClient, token: str, params: dict, files: dict):
    session = db.get_session(token)
    webhook_url = session.get("webhook_url") if session else None
    queue = update_manager.get_queue(token)

    return telegram_success({
        "url": webhook_url or "",
        "has_custom_certificate": False,
        "pending_update_count": len(queue.updates),
    })


async def handle_logout(client: TelegramClient, token: str, params: dict, files: dict):
    await client_manager.disconnect_client(token)
    db.delete_session(token)
    return telegram_success(True)


# =====================================================================
# USER-ONLY EXTENSIONS (Userbot Superpowers!)
# =====================================================================

async def handle_joinchat(client: TelegramClient, token: str, params: dict, files: dict):
    """Join a public channel or a private invite link (t.me/+hash or t.me/joinchat/hash)."""
    target = params.get("chat_id") or params.get("invite_link")
    if not target:
        return telegram_error(400, "Bad Request: chat_id or invite_link is required")

    target_str = str(target).strip()
    # Check if invite link
    invite_match = re.search(r"(?:joinchat/|\+)([a-zA-Z0-9_-]+)", target_str)
    if invite_match:
        invite_hash = invite_match.group(1)
        res = await client(ImportChatInviteRequest(invite_hash))
        chat_entity = res.chats[0] if res.chats else None
        return telegram_success(serialize_chat(chat_entity))

    # Public channel / group by username
    entity = await resolve_peer(client, target_str)
    await client(JoinChannelRequest(entity))
    return telegram_success(serialize_chat(entity))


async def handle_getdialogs(client: TelegramClient, token: str, params: dict, files: dict):
    """List recent chats/dialogs for this user."""
    limit = int(params.get("limit", 30))
    dialogs = await client.get_dialogs(limit=limit)

    results = []
    for d in dialogs:
        results.append({
            "chat": serialize_chat(d.entity),
            "unread_count": d.unread_count,
            "is_pinned": d.pinned,
            "last_message": serialize_message(d.message) if d.message else None,
        })
    return telegram_success(results)


async def handle_markasread(client: TelegramClient, token: str, params: dict, files: dict):
    """Mark dialog/chat messages as read."""
    chat_id = params.get("chat_id")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    max_id = int(params["max_id"]) if params.get("max_id") else None
    await client.send_read_acknowledge(entity, max_id=max_id)
    return telegram_success(True)


async def handle_addcontact(client: TelegramClient, token: str, params: dict, files: dict):
    """Add a user to contact list."""
    phone = params.get("phone_number")
    first_name = params.get("first_name", "")
    last_name = params.get("last_name", "")
    if not phone or not first_name:
        return telegram_error(400, "Bad Request: phone_number and first_name are required")

    contact = InputPhoneContact(client_id=0, phone=str(phone), first_name=first_name, last_name=last_name)
    res = await client(TelethonAddContactRequest(id=types.InputUserEmpty(), first_name=first_name, last_name=last_name, phone=str(phone)))
    return telegram_success(True)


async def handle_getfile(client: TelegramClient, token: str, params: dict, files: dict):
    file_id = params.get("file_id")
    if not file_id:
        return telegram_error(400, "Bad Request: file_id is required")

    parsed = parse_file_id(file_id)
    if parsed and parsed["type"] == "message":
        try:
            res = await download_message_file(client, token, parsed["chat_id"], parsed["message_id"])
            if res:
                return telegram_success(res)
        except PermissionError as e:
            return telegram_error(403, str(e))
        except Exception as e:
            logger.warning(f"Error downloading message file: {e}")

    # Check uploads and files directories
    for sub in ["uploads", "files"]:
        sub_dir = settings.storage_path / sub / token
        if sub_dir.exists():
            for f in sub_dir.glob("*"):
                if file_id in f.name:
                    return telegram_success({
                        "file_id": file_id,
                        "file_unique_id": f"unique_{file_id}",
                        "file_size": f.stat().st_size,
                        "file_path": f"{sub}/{token}/{f.name}",
                    })

    return telegram_error(404, "Bad Request: file not found or expired")


async def handle_uploadfile(client: TelegramClient, token: str, params: dict, files: dict):
    upload_item = files.get("file") or files.get("document") or files.get("photo") or (list(files.values())[0] if files else None)
    if not upload_item:
        return telegram_error(400, "Bad Request: file is required")

    content = await upload_item.read()
    try:
        res = await save_uploaded_file(token, upload_item.filename or "upload.bin", content)
        return telegram_success(res)
    except PermissionError as e:
        return telegram_error(403, str(e))


async def handle_sendmediagroup(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    media = params.get("media")
    if not chat_id or not media:
        return telegram_error(400, "Bad Request: chat_id and media are required")

    if isinstance(media, str):
        try:
            media = json.loads(media)
        except Exception:
            return telegram_error(400, "Bad Request: media must be valid JSON array")

    entity = await resolve_peer(client, chat_id)
    items_to_send = []
    for m in media:
        m_file = m.get("media")
        if m_file and m_file in files:
            f_upload = files[m_file]
            b = await f_upload.read()
            bio = io.BytesIO(b)
            bio.name = f_upload.filename or "media"
            items_to_send.append(bio)
        elif m_file:
            items_to_send.append(m_file)

    msgs = await client.send_file(entity, items_to_send)
    res = [serialize_message(msg) for msg in (msgs if isinstance(msgs, list) else [msgs])]
    return telegram_success(res)


async def handle_sendpoll(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    question = params.get("question")
    options = params.get("options")
    if not chat_id or not question or not options:
        return telegram_error(400, "Bad Request: chat_id, question, and options are required")

    if isinstance(options, str):
        try:
            options = json.loads(options)
        except Exception:
            options = [opt.strip() for opt in options.split(",") if opt.strip()]

    entity = await resolve_peer(client, chat_id)
    from telethon.tl.types import InputMediaPoll, Poll, PollAnswer

    answers = [PollAnswer(text=str(opt), option=bytes([idx])) for idx, opt in enumerate(options)]
    poll = Poll(id=0, question=str(question), answers=answers, closed=False)
    msg = await client.send_file(entity, InputMediaPoll(poll=poll))
    return telegram_success(serialize_message(msg))


async def handle_senddice(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    emoji = params.get("emoji", "🎲")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    from telethon.tl.types import InputMediaDice

    msg = await client.send_file(entity, InputMediaDice(emoticon=emoji))
    return telegram_success(serialize_message(msg))


async def handle_sendsticker(client: TelegramClient, token: str, params: dict, files: dict):
    return await _send_media_helper(client, "sticker", params, files)


async def handle_setmessagereaction(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    message_id = params.get("message_id")
    reaction = params.get("reaction")
    if not chat_id or not message_id:
        return telegram_error(400, "Bad Request: chat_id and message_id are required")

    entity = await resolve_peer(client, chat_id)
    emoji = "👍"
    if isinstance(reaction, str):
        if reaction.startswith("["):
            try:
                parsed_r = json.loads(reaction)
                if parsed_r:
                    emoji = parsed_r[0].get("emoji", "👍") if isinstance(parsed_r[0], dict) else str(parsed_r[0])
            except Exception:
                emoji = reaction
        else:
            emoji = reaction
    elif isinstance(reaction, list) and reaction:
        emoji = reaction[0].get("emoji", "👍") if isinstance(reaction[0], dict) else str(reaction[0])
    elif isinstance(reaction, dict):
        emoji = reaction.get("emoji", "👍")

    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    await client(SendReactionRequest(peer=entity, msg_id=int(message_id), reaction=[ReactionEmoji(emoticon=str(emoji))]))
    return telegram_success(True)


async def handle_setchatdescription(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    description = params.get("description", "")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    try:
        from telethon.tl.functions.messages import EditChatAboutRequest
        await client(EditChatAboutRequest(peer=entity, about=description))
    except Exception:
        from telethon.tl.functions.channels import EditAboutRequest
        await client(EditAboutRequest(channel=entity, about=description))

    return telegram_success(True)


async def handle_banchatmember(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    user_id = params.get("user_id")
    if not chat_id or not user_id:
        return telegram_error(400, "Bad Request: chat_id and user_id are required")

    entity = await resolve_peer(client, chat_id)
    user_entity = await resolve_peer(client, user_id)
    await client.edit_permissions(entity, user_entity, view_messages=False)
    return telegram_success(True)


async def handle_unbanchatmember(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    user_id = params.get("user_id")
    if not chat_id or not user_id:
        return telegram_error(400, "Bad Request: chat_id and user_id are required")

    entity = await resolve_peer(client, chat_id)
    user_entity = await resolve_peer(client, user_id)
    await client.edit_permissions(entity, user_entity, view_messages=True)
    return telegram_success(True)


async def handle_exportchatinvitelink(client: TelegramClient, token: str, params: dict, files: dict):
    chat_id = params.get("chat_id")
    if not chat_id:
        return telegram_error(400, "Bad Request: chat_id is required")

    entity = await resolve_peer(client, chat_id)
    from telethon.tl.functions.messages import ExportChatInviteRequest
    res = await client(ExportChatInviteRequest(peer=entity))
    return telegram_success(getattr(res, "link", ""))


async def handle_exportsession(client: TelegramClient, token: str, params: dict, files: dict):
    export_data = db.get_session_export(token)
    if not export_data:
        return telegram_error(404, "Session not found")
    return telegram_success(export_data)


async def handle_exportfile(client: TelegramClient, token: str, params: dict, files: dict):
    return telegram_success({"download_url": f"/session/export_file?token={token}"})


METHOD_HANDLERS = {
    "handle_getme": handle_getme,
    "handle_getuserprofilephotos": handle_getuserprofilephotos,
    "handle_sendmessage": handle_sendmessage,
    "handle_forwardmessage": handle_forwardmessage,
    "handle_copymessage": handle_copymessage,
    "handle_editmessagetext": handle_editmessagetext,
    "handle_editmessagecaption": handle_editmessagecaption,
    "handle_deletemessage": handle_deletemessage,
    "handle_deletemessages": handle_deletemessages,
    "handle_pinchatmessage": handle_pinchatmessage,
    "handle_unpinchatmessage": handle_unpinchatmessage,
    "handle_unpinallchatmessages": handle_unpinallchatmessages,
    "handle_sendphoto": handle_sendphoto,
    "handle_senddocument": handle_senddocument,
    "handle_sendvideo": handle_sendvideo,
    "handle_sendaudio": handle_sendaudio,
    "handle_sendvoice": handle_sendvoice,
    "handle_sendlocation": handle_sendlocation,
    "handle_sendcontact": handle_sendcontact,
    "handle_sendchataction": handle_sendchataction,
    "handle_getchat": handle_getchat,
    "handle_getchatadministrators": handle_getchatadministrators,
    "handle_getchatmembercount": handle_getchatmembercount,
    "handle_getchatmemberscount": handle_getchatmembercount,
    "handle_getchatmember": handle_getchatmember,
    "handle_leavechat": handle_leavechat,
    "handle_setchattitle": handle_setchattitle,
    "handle_getupdates": handle_getupdates,
    "handle_setwebhook": handle_setwebhook,
    "handle_deletewebhook": handle_deletewebhook,
    "handle_getwebhookinfo": handle_getwebhookinfo,
    "handle_logout": handle_logout,
    # File & Media
    "handle_getfile": handle_getfile,
    "handle_uploadfile": handle_uploadfile,
    "handle_sendmediagroup": handle_sendmediagroup,
    "handle_sendpoll": handle_sendpoll,
    "handle_senddice": handle_senddice,
    "handle_sendsticker": handle_sendsticker,
    "handle_setmessagereaction": handle_setmessagereaction,
    "handle_setchatdescription": handle_setchatdescription,
    "handle_banchatmember": handle_banchatmember,
    "handle_kickchatmember": handle_banchatmember,
    "handle_unbanchatmember": handle_unbanchatmember,
    "handle_exportchatinvitelink": handle_exportchatinvitelink,
    "handle_exportsession": handle_exportsession,
    "handle_exportfile": handle_exportfile,
    # User extensions
    "handle_joinchat": handle_joinchat,
    "handle_getdialogs": handle_getdialogs,
    "handle_markasread": handle_markasread,
    "handle_addcontact": handle_addcontact,
}
