import asyncio
import logging
import secrets
from pathlib import Path
from typing import Dict, Optional, Any, Tuple
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from app.config import settings
from app.database import db
from app.core.proxy import ProxyConfig
from app.core.serializers import serialize_message, serialize_user
from app.core.update_queue import update_manager

logger = logging.getLogger(__name__)


class ClientManager:
    """Manages Telethon TelegramClient lifecycles, connection pooling, and message events."""

    def __init__(self):
        self._clients: Dict[str, TelegramClient] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def _get_lock(self, token: str) -> asyncio.Lock:
        if token not in self._locks:
            self._locks[token] = asyncio.Lock()
        return self._locks[token]

    async def get_client(self, token: str) -> TelegramClient:
        """Retrieves an active connected TelegramClient for token or initializes one."""
        async with self._get_lock(token):
            if token in self._clients:
                client = self._clients[token]
                if client.is_connected():
                    return client
                else:
                    try:
                        await client.connect()
                        if await client.is_user_authorized():
                            return client
                    except Exception as e:
                        logger.warning(f"Reconnecting client for token {token[:10]} failed: {e}")

            session_record = db.get_session(token)
            if not session_record:
                raise KeyError("Unauthorized: Invalid user token")

            client = await self._create_client_from_record(session_record)
            self._clients[token] = client
            self._attach_listeners(token, client)
            return client

    async def _create_client_from_record(self, record: Dict[str, Any]) -> TelegramClient:
        """Instantiates and connects a TelegramClient from database record."""
        session_type = record.get("session_type", "file")
        session_name = record["session_name"]
        api_id = record["api_id"]
        api_hash = record["api_hash"]

        if session_type == "string":
            session = StringSession(record.get("session_string") or "")
        else:
            session_file_path = settings.sessions_path / session_name
            session = str(session_file_path)

        # Determine proxy
        proxy_config = None
        if record.get("proxy"):
            try:
                proxy_config = ProxyConfig.parse(record["proxy"])
            except Exception as e:
                logger.error(f"Error parsing proxy for token {record['token'][:10]}: {e}")

        if not proxy_config and settings.DEFAULT_PROXY:
            try:
                proxy_config = ProxyConfig.parse(settings.DEFAULT_PROXY)
            except Exception as e:
                logger.error(f"Error parsing DEFAULT_PROXY: {e}")

        connection_class = None
        proxy_args = None
        if proxy_config:
            connection_class, proxy_args = proxy_config.get_telethon_args()

        kwargs: Dict[str, Any] = {
            "flood_sleep_threshold": settings.FLOOD_SLEEP_THRESHOLD,
            "request_retries": settings.REQUEST_RETRIES,
            "connection_retries": settings.CONNECTION_RETRIES,
        }
        if connection_class:
            kwargs["connection"] = connection_class
        if proxy_args:
            kwargs["proxy"] = proxy_args

        client = TelegramClient(session, api_id, api_hash, **kwargs)
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            raise PermissionError("User session is expired or not authorized.")

        return client

    def _attach_listeners(self, token: str, client: TelegramClient):
        """Attaches event listeners to route incoming updates to update_queue."""
        @client.on(events.NewMessage)
        async def on_new_message(event):
            try:
                serialized = serialize_message(event.message)
                if serialized:
                    queue = update_manager.get_queue(token)
                    await queue.add_update({"message": serialized})
            except Exception as e:
                logger.error(f"Error dispatching update for token {token[:10]}: {e}")

        @client.on(events.MessageEdited)
        async def on_message_edited(event):
            try:
                serialized = serialize_message(event.message)
                if serialized:
                    queue = update_manager.get_queue(token)
                    await queue.add_update({"edited_message": serialized})
            except Exception as e:
                logger.error(f"Error dispatching edited message update: {e}")

    async def register_session(
        self,
        api_id: int,
        api_hash: str,
        session_file_bytes: Optional[bytes] = None,
        session_string: Optional[str] = None,
        proxy_config: Optional[ProxyConfig] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Validates session, registers in database, and returns (token, user_dict).
        """
        token = f"usr_{secrets.token_hex(20)}"
        session_name = f"session_{secrets.token_hex(8)}"

        if session_file_bytes:
            session_type = "file"
            session_file_path = settings.sessions_path / f"{session_name}.session"
            session_file_path.write_bytes(session_file_bytes)
            session = str(settings.sessions_path / session_name)
        elif session_string:
            session_type = "string"
            session = StringSession(session_string.strip())
        else:
            raise ValueError("Either session_file or session_string must be provided.")

        connection_class = None
        proxy_args = None
        if proxy_config:
            connection_class, proxy_args = proxy_config.get_telethon_args()
        elif settings.DEFAULT_PROXY:
            try:
                p = ProxyConfig.parse(settings.DEFAULT_PROXY)
                if p:
                    connection_class, proxy_args = p.get_telethon_args()
            except Exception:
                pass

        kwargs: Dict[str, Any] = {}
        if connection_class:
            kwargs["connection"] = connection_class
        if proxy_args:
            kwargs["proxy"] = proxy_args

        client = TelegramClient(session, api_id, api_hash, **kwargs)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise PermissionError("Telegram session is not authorized. Check session data.")

            me = await client.get_me()
            user_data = serialize_user(me)

            proxy_dict = proxy_config.to_dict() if proxy_config else None

            # Save in database
            db.save_session(
                token=token,
                session_name=session_name,
                session_type=session_type,
                api_id=api_id,
                api_hash=api_hash,
                session_string=session_string if session_type == "string" else None,
                user_id=me.id,
                first_name=me.first_name,
                last_name=me.last_name,
                username=me.username,
                phone=me.phone,
                proxy=proxy_dict,
            )

            # Store in cache
            self._clients[token] = client
            self._attach_listeners(token, client)

            return token, user_data
        except Exception:
            if client.is_connected():
                await client.disconnect()
            if session_type == "file":
                f_path = settings.sessions_path / f"{session_name}.session"
                if f_path.exists():
                    f_path.unlink()
            raise

    async def update_client_proxy(self, token: str, proxy_config: Optional[ProxyConfig]):
        """Updates proxy config for a session, reconnecting the client."""
        async with self._get_lock(token):
            # Disconnect active client if running
            if token in self._clients:
                client = self._clients.pop(token)
                try:
                    if client.is_connected():
                        await client.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting client during proxy update: {e}")

            proxy_dict = proxy_config.to_dict() if proxy_config else None
            db.update_proxy(token, proxy_dict)

            # Re-initialize client with new proxy
            new_client = await self.get_client(token)
            return new_client

    async def disconnect_client(self, token: str):
        """Disconnect and remove client from active cache."""
        async with self._get_lock(token):
            if token in self._clients:
                client = self._clients.pop(token)
                try:
                    if client.is_connected():
                        await client.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting client {token[:10]}: {e}")

    async def rotate_token(self, old_token: str, new_token: Optional[str] = None) -> str:
        """Rotates the API token for an existing session."""
        session_record = db.get_session(old_token)
        if not session_record:
            raise KeyError("Unauthorized: Invalid user token")

        final_token = new_token or f"usr_{secrets.token_hex(20)}"
        success = db.rotate_token(old_token, final_token)
        if not success:
            raise ValueError("Failed to rotate token in database")

        async with self._global_lock:
            if old_token in self._clients:
                self._clients[final_token] = self._clients.pop(old_token)
            if old_token in self._locks:
                self._locks[final_token] = self._locks.pop(old_token)

        old_queue = update_manager._queues.pop(old_token, None)
        if old_queue:
            old_queue.token = final_token
            update_manager._queues[final_token] = old_queue

        return final_token

    async def unlink_session(self, token: str, delete_file: bool = True) -> bool:
        """Unlinks and deletes session from server without logging out of Telegram."""
        async with self._get_lock(token):
            record = db.get_session(token)
            if token in self._clients:
                client = self._clients.pop(token)
                try:
                    if client.is_connected():
                        await client.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting client {token[:10]}: {e}")

            if record and delete_file and record.get("session_type") == "file":
                s_name = record.get("session_name")
                if s_name:
                    p = settings.sessions_path / f"{s_name}.session"
                    if p.exists():
                        p.unlink()
                    p_j = settings.sessions_path / f"{s_name}.session-journal"
                    if p_j.exists():
                        p_j.unlink()

            db.hard_delete_session(token)
            update_manager.remove_queue(token)
            return True

    async def terminate_session(self, token: str) -> bool:
        """Terminates session on Telegram servers (logOut) and deletes from server."""
        async with self._get_lock(token):
            record = db.get_session(token)
            if not record:
                raise KeyError("Unauthorized: Invalid user token")

            client = None
            if token in self._clients:
                client = self._clients.pop(token)
            else:
                try:
                    client = await self._create_client_from_record(record)
                except Exception as e:
                    logger.warning(f"Could not connect client to log out: {e}")

            if client:
                try:
                    if not client.is_connected():
                        await client.connect()
                    await client.log_out()
                except Exception as e:
                    logger.warning(f"Error logging out of Telegram: {e}")
                finally:
                    try:
                        if client.is_connected():
                            await client.disconnect()
                    except Exception:
                        pass

            if record.get("session_type") == "file":
                s_name = record.get("session_name")
                if s_name:
                    p = settings.sessions_path / f"{s_name}.session"
                    if p.exists():
                        p.unlink()

            db.hard_delete_session(token)
            update_manager.remove_queue(token)
            return True

    async def close_all(self):
        """Cleanly disconnect all clients on shutdown."""
        for token, client in list(self._clients.items()):
            try:
                if client.is_connected():
                    await client.disconnect()
            except Exception as e:
                logger.warning(f"Error closing client during shutdown: {e}")
        self._clients.clear()


client_manager = ClientManager()
