import logging
from typing import Optional, Dict, Any, List
from telethon import utils
from telethon.tl.types import (
    User as TelethonUser,
    Chat as TelethonChat,
    Channel as TelethonChannel,
    Message as TelethonMessage,
    MessageMediaPhoto,
    MessageMediaDocument,
    MessageMediaContact,
    MessageMediaGeo,
    DocumentAttributeFilename,
    DocumentAttributeAudio,
    DocumentAttributeVideo,
    ChannelParticipantCreator,
    ChannelParticipantAdmin,
    ChatParticipantCreator,
    ChatParticipantAdmin,
)

logger = logging.getLogger(__name__)


def serialize_user(user: Any) -> Optional[Dict[str, Any]]:
    """Converts a Telethon User object to a Telegram Bot API User dictionary."""
    if not user:
        return None

    user_id = getattr(user, "id", None)
    if user_id is None:
        return None

    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", None)
    username = getattr(user, "username", None)
    phone = getattr(user, "phone", None)
    is_bot = getattr(user, "bot", False)
    lang_code = getattr(user, "lang_code", None)

    res: Dict[str, Any] = {
        "id": int(user_id),
        "is_bot": bool(is_bot),
        "first_name": first_name or (username or f"User_{user_id}"),
        "can_join_groups": True,
        "can_read_all_group_messages": True,
        "supports_inline_queries": False,
    }

    if last_name:
        res["last_name"] = last_name
    if username:
        res["username"] = username
    if lang_code:
        res["language_code"] = lang_code
    if phone:
        res["phone_number"] = phone

    return res


def serialize_chat(entity: Any) -> Optional[Dict[str, Any]]:
    """Converts a Telethon Chat, Channel, or User entity to a Telegram Bot API Chat dictionary."""
    if not entity:
        return None

    try:
        peer_id = utils.get_peer_id(entity)
    except Exception:
        peer_id = getattr(entity, "id", 0)

    # Determine chat type
    chat_type = "private"
    title = None
    first_name = None
    last_name = None
    username = getattr(entity, "username", None)

    if isinstance(entity, (TelethonChat,)):
        chat_type = "group"
        title = getattr(entity, "title", "Group")
    elif isinstance(entity, (TelethonChannel,)):
        if getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False):
            chat_type = "supergroup"
        else:
            chat_type = "channel"
        title = getattr(entity, "title", "Channel")
    elif isinstance(entity, TelethonUser) or peer_id > 0:
        chat_type = "private"
        first_name = getattr(entity, "first_name", "") or ""
        last_name = getattr(entity, "last_name", None)

    res: Dict[str, Any] = {
        "id": int(peer_id),
        "type": chat_type,
    }

    if title:
        res["title"] = title
    if username:
        res["username"] = username
    if first_name:
        res["first_name"] = first_name
    if last_name:
        res["last_name"] = last_name

    about = getattr(entity, "about", None)
    if about:
        res["bio"] = about
        res["description"] = about

    return res


