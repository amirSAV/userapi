from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from app.config import settings

router = APIRouter(prefix="", tags=["Documentation & Help"])

HELP_STATIC_FILE = Path(__file__).parent.parent / "static" / "help.html"

HELP_METADATA = {
    "title": "UserAPI - Telegram Bot API Replacement for User Accounts",
    "version": settings.APP_VERSION,
    "description": (
        "UserAPI is a high-performance Telegram Bot API emulator powered by FastAPI and Telethon. "
        "It allows standard Telegram Bot API client libraries (such as aiogram, python-telegram-bot, "
        "Telegraf, etc.) to control real Telegram user accounts (userbots) without code changes."
    ),
    "quickstart": {
        "step_1": "Obtain your Telegram API ID and API HASH from https://my.telegram.org.",
        "step_2": "Register your session via POST /auth/register (upload .session file) or POST /auth/register_string (with StringSession).",
        "step_3": "Receive your user token (e.g. usr_abcdef1234...).",
        "step_4": "Point your Telegram library's base URL to http://<server_host>:<server_port>/bot<token>/<method> or http://<server_host>:<server_port>/<token>/<method>.",
    },
    "proxy_support": {
        "description": "UserAPI natively supports MTProto proxies, SOCKS5 proxies, SOCKS4 proxies, and HTTP proxies per session.",
        "endpoints": {
            "setProxy": "POST /{token}/setProxy or POST /bot{token}/setProxy",
            "getProxy": "GET /{token}/getProxy",
            "deleteProxy": "POST /{token}/deleteProxy",
        },
        "formats": {
            "socks5": {
                "url": "socks5://username:password@1.2.3.4:1080",
                "dict": {"type": "socks5", "host": "1.2.3.4", "port": 1080, "username": "user", "password": "pass", "rdns": True},
            },
            "http": {
                "url": "http://username:password@1.2.3.4:8080",
                "dict": {"type": "http", "host": "1.2.3.4", "port": 8080, "username": "user", "password": "pass"},
            },
            "mtproto": {
                "url": "tg://proxy?server=1.2.3.4&port=443&secret=dd00000000000000000000000000000000",
                "dict": {"type": "mtproto", "host": "1.2.3.4", "port": 443, "secret": "dd00000000000000000000000000000000"},
            },
        },
    },
    "supported_bot_api_methods": [
        "getMe",
        "getUserProfilePhotos",
        "sendMessage",
        "forwardMessage",
        "copyMessage",
        "editMessageText",
        "editMessageCaption",
        "deleteMessage",
        "deleteMessages",
        "pinChatMessage",
        "unpinChatMessage",
        "unpinAllChatMessages",
        "sendPhoto",
        "sendDocument",
        "sendVideo",
        "sendAudio",
        "sendVoice",
        "sendMediaGroup",
        "sendPoll",
        "sendDice",
        "sendSticker",
        "setMessageReaction",
        "setChatDescription",
        "banChatMember",
        "unbanChatMember",
        "exportChatInviteLink",
        "getFile",
        "uploadFile",
        "sendLocation",
        "sendContact",
        "sendChatAction",
        "getChat",
        "getChatAdministrators",
        "getChatMemberCount",
        "getChatMember",
        "leaveChat",
        "setChatTitle",
        "getUpdates (long-polling)",
        "setWebhook",
        "deleteWebhook",
        "getWebhookInfo",
        "logOut",
    ],
    "file_handling": {
        "getFile": "POST /{token}/getFile or POST /bot{token}/getFile with file_id",
        "download": "GET /file/bot{token}/{file_path} or GET /file/{token}/{file_path}",
        "uploadFile": "POST /{token}/uploadFile (multipart upload with file_id generation)",
    },
    "session_export": {
        "export_metadata": "GET /session/export?token={token} or POST /bot{token}/exportSession",
        "export_file": "GET /session/export_file?token={token} or POST /bot{token}/exportFile (downloads Telethon .session binary file)",
        "export_all": "GET /session/export_all?token={token} (downloads ZIP with session file and metadata)",
    },
    "public_proxy_tester": {
        "endpoint": "GET /proxy/test?proxy=... or POST /proxy/test",
        "description": "Public latency and connectivity test for SOCKS5, SOCKS4, HTTP, and MTProto proxies without authentication.",
    },
    "admin_management": {
        "description": "Admin endpoints secured with ADMIN_TOKEN in .env (via X-Admin-Token or Bearer header)",
        "endpoints": {
            "stats": "GET /admin/stats - Server metrics, active sessions, storage used",
            "sessions": "GET /admin/sessions - List registered sessions and quotas",
            "set_quota": "PUT /admin/sessions/{token}/quota - Update storage quota (MB)",
            "delete_session": "DELETE /admin/sessions/{token}?terminate=true/false - Terminate or unlink session",
        },
    },
    "user_exclusive_extensions": {
        "joinChat": "Join public channels/groups by username or private invite links (t.me/+hash).",
        "getDialogs": "Fetch the user's active dialogs and chat list.",
        "markAsRead": "Acknowledge and mark incoming messages in a chat as read.",
        "addContact": "Add a new phone contact to the user's Telegram contact list.",
        "setProxy / getProxy / deleteProxy": "Dynamically configure MTProto or SOCKS proxies per token.",
        "exportSession / exportFile": "Export session credentials, StringSession, and .session binary SQLite file.",
    },
    "session_lifecycle_management": {
        "unlink_session": "POST /{token}/unlink or POST /session/unlink - Removes credentials and data from server WITHOUT logging out from Telegram. Account stays active on user devices.",
        "terminate_session": "POST /{token}/terminate, logOut, or POST /session/terminate - Permanently logs out from Telegram servers and deletes all data.",
        "rotate_token": "POST /{token}/rotateToken or POST /session/rotate_token - Changes the API token without needing to re-login or upload session again.",
    },
    "telegram_bot_relay_mode": {
        "description": "UserAPI can also act as an intelligent proxy middleman for official Telegram Bot tokens (e.g. 123456:ABC...). It routes requests to api.telegram.org through configured SOCKS5 or HTTP proxies.",
        "registration": "POST /auth/register_bot with bot_token and optional proxy.",
        "on_the_fly": "Simply call /bot<BOT_TOKEN>/<METHOD> - UserAPI automatically routes through proxy.",
        "proxy_management": "Use /bot<BOT_TOKEN>/setProxy, /getProxy, and /deleteProxy just like user sessions.",
    },
    "bot_only_unsupported_features": {
        "setMyCommands / getMyCommands / deleteMyCommands": "User accounts do not have bot command scopes or command menus (supported when relaying official bots).",
        "setChatMenuButton / getChatMenuButton": "User accounts cannot configure bot chat menu buttons.",
        "answerCallbackQuery": "User accounts cannot receive or answer inline callback queries (supported for official bots).",
        "inline_keyboard with callback_data": "Telegram user sessions can only send links or plain text; inline callback buttons require bot authorization.",
        "sendInvoice / createInvoiceLink / payments": "Payments require a Bot API payments provider token.",
    },
    "telegram_library_drop_in_examples": {
        "python_telegram_bot": (
            "from telegram.ext import ApplicationBuilder\n"
            "app = ApplicationBuilder().token('usr_xxxx').base_url('http://127.0.0.1:8000/bot').build()"
        ),
        "aiogram": (
            "from aiogram import Bot\n"
            "from aiogram.client.telegram import TelegramAPIServer\n"
            "local_server = TelegramAPIServer.from_base('http://127.0.0.1:8000')\n"
            "bot = Bot(token='usr_xxxx', server=local_server)"
        ),
        "telegraf_node": (
            "const { Telegraf } = require('telegraf');\n"
            "const bot = new Telegraf('usr_xxxx', { telegram: { apiRoot: 'http://127.0.0.1:8000' } });"
        ),
    },
}


@router.get("/help")
@router.get("/help/")
async def get_help(request: Request, format: Optional[str] = Query(None)):
    """Provides complete documentation for UserAPI."""
    accept_header = request.headers.get("accept", "").lower()

    if format == "json" or "application/json" in accept_header:
        return JSONResponse(status_code=200, content={"ok": True, "result": HELP_METADATA})

    if HELP_STATIC_FILE.exists():
        content = HELP_STATIC_FILE.read_text(encoding="utf-8")
        return HTMLResponse(content=content, status_code=200)

    return JSONResponse(status_code=200, content={"ok": True, "result": HELP_METADATA})
