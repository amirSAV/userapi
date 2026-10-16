# 🚀 UserAPI

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Telethon](https://img.shields.io/badge/Telethon-1.36+-2BA1DE.svg?logo=telegram)](https://docs.telethon.dev)

A high-performance, drop-in **Telegram Bot API replacement** powered by **Telethon** and **FastAPI**, designed to execute Bot API requests directly through **real Telegram user accounts (userbots)**.

Existing Telegram bot libraries (`aiogram`, `python-telegram-bot`, `telegraf`, etc.) can connect to UserAPI simply by switching their base URL.

---

## ✨ Features

- **🔄 Drop-In Telegram Bot API Emulation**:
  - Direct routing for `https://<host>/bot<token>/<method>` and `https://<host>/<token>/<method>`.
  - Same standard JSON responses (`{"ok": true, "result": ...}` and `{"ok": false, "error_code": 400, "description": "..."}`).
- **📱 Real User Accounts (Telethon)**:
  - Runs all requests using a real Telegram user session (MTProto).
- **🌐 Comprehensive Per-User Proxy Support**:
  - Native support for **MTProto Proxies** (randomized intermediate proxy).
  - **SOCKS5**, **SOCKS4**, and **HTTP/HTTPS Proxies**.
  - Configure proxies dynamically per user token (`setProxy`, `getProxy`, `deleteProxy`) or set a server-wide default fallback proxy.
- **🔐 Flexible Session Registration**:
  - Upload an existing `.session` SQLite file via `multipart/form-data`.
  - Or provide a Telethon `StringSession`.
  - Or use the interactive 3-step phone login flow (`send_code`, `sign_in`, `2fa`).
  - Automatically generates a secure, unique API token for each user session.
- **🤖 Official Telegram Bot Reverse Proxy & Relay**:
  - Acts as a proxy middleman for official Telegram Bots (tokens from `@BotFather`).
  - Routes bot requests to `api.telegram.org` through per-bot SOCKS5 or HTTP proxies, allowing bots to run seamlessly in censored networks.
- **🔄 Dynamic Token Rotation**:
  - Rotate your API token at any time (`rotateToken`) without re-authenticating, changing session files, or disconnecting.
- **🗑️ Flexible Session Removal (Unlink vs Terminate)**:
  - **Unlink from Server (`unlink` / `close`)**: wipes tokens and session files from the server without terminating the Telegram session (remains logged in on your phone/devices).
  - **Terminate Session (`terminate` / `logOut`)**: permanently logs out on Telegram servers and wipes local data.
- **📁 Persistent Server Storage via `.env`**:
  - All sessions, databases, and uploaded files are stored in a configurable folder (`STORAGE_DIR=./data`).
- **🛡️ Telegram Bot API Parity & Limitations Handling**:
  - Methods not supported by user accounts (like `setMyCommands`, `answerCallbackQuery`, inline keyboard `callback_data` buttons) gracefully return standard Telegram Bot API error responses explaining the technical restriction.
- **💾 Session Export & Backup**:
  - Export registered accounts at any time:
    - Download the authentic Telethon `.session` SQLite binary file (`/session/export_file` or `exportFile`).
    - Retrieve StringSession and credentials JSON (`/session/export` or `exportSession`).
    - Download complete ZIP archive backup (`/session/export_all`).
- **📁 File Uploads & Bot API Download Parity**:
  - Full support for `getFile` returning standard Bot API `file_path`.
  - Direct binary downloads via `https://<host>/file/bot<token>/<file_path>` or `https://<host>/file/<token>/<file_path>`.
  - Multipart file uploading with unique `file_id` generation (`uploadFile`).
- **🛡️ Admin Dashboard & Per-User Storage Quotas**:
  - Secured via `ADMIN_TOKEN` (`X-Admin-Token` or Bearer header).
  - Monitor total storage, registered sessions, and active memory clients (`/admin/stats`).
  - Enforce and customize storage quotas per user in megabytes (`/admin/sessions/{token}/quota`).
- **🔍 Public Proxy Latency Tester**:
  - Public `/proxy/test` endpoint to check connectivity and latency for SOCKS5, SOCKS4, HTTP, and MTProto proxies without requiring authentication.
- **⚡ Extended Telegram Bot API Parity**:
  - `sendMediaGroup`: Send albums of photos and videos.
  - `sendPoll`: Create polls and quizzes.
  - `sendDice`: Send animated dice, basketball, darts, etc.
  - `sendSticker`: Send stickers via file_id or document.
  - `setMessageReaction`: Add or clear emoji reactions.
  - `banChatMember` & `unbanChatMember`: Kick/ban and unban members.
  - `setChatDescription` & `exportChatInviteLink`: Manage chat metadata and invite links.
- **⚡ Exclusive Userbot Superpowers**:
  - `joinChat`: Join public channels or private invite links (`t.me/+hash`).
  - `getDialogs`: Retrieve active chats, unread message counts, and last messages.
  - `markAsRead`: Acknowledge and mark messages as read.
  - `addContact`: Add phone numbers to the user's contact book.
- **📡 Updates: Long-Polling & Webhooks**:
  - `getUpdates` with long-polling (`offset`, `limit`, `timeout`).
  - `setWebhook`, `deleteWebhook`, and `getWebhookInfo` support.
- **📖 Documentation & UI**:
  - Interactive HTML documentation and API tester at `/help`.
  - Interactive Swagger OpenAPI UI at `/docs`.

---

## 🏗️ Architecture

```
                                  ┌──────────────────────────────┐
                                  │      Client Applications     │
                                  │ (aiogram / PTB / curl / etc.)│
                                  └──────────────┬───────────────┘
                                                 │
                               HTTP / HTTPS (Bot API Schema)
                                                 │
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                   UserAPI                                   │
│                                                                             │
│  ┌───────────────────────┐   ┌───────────────────┐   ┌───────────────────┐  │
│  │     FastAPI Router    │──▶│  Client Manager   │──▶│ Telethon Client   │  │
│  │ /bot<token>/<method>  │   │  (Token -> Client)│   │  (User Session)   │  │
│  └───────────────────────┘   └─────────┬─────────┘   └─────────┬─────────┘  │
│                                        │                       │            │
│               ┌────────────────────────┴────────┐              │            │
│               ▼                                 ▼              ▼            │
│    ┌────────────────────┐            ┌────────────────┐   Proxy / MTProto   │
│    │ SQLite Database    │            │ Update Queue & │   (SOCKS5 / HTTP /  │
│    │ (STORAGE_DIR/      │            │ Webhook Worker │    MTProto Proxy)   │
│    │  userapi.db)       │            └────────────────┘        │            │
└────┴────────────────────┴──────────────────────────────────────┼────────────┘
                                                                 ▼
                                                    Telegram MTProto Servers
```

---

## 📦 Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/amirSAV/userapi.git
cd userapi
```

### 2. Create and Activate Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example environment configuration:

```bash
cp .env.example .env
```

Edit `.env` to configure your storage location, host, port, or fallback proxy:

```ini
# Server host & port
HOST=0.0.0.0
PORT=8000

# Directory where sessions, SQLite database, and media are saved
STORAGE_DIR=./data

# (Optional) Global fallback proxy
DEFAULT_PROXY=socks5://127.0.0.1:1080

# Admin panel secret token for /admin endpoints
ADMIN_TOKEN=your_super_secret_admin_token

# Default user disk storage quota in MB
DEFAULT_USER_QUOTA_MB=100
```

### 5. Run the Server

```bash
# Using the startup script:
python run.py

# Or directly with uvicorn:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Server will be running at `http://localhost:8000`.

---

## 🔑 Authentication: Registering a User Session

To generate an API token for a user account, register your Telegram session:

### Option A: Upload `.session` File (Recommended)

```bash
curl -X POST "http://localhost:8000/auth/register" \
  -F "file=@my_account.session" \
  -F "api_id=1234567" \
  -F "api_hash=0123456789abcdef0123456789abcdef"
```

### Option B: Provide a Telethon `StringSession`

```bash
curl -X POST "http://localhost:8000/auth/register_string" \
  -H "Content-Type: application/json" \
  -d '{
    "api_id": 1234567,
    "api_hash": "0123456789abcdef0123456789abcdef",
    "session_string": "1BJWap1wBu..."
  }'
```

### Option C: Interactive Phone Login (Without existing session)

1. **Request Code**:

   ```bash
   curl -X POST "http://localhost:8000/auth/send_code" \
     -H "Content-Type: application/json" \
     -d '{
       "phone_number": "+1234567890",
       "api_id": 1234567,
       "api_hash": "0123456789abcdef0123456789abcdef"
     }'
   ```

   *Returns an `auth_token`.*

2. **Submit Code**:

   ```bash
   curl -X POST "http://localhost:8000/auth/sign_in" \
     -H "Content-Type: application/json" \
     -d '{
       "auth_token": "auth_xxx...",
       "code": "12345"
     }'
   ```

3. **2FA Password (if enabled)**:

   ```bash
   curl -X POST "http://localhost:8000/auth/2fa" \
     -H "Content-Type: application/json" \
     -d '{
       "auth_token": "auth_xxx...",
       "password": "my_2fa_password"
     }'
   ```

### Registration Response

```json
{
  "ok": true,
  "result": {
    "token": "usr_94b5e28a01bf4e892cfa7162985361...",
    "user": {
      "id": 987654321,
      "is_bot": false,
      "first_name": "Amir",
      "username": "amir_username",
      "phone_number": "+1234567890"
    },
    "api_endpoint": "/usr_94b5e28a.../getMe",
    "bot_api_endpoint": "/botusr_94b5e28a.../getMe"
  }
}
```

---

## 🌐 Proxy Configuration

UserAPI supports per-token proxy configuration. Clients in censored environments can connect through SOCKS5, HTTP, or MTProto proxies.

### 1. Set SOCKS5 / HTTP Proxy

```bash
curl -X POST "http://localhost:8000/bot<TOKEN>/setProxy" \
  -H "Content-Type: application/json" \
  -d '{
    "proxy": "socks5://user:pass@127.0.0.1:1080"
  }'
```

Or via structured JSON:

```bash
curl -X POST "http://localhost:8000/bot<TOKEN>/setProxy" \
  -H "Content-Type: application/json" \
  -d '{
    "proxy": {
      "type": "socks5",
      "host": "127.0.0.1",
      "port": 1080,
      "username": "user",
      "password": "pass",
      "rdns": true
    }
  }'
```

### 2. Set MTProto Proxy

You can pass a Telegram MTProto proxy URL or dict:

```bash
curl -X POST "http://localhost:8000/bot<TOKEN>/setProxy" \
  -H "Content-Type: application/json" \
  -d '{
    "proxy": "tg://proxy?server=proxy.example.com&port=443&secret=dd0123456789abcdef0123456789abcdef"
  }'
```

Or structured JSON:

```bash
curl -X POST "http://localhost:8000/bot<TOKEN>/setProxy" \
  -H "Content-Type: application/json" \
  -d '{
    "proxy": {
      "type": "mtproto",
      "host": "proxy.example.com",
      "port": 443,
      "secret": "dd0123456789abcdef0123456789abcdef"
    }
  }'
```

### 3. Check / Remove Proxy

- **Get current proxy**: `GET /bot<TOKEN>/getProxy`
- **Delete proxy**: `POST /bot<TOKEN>/deleteProxy`

---

## 🤖 Official Telegram Bot Reverse Proxy Relay

UserAPI is not only for user accounts — it also acts as an intelligent proxy middleman for **official Telegram Bot tokens** (from `@BotFather`).
When running in restricted network environments, you can point standard bot libraries to UserAPI to route traffic to `https://api.telegram.org` through a SOCKS5 or HTTP proxy.

### Registering Bot Token

```bash
curl -X POST "http://localhost:8000/auth/register_bot" \
  -H "Content-Type: application/json" \
  -d '{
    "bot_token": "123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "proxy": "socks5://user:pass@127.0.0.1:1080"
  }'
```

Or invoke directly on-the-fly:
```bash
curl -X POST "http://localhost:8000/bot<BOT_TOKEN>/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{"chat_id": 123456, "text": "Hello through UserAPI proxy relay!"}'
```

Configure proxies dynamically for bot tokens:
- **Set Proxy**: `POST /bot<BOT_TOKEN>/setProxy`
- **Get Proxy**: `GET /bot<BOT_TOKEN>/getProxy`
- **Delete Proxy**: `POST /bot<BOT_TOKEN>/deleteProxy`
- **Unlink Bot**: `POST /bot<BOT_TOKEN>/unlink`

---

## 🔄 Token Rotation & Session Lifecycle

### 1. Rotating API Tokens
You can rotate or customize the API token for any active session at any time without having to re-authenticate or upload the session again:

```bash
curl -X POST "http://localhost:8000/bot<CURRENT_TOKEN>/rotateToken" \
  -H "Content-Type: application/json" \
  -d '{
    "new_token": "usr_custom_or_auto_generated"
  }'
```

### 2. Unlinking vs Terminating Sessions

UserAPI provides two distinct ways to remove accounts:

| Mode | Endpoint | Behavior |
|:---|:---|:---|
| **Unlink from Server Only** | `POST /bot<TOKEN>/unlink`<br>`POST /bot<TOKEN>/close` | Disconnects and deletes `.session` files and database records from the server **WITHOUT logging out of Telegram**. The user remains logged in on their phone, desktop, and other apps. |
| **Terminate Session Permanently** | `POST /bot<TOKEN>/terminate`<br>`POST /bot<TOKEN>/logOut` | Executes `log_out` on Telegram servers, immediately invalidating the session everywhere and removing all server data. |

---

## 💾 Session Export & Backup

Users can export or back up their session files at any time, in 3 different formats:

### 1. Download Telethon `.session` SQLite Binary File
```bash
# Via dedicated endpoint (attaches filename header):
curl -O -J "http://localhost:8000/session/export_file?token=<TOKEN>"

# Or via Telegram Bot API method:
curl -X POST "http://localhost:8000/bot<TOKEN>/exportFile"
```
*(Note: If you originally registered via a StringSession, UserAPI dynamically generates an authentic SQLite `.session` file for download!)*

### 2. Export StringSession & Account Metadata
```bash
# Returns JSON containing session_string, phone, api_id, etc.
curl "http://localhost:8000/session/export?token=<TOKEN>"

# Or via Bot API method:
curl -X POST "http://localhost:8000/bot<TOKEN>/exportSession"
```

### 3. Full ZIP Backup
```bash
# Downloads a zip archive containing the session file and session_info.json
curl -O -J "http://localhost:8000/session/export_all?token=<TOKEN>"
```

---

## 📁 File Handling & Media Methods

UserAPI supports official Telegram Bot API file paths and downloads:

### 1. `getFile` and `/file/bot<token>/<file_path>`
```bash
# Step 1: Call getFile
curl -X POST "http://localhost:8000/bot<TOKEN>/getFile" \
  -H "Content-Type: application/json" \
  -d '{"file_id": "msg_123456789_doc"}'

# Step 2: Download directly using the returned file_path
curl -O "http://localhost:8000/file/bot<TOKEN>/user_files/<TOKEN>/msg_123456789_doc.jpg"
```

### 2. Uploading Files (`uploadFile`)
Upload files to user storage and obtain a `file_id`:
```bash
curl -X POST "http://localhost:8000/bot<TOKEN>/uploadFile" \
  -F "file=@example.pdf"
```

### 3. Extended Bot API Methods
- **`sendMediaGroup`**: Send albums of photos and videos.
- **`sendPoll`**: Post multiple-choice polls or quiz questions.
- **`sendDice`**: Send animated dice, dartboards, basketball, etc.
- **`setMessageReaction`**: React with emojis (`👍`, `❤️`, etc.) to messages.
- **`banChatMember` / `unbanChatMember`**: Kick or ban participants from groups/channels.
- **`setChatDescription` & `exportChatInviteLink`**: Update chat description or generate links.

---

## 🛡️ Admin Dashboard & Storage Quotas

Control and monitor your UserAPI server using the `ADMIN_TOKEN` configured in `.env`. Admin endpoints accept the token via `X-Admin-Token` header or `Authorization: Bearer <ADMIN_TOKEN>`.

### 1. System Health & Storage Statistics
```bash
curl -H "X-Admin-Token: your_secret_admin_token" \
  "http://localhost:8000/admin/stats"
```
Response:
```json
{
  "ok": true,
  "result": {
    "status": "healthy",
    "total_sessions": 5,
    "active_clients_in_memory": 3,
    "total_storage_mb": 42.15,
    "storage_dir": "./data"
  }
}
```

### 2. List Registered Sessions & Quotas
```bash
curl -H "X-Admin-Token: your_secret_admin_token" \
  "http://localhost:8000/admin/sessions"
```

### 3. Update User Storage Quota
Enforce disk storage limits per session (in MB):
```bash
curl -X PUT -H "X-Admin-Token: your_secret_admin_token" \
  "http://localhost:8000/admin/sessions/<TOKEN>/quota?quota_mb=250"
```

### 4. Admin Delete / Terminate Session
```bash
# Terminate permanently from Telegram and server:
curl -X DELETE -H "X-Admin-Token: your_secret_admin_token" \
  "http://localhost:8000/admin/sessions/<TOKEN>?terminate=true"

# Or unlink only (preserve Telegram session):
curl -X DELETE -H "X-Admin-Token: your_secret_admin_token" \
  "http://localhost:8000/admin/sessions/<TOKEN>?terminate=false"
```

---

## 🔍 Public Proxy Latency Tester

Test proxy connectivity and latency without authentication:

```bash
# Using GET query param:
curl "http://localhost:8000/proxy/test?proxy=socks5://user:pass@127.0.0.1:1080"

# Or using POST JSON:
curl -X POST "http://localhost:8000/proxy/test" \
  -H "Content-Type: application/json" \
  -d '{"proxy": "tg://proxy?server=proxy.example.com&port=443&secret=dd..."}'
```

Response:
```json
{
  "ok": true,
  "result": {
    "alive": true,
    "proxy_type": "socks5",
    "host": "127.0.0.1",
    "port": 1080,
    "latency_ms": 38.45
  }
}
```

---

## 🤖 Drop-in Library Usage

### Python (aiogram v3)

```python
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.telegram import TelegramAPIServer

# Point server to UserAPI local instance
userapi_server = TelegramAPIServer.from_base("http://127.0.0.1:8000")

bot = Bot(token="usr_YOUR_TOKEN", server=userapi_server)
dp = Dispatcher()

async def main():
    me = await bot.get_me()
    print(f"Logged in as user: {me.first_name} (@{me.username})")
    
    # Send a message through the user account
    await bot.send_message(chat_id="@channel_or_username", text="Hello from aiogram over UserAPI!")

if __name__ == "__main__":
    asyncio.run(main())
```

### Python (python-telegram-bot)

```python
from telegram.ext import ApplicationBuilder

app = (
    ApplicationBuilder()
    .token("usr_YOUR_TOKEN")
    .base_url("http://127.0.0.1:8000/bot")
    .build()
)

async def send():
    async with app.bot:
        await app.bot.send_message(chat_id="me", text="Self note via UserAPI!")

import asyncio
asyncio.run(send())
```

### Node.js (Telegraf)

```javascript
const { Telegraf } = require('telegraf');

const bot = new Telegraf('usr_YOUR_TOKEN', {
  telegram: { apiRoot: 'http://127.0.0.1:8000' }
});

bot.telegram.getMe().then(console.log);
bot.telegram.sendMessage('@durov', 'Hello from Telegraf via UserAPI!');
```

---

## 📊 Compatibility Matrix

| Category            | Method                                   | Status | Notes                                                              |
|:------------------- |:---------------------------------------- |:------:|:------------------------------------------------------------------ |
| **Account**         | `getMe`                                  | ✅      | Returns `User` object for the logged-in session                    |
|                     | `getUserProfilePhotos`                   | ✅      | Fetches profile photos                                             |
| **Messaging**       | `sendMessage`                            | ✅      | Text, HTML/Markdown parse mode, reply_to, scheduled messages       |
|                     | `forwardMessage`                         | ✅      | Forwards message to target chat                                    |
|                     | `copyMessage`                            | ✅      | Re-sends message without forward tag                               |
|                     | `editMessageText`                        | ✅      | Edits sent text                                                    |
|                     | `editMessageCaption`                     | ✅      | Edits sent caption                                                 |
|                     | `deleteMessage` / `deleteMessages`       | ✅      | Deletes single or multiple messages                                |
|                     | `pinChatMessage` / `unpinChatMessage`    | ✅      | Pins or unpins message in chat                                     |
| **Media**           | `sendPhoto`, `sendDocument`, `sendVideo` | ✅      | Supports multipart upload or file URL                              |
|                     | `sendAudio`, `sendVoice`                 | ✅      | Sends audio file or voice note                                     |
|                     | `sendMediaGroup`                         | ✅      | Sends photo/video albums in a single group                         |
|                     | `sendPoll`                               | ✅      | Sends regular or quiz polls                                        |
|                     | `sendDice`                               | ✅      | Sends animated dice, darts, basketball, etc.                       |
|                     | `sendSticker`                            | ✅      | Sends stickers via document or file_id                             |
|                     | `sendLocation`, `sendContact`            | ✅      | Geo point and contact vCards                                       |
|                     | `sendChatAction`                         | ✅      | Sends typing / upload indicators                                   |
| **File Handling**   | `getFile`                                | ✅      | Returns `File` object with `file_path` for downloading             |
|                     | `/file/bot<token>/<path>`                | ✅      | Standard Bot API binary file download endpoint                     |
|                     | `uploadFile`                             | ✅      | Multipart upload storing file with unique `file_id`                |
| **Reactions**       | `setMessageReaction`                     | ✅      | Sets or removes emoji reactions on messages                        |
| **Chat Admin**      | `getChat`                                | ✅      | Returns private / group / channel details                          |
|                     | `getChatAdministrators`                  | ✅      | Returns admin participant list                                     |
|                     | `getChatMemberCount`                     | ✅      | Returns total chat member count                                    |
|                     | `getChatMember`                          | ✅      | Returns participant permissions                                    |
|                     | `leaveChat`                              | ✅      | Leaves chat or channel                                             |
|                     | `setChatTitle`                           | ✅      | Changes group or channel title                                     |
|                     | `setChatDescription`                     | ✅      | Sets channel or group description                                  |
|                     | `banChatMember` / `unbanChatMember`      | ✅      | Kicks/bans or unbans chat participant                              |
|                     | `exportChatInviteLink`                   | ✅      | Generates invite link for chat                                     |
| **Updates**         | `getUpdates`                             | ✅      | Long-polling update buffer                                         |
|                     | `setWebhook` / `deleteWebhook`           | ✅      | Dispatches updates to webhook URL                                  |
| **User Extensions** | `joinChat`                               | 🌟     | Joins public channel or private invite link (`t.me/+hash`)         |
|                     | `getDialogs`                             | 🌟     | Fetches active chats and unread counts                             |
|                     | `markAsRead`                             | 🌟     | Acknowledges messages as read                                      |
|                     | `addContact`                             | 🌟     | Adds phone contact to account                                      |
|                     | `setProxy` / `getProxy` / `deleteProxy`  | 🌟     | Per-token dynamic proxy management                                 |
|                     | `exportSession` / `exportFile`           | 🌟     | Export credentials, StringSession, and .session SQLite file        |
| **Bot-Only**        | `setMyCommands` / `getMyCommands`        | ❌      | Returns `400 Bad Request` (user accounts lack bot command scopes)  |
|                     | `setChatMenuButton`                      | ❌      | Returns `400 Bad Request`                                          |
|                     | `answerCallbackQuery`                    | ❌      | Returns `400 Bad Request`                                          |
|                     | Inline buttons with `callback_data`      | ❌      | Returns `400 Bad Request` (user accounts cannot process callbacks) |
|                     | `sendInvoice` / Payments                 | ❌      | Returns `400 Bad Request` (requires Bot API payment provider)      |

---

## 🧪 Testing

Run the automated test suite with `pytest`:

```bash
pytest -v
```

---

## 📄 License

This project is open-source and released under the **[MIT License](LICENSE)**.
