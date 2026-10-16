import asyncio
import logging
import httpx
from typing import Dict, List, Optional, Any
from app.database import db

logger = logging.getLogger(__name__)


class SessionUpdateQueue:
    """Manages update buffer and long polling for a single user token."""

    def __init__(self, token: str):
        self.token = token
        self.current_update_id = 1000
        self.updates: List[Dict[str, Any]] = []
        self._new_update_event = asyncio.Event()
        self._lock = asyncio.Lock()

    async def add_update(self, raw_update_payload: Dict[str, Any]):
        """Append an update to queue or dispatch to webhook."""
        async with self._lock:
            self.current_update_id += 1
            update_id = self.current_update_id
            update = {"update_id": update_id, **raw_update_payload}

            session_data = db.get_session(self.token)
            webhook_url = session_data.get("webhook_url") if session_data else None

            if webhook_url:
                # Dispatch async to webhook
                asyncio.create_task(self._send_webhook(webhook_url, update))
            else:
                # Store in buffer (limit to 1000 items)
                self.updates.append(update)
                if len(self.updates) > 1000:
                    self.updates.pop(0)

                self._new_update_event.set()

    async def _send_webhook(self, url: str, update: Dict[str, Any]):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=update)
                if resp.status_code >= 400:
                    logger.warning(f"Webhook {url} responded with status {resp.status_code}")
        except Exception as e:
            logger.error(f"Failed to post update to webhook {url}: {e}")

    async def get_updates(
        self,
        offset: Optional[int] = None,
        limit: int = 100,
        timeout: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Fetches pending updates, honoring offset, limit, and long-polling timeout.
        """
        async with self._lock:
            # Check if webhook is active
            session_data = db.get_session(self.token)
            if session_data and session_data.get("webhook_url"):
                raise ValueError("can't use getUpdates method while webhook is active; use deleteWebhook first")

            # Acknowledge past updates if offset is provided
            if offset is not None:
                self.updates = [u for u in self.updates if u["update_id"] >= offset]

            # If updates are available or timeout is 0, return immediately
            if self.updates or timeout <= 0:
                result = self.updates[:limit]
                return result

            # Otherwise reset event to prepare for waiting
            self._new_update_event.clear()

        # Wait for new updates up to timeout seconds
        try:
            await asyncio.wait_for(self._new_update_event.wait(), timeout=float(timeout))
        except asyncio.TimeoutError:
            pass

        async with self._lock:
            if offset is not None:
                self.updates = [u for u in self.updates if u["update_id"] >= offset]
            result = self.updates[:limit]
            return result


class UpdateManager:
    """Registry of SessionUpdateQueue instances keyed by token."""

    def __init__(self):
        self._queues: Dict[str, SessionUpdateQueue] = {}

    def get_queue(self, token: str) -> SessionUpdateQueue:
        if token not in self._queues:
            self._queues[token] = SessionUpdateQueue(token)
        return self._queues[token]

    def remove_queue(self, token: str):
        self._queues.pop(token, None)


update_manager = UpdateManager()