def serialize_message(message: Any) -> Optional[Dict[str, Any]]:
    """Converts a Telethon Message object to a Telegram Bot API Message dictionary."""
    if not message or not isinstance(message, TelethonMessage):
        return None

    msg_id = getattr(message, "id", 0)
    date_val = int(message.date.timestamp()) if hasattr(message, "date") and message.date else 0

    # Sender & Chat
    sender_user = None
    sender_chat = None

    if message.sender:
        if isinstance(message.sender, TelethonUser):
            sender_user = serialize_user(message.sender)
        else:
            sender_chat = serialize_chat(message.sender)

    chat_obj = serialize_chat(message.chat) or ({"id": message.chat_id, "type": "private"} if message.chat_id else None)

    res: Dict[str, Any] = {
        "message_id": msg_id,
        "date": date_val,
        "chat": chat_obj,
    }

    if sender_user:
        res["from"] = sender_user
    if sender_chat:
        res["sender_chat"] = sender_chat

    # Text / Caption
    text_content = getattr(message, "raw_text", "") or getattr(message, "message", "") or ""

    if message.media:
        if text_content:
            res["caption"] = text_content
        media = message.media

        if isinstance(media, MessageMediaPhoto):
            res["photo"] = [
                {
                    "file_id": f"photo_{msg_id}",
                    "file_unique_id": f"unique_photo_{msg_id}",
                    "width": 1280,
                    "height": 720,
                    "file_size": 100000,
                }
            ]
        elif isinstance(media, MessageMediaDocument):
            doc = media.document
            doc_id = getattr(doc, "id", msg_id)
            mime_type = getattr(doc, "mime_type", "application/octet-stream")
            size = getattr(doc, "size", 0)

            doc_attributes = getattr(doc, "attributes", [])
            filename = "document"
            is_audio = False
            is_video = False
            is_voice = False
            duration = 0
            title = None
            performer = None

            for attr in doc_attributes:
                if isinstance(attr, DocumentAttributeFilename):
                    filename = attr.file_name
                elif isinstance(attr, DocumentAttributeAudio):
                    if getattr(attr, "voice", False):
                        is_voice = True
                    else:
                        is_audio = True
                    duration = getattr(attr, "duration", 0)
                    title = getattr(attr, "title", None)
                    performer = getattr(attr, "performer", None)
                elif isinstance(attr, DocumentAttributeVideo):
                    is_video = True
                    duration = getattr(attr, "duration", 0)

            if is_voice:
                res["voice"] = {
                    "file_id": f"voice_{doc_id}",
                    "file_unique_id": f"unique_voice_{doc_id}",
                    "duration": duration,
                    "mime_type": mime_type,
                    "file_size": size,
                }
            elif is_audio:
                res["audio"] = {
                    "file_id": f"audio_{doc_id}",
                    "file_unique_id": f"unique_audio_{doc_id}",
                    "duration": duration,
                    "performer": performer,
                    "title": title,
                    "file_name": filename,
                    "mime_type": mime_type,
                    "file_size": size,
                }
            elif is_video:
                res["video"] = {
                    "file_id": f"video_{doc_id}",
                    "file_unique_id": f"unique_video_{doc_id}",
                    "duration": duration,
                    "file_name": filename,
                    "mime_type": mime_type,
                    "file_size": size,
                }
            else:
                res["document"] = {
                    "file_id": f"doc_{doc_id}",
                    "file_unique_id": f"unique_doc_{doc_id}",
                    "file_name": filename,
                    "mime_type": mime_type,
                    "file_size": size,
                }
        elif isinstance(media, MessageMediaContact):
            res["contact"] = {
                "phone_number": media.phone_number,
                "first_name": media.first_name,
                "last_name": media.last_name or "",
                "user_id": media.user_id,
            }
        elif isinstance(media, MessageMediaGeo):
            geo = media.geo
            res["location"] = {
                "longitude": getattr(geo, "long", 0.0),
                "latitude": getattr(geo, "lat", 0.0),
            }
    else:
        res["text"] = text_content

    # Reply
    if getattr(message, "reply_to", None):
        reply_to_msg_id = getattr(message.reply_to, "reply_to_msg_id", None)
        if reply_to_msg_id:
            res["reply_to_message"] = {
                "message_id": reply_to_msg_id,
                "date": date_val,
                "chat": chat_obj,
            }

    # Forward
    if getattr(message, "forward", None):
        fwd = message.forward
        if getattr(fwd, "sender", None):
            res["forward_from"] = serialize_user(fwd.sender)
        elif getattr(fwd, "chat", None):
            res["forward_from_chat"] = serialize_chat(fwd.chat)
        if getattr(fwd, "date", None):
            res["forward_date"] = int(fwd.date.timestamp())

    # Edit date
    if getattr(message, "edit_date", None):
        res["edit_date"] = int(message.edit_date.timestamp())

    return res


def serialize_chat_member(participant: Any, user: Any) -> Dict[str, Any]:
    """Converts a Telethon chat participant to a Telegram Bot API ChatMember dictionary."""
    user_dict = serialize_user(user)

    if isinstance(participant, (ChannelParticipantCreator, ChatParticipantCreator)):
        return {
            "status": "creator",
            "user": user_dict,
            "is_anonymous": False,
        }
    elif isinstance(participant, (ChannelParticipantAdmin, ChatParticipantAdmin)):
        return {
            "status": "administrator",
            "user": user_dict,
            "can_be_edited": False,
            "can_manage_chat": True,
            "can_change_info": getattr(participant.admin_rights, "change_info", True) if hasattr(participant, "admin_rights") else True,
            "can_post_messages": getattr(participant.admin_rights, "post_messages", True) if hasattr(participant, "admin_rights") else True,
            "can_edit_messages": getattr(participant.admin_rights, "edit_messages", True) if hasattr(participant, "admin_rights") else True,
            "can_delete_messages": getattr(participant.admin_rights, "delete_messages", True) if hasattr(participant, "admin_rights") else True,
            "can_invite_users": getattr(participant.admin_rights, "invite_users", True) if hasattr(participant, "admin_rights") else True,
            "can_restrict_members": getattr(participant.admin_rights, "ban_users", True) if hasattr(participant, "admin_rights") else True,
            "can_pin_messages": getattr(participant.admin_rights, "pin_messages", True) if hasattr(participant, "admin_rights") else True,
            "can_promote_members": getattr(participant.admin_rights, "add_admins", False) if hasattr(participant, "admin_rights") else False,
        }
    else:
        return {
            "status": "member",
            "user": user_dict,
        }


def serialize_update(update_id: int, message: TelethonMessage) -> Dict[str, Any]:
    """Wraps a serialized message into a Telegram Bot API Update dictionary."""
    return {
        "update_id": update_id,
        "message": serialize_message(message),
    }
