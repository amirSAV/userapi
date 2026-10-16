import os
import re
import uuid
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Union
from telethon import TelegramClient

from app.config import settings
from app.database import db

logger = logging.getLogger(__name__)


def generate_file_id(chat_id: Union[int, str], message_id: int, media_type: str = "media") -> str:
    """Generates a structured, parseable file_id for a message attachment."""
    safe_chat = str(chat_id).replace("-", "n")
    return f"msg_{safe_chat}_{message_id}_{media_type}"


def parse_file_id(file_id: str) -> Optional[Dict[str, Any]]:
    """Parses a structured file_id back into chat_id, message_id, and media_type."""
    if not file_id:
        return None

    if file_id.startswith("msg_"):
        parts = file_id.split("_")
        if len(parts) >= 4:
            safe_chat = parts[1]
            chat_id = int("-" + safe_chat[1:]) if safe_chat.startswith("n") else (int(safe_chat) if safe_chat.isdigit() else safe_chat)
            msg_id = int(parts[2])
            media_type = parts[3]
            return {
                "type": "message",
                "chat_id": chat_id,
                "message_id": msg_id,
                "media_type": media_type,
            }

    if file_id.startswith("up_"):
        return {
            "type": "upload",
            "upload_id": file_id,
        }

    return None


def check_storage_quota(token: str, new_bytes: int = 0) -> bool:
    """Checks whether adding new_bytes would exceed the session's storage quota."""
    session = db.get_session(token)
    if not session:
        return True

    quota_mb = session.get("storage_quota_mb") or settings.DEFAULT_USER_QUOTA_MB
    quota_bytes = quota_mb * 1024 * 1024

    current_used = db.get_session_storage_used_bytes(token)
    if current_used + new_bytes > quota_bytes:
        raise PermissionError(
            f"Storage quota exceeded: Current usage {round(current_used / (1024*1024), 2)}MB + "
            f"new {round(new_bytes / (1024*1024), 2)}MB exceeds quota of {quota_mb}MB."
        )
    return True


async def save_uploaded_file(token: str, filename: str, content: bytes) -> Dict[str, Any]:
    """Saves a file uploaded to the server, enforcing storage quota, and returns file metadata."""
    check_storage_quota(token, len(content))

    token_dir = settings.uploads_path / token
    token_dir.mkdir(parents=True, exist_ok=True)

    file_uuid = uuid.uuid4().hex[:12]
    clean_filename = re.sub(r"[^\w\.-]", "_", filename) or "file.bin"
    disk_filename = f"{file_uuid}_{clean_filename}"
    file_path = token_dir / disk_filename

    file_path.write_bytes(content)

    file_id = f"up_{token[:8]}_{file_uuid}_{clean_filename}"
    rel_path = f"uploads/{token}/{disk_filename}"

    return {
        "file_id": file_id,
        "file_unique_id": f"unique_{file_uuid}",
        "file_size": len(content),
        "file_name": clean_filename,
        "file_path": rel_path,
        "disk_path": str(file_path),
    }


async def download_message_file(client: TelegramClient, token: str, chat_id: Union[int, str], message_id: int) -> Optional[Dict[str, Any]]:
    """Downloads media from Telegram message and caches it in STORAGE_DIR/files/<token>/."""
    msg = await client.get_messages(chat_id, ids=message_id)
    if not msg or not msg.media:
        return None

    token_dir = settings.files_path / token
    token_dir.mkdir(parents=True, exist_ok=True)

    # Check if previously downloaded
    existing_files = list(token_dir.glob(f"msg_{message_id}_*"))
    if existing_files:
        cached = existing_files[0]
        return {
            "file_id": generate_file_id(chat_id, message_id),
            "file_unique_id": f"unique_msg_{message_id}",
            "file_size": cached.stat().st_size,
            "file_path": f"files/{token}/{cached.name}",
            "disk_path": str(cached),
        }

    # Pre-check estimated size if available
    size_est = getattr(msg.media, "document", None)
    if size_est:
        doc_size = getattr(size_est, "size", 0)
        check_storage_quota(token, doc_size)

    # Download media
    target_pattern = str(token_dir / f"msg_{message_id}_")
    downloaded_path_str = await client.download_media(msg, file=target_pattern)
    if not downloaded_path_str:
        return None

    downloaded_path = Path(downloaded_path_str)
    file_size = downloaded_path.stat().st_size
    check_storage_quota(token, file_size)

    return {
        "file_id": generate_file_id(chat_id, message_id),
        "file_unique_id": f"unique_msg_{message_id}",
        "file_size": file_size,
        "file_path": f"files/{token}/{downloaded_path.name}",
        "disk_path": str(downloaded_path),
    }
