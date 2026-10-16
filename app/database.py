import sqlite3
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from app.config import settings

logger = logging.getLogger(__name__)


class Database:
    """SQLite-backed metadata storage for user sessions, bot relays, and API tokens."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(settings.db_path)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        """Create tables if they do not exist."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    session_name TEXT NOT NULL,
                    session_type TEXT NOT NULL, -- 'file', 'string', 'bot_relay'
                    session_string TEXT,
                    api_id INTEGER,
                    api_hash TEXT,
                    user_id INTEGER,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    phone TEXT,
                    proxy TEXT, -- JSON string
                    webhook_url TEXT,
                    storage_quota_mb INTEGER DEFAULT 500,
                    created_at TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
                """
            )
            # Migration check
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN storage_quota_mb INTEGER DEFAULT 500")
            except Exception:
                pass

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS temp_auth (
                    auth_token TEXT PRIMARY KEY,
                    phone TEXT NOT NULL,
                    phone_code_hash TEXT NOT NULL,
                    api_id INTEGER NOT NULL,
                    api_hash TEXT NOT NULL,
                    proxy TEXT,
                    session_string TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def save_session(
        self,
        token: str,
        session_name: str,
        session_type: str,
        api_id: Optional[int] = 0,
        api_hash: Optional[str] = "",
        session_string: Optional[str] = None,
        user_id: Optional[int] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        username: Optional[str] = None,
        phone: Optional[str] = None,
        proxy: Optional[Dict[str, Any]] = None,
        webhook_url: Optional[str] = None,
    ):
        """Insert or update session metadata."""
        now = datetime.now(timezone.utc).isoformat()
        proxy_json = json.dumps(proxy) if proxy else None

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    token, session_name, session_type, session_string,
                    api_id, api_hash, user_id, first_name, last_name,
                    username, phone, proxy, webhook_url, created_at, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(token) DO UPDATE SET
                    session_name=excluded.session_name,
                    session_type=excluded.session_type,
                    session_string=excluded.session_string,
                    api_id=excluded.api_id,
                    api_hash=excluded.api_hash,
                    user_id=excluded.user_id,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    username=excluded.username,
                    phone=excluded.phone,
                    proxy=excluded.proxy,
                    webhook_url=excluded.webhook_url,
                    is_active=1
                """,
                (
                    token,
                    session_name,
                    session_type,
                    session_string,
                    api_id,
                    api_hash,
                    user_id,
                    first_name,
                    last_name,
                    username,
                    phone,
                    proxy_json,
                    webhook_url,
                    now,
                ),
            )
            conn.commit()

    def save_bot_relay(self, token: str, proxy: Optional[Dict[str, Any]] = None, bot_username: Optional[str] = None):
        """Register an official Telegram bot token for reverse proxy relay with optional proxy."""
        now = datetime.now(timezone.utc).isoformat()
        proxy_json = json.dumps(proxy) if proxy else None

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    token, session_name, session_type, session_string,
                    api_id, api_hash, username, proxy, created_at, is_active
                ) VALUES (?, ?, 'bot_relay', NULL, 0, '', ?, ?, ?, 1)
                ON CONFLICT(token) DO UPDATE SET
                    proxy=excluded.proxy,
                    username=coalesce(excluded.username, sessions.username),
                    is_active=1
                """,
                (token, f"bot_{token[:8]}", bot_username, proxy_json, now),
            )
            conn.commit()

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        """Retrieve session record by token."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM sessions WHERE token = ? AND is_active = 1", (token,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            if res.get("proxy"):
                try:
                    res["proxy"] = json.loads(res["proxy"])
                except Exception:
                    res["proxy"] = None
            return res

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all active sessions (without sensitive keys in summary)."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT token, session_name, session_type, user_id, first_name, username, phone, created_at, webhook_url FROM sessions WHERE is_active = 1")
            return [dict(row) for row in cursor.fetchall()]

    def update_proxy(self, token: str, proxy: Optional[Dict[str, Any]]):
        """Update proxy for session or bot relay."""
        proxy_json = json.dumps(proxy) if proxy else None
        with self._get_connection() as conn:
            # If session doesn't exist yet but looks like a bot token, register it
            cursor = conn.execute("SELECT token FROM sessions WHERE token = ?", (token,))
            if not cursor.fetchone():
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT INTO sessions (
                        token, session_name, session_type, api_id, api_hash, proxy, created_at, is_active
                    ) VALUES (?, ?, 'bot_relay', 0, '', ?, ?, 1)
                    """,
                    (token, f"bot_{token[:8]}", proxy_json, now),
                )
            else:
                conn.execute("UPDATE sessions SET proxy = ? WHERE token = ?", (proxy_json, token))
            conn.commit()

    def update_webhook(self, token: str, webhook_url: Optional[str]):
        """Update webhook URL for session."""
        with self._get_connection() as conn:
            conn.execute("UPDATE sessions SET webhook_url = ? WHERE token = ?", (webhook_url, token))
            conn.commit()

    def rotate_token(self, old_token: str, new_token: str) -> bool:
        """Atomically rotate API token for an existing session."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT token FROM sessions WHERE token = ? AND is_active = 1", (old_token,))
            if not cursor.fetchone():
                return False
            conn.execute("UPDATE sessions SET token = ? WHERE token = ?", (new_token, old_token))
            conn.commit()
            return True

    def delete_session(self, token: str):
        """Mark session as inactive / deleted."""
        with self._get_connection() as conn:
            conn.execute("UPDATE sessions SET is_active = 0 WHERE token = ?", (token,))
            conn.commit()

    def hard_delete_session(self, token: str) -> bool:
        """Permanently delete session row from database."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return cursor.rowcount > 0

    def get_session_storage_used_bytes(self, token: str) -> int:
        """Calculates total disk space in bytes used by this session's files."""
        total = 0
        record = self.get_session(token)
        if not record:
            return 0

        # Session SQLite file
        if record.get("session_type") == "file":
            s_name = record.get("session_name")
            if s_name:
                p = settings.sessions_path / f"{s_name}.session"
                if p.exists():
                    total += p.stat().st_size
                p_j = settings.sessions_path / f"{s_name}.session-journal"
                if p_j.exists():
                    total += p_j.stat().st_size

        # Downloaded files for this token
        token_files = settings.files_path / token
        if token_files.exists():
            for f in token_files.glob("**/*"):
                if f.is_file():
                    total += f.stat().st_size

        # Uploaded files for this token
        token_uploads = settings.uploads_path / token
        if token_uploads.exists():
            for f in token_uploads.glob("**/*"):
                if f.is_file():
                    total += f.stat().st_size

        return total

    def update_user_quota(self, token: str, quota_mb: int) -> bool:
        """Update storage quota in MB for a specific session."""
        with self._get_connection() as conn:
            cursor = conn.execute("UPDATE sessions SET storage_quota_mb = ? WHERE token = ?", (quota_mb, token))
            conn.commit()
            return cursor.rowcount > 0

    def list_all_sessions_admin(self) -> List[Dict[str, Any]]:
        """List detailed session information for admin dashboard."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT token, session_name, session_type, api_id, user_id,
                       first_name, last_name, username, phone, proxy,
                       webhook_url, storage_quota_mb, created_at, is_active
                FROM sessions
                ORDER BY created_at DESC
                """
            )
            rows = [dict(r) for r in cursor.fetchall()]

        for r in rows:
            if r.get("proxy"):
                try:
                    r["proxy"] = json.loads(r["proxy"])
                except Exception:
                    pass
            used_bytes = self.get_session_storage_used_bytes(r["token"])
            r["storage_used_bytes"] = used_bytes
            r["storage_used_mb"] = round(used_bytes / (1024 * 1024), 2)
            r["storage_quota_mb"] = r.get("storage_quota_mb") or settings.DEFAULT_USER_QUOTA_MB

        return rows

    def get_stats_summary(self) -> Dict[str, Any]:
        """Calculates server-wide stats for admin dashboard."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM sessions WHERE is_active = 1")
            total_active = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM sessions WHERE is_active = 1 AND session_type = 'bot_relay'")
            bot_relays = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM sessions WHERE is_active = 1 AND session_type != 'bot_relay'")
            user_sessions = cursor.fetchone()[0]

        total_storage_bytes = 0
        if settings.storage_path.exists():
            for p in settings.storage_path.glob("**/*"):
                if p.is_file():
                    total_storage_bytes += p.stat().st_size

        return {
            "total_active_sessions": total_active,
            "user_sessions_count": user_sessions,
            "bot_relays_count": bot_relays,
            "total_storage_used_bytes": total_storage_bytes,
            "total_storage_used_mb": round(total_storage_bytes / (1024 * 1024), 2),
            "storage_directory": str(settings.storage_path),
            "default_user_quota_mb": settings.DEFAULT_USER_QUOTA_MB,
        }

    def get_session_export(self, token: str) -> Optional[Dict[str, Any]]:
        """Retrieve full session data for exporting."""
        record = self.get_session(token)
        if not record:
            return None

        res = dict(record)
        session_file_path = None
        if record.get("session_type") == "file":
            s_name = record.get("session_name")
            p = settings.sessions_path / f"{s_name}.session"
            if p.exists():
                session_file_path = str(p)

        res["session_file_path"] = session_file_path
        return res

    # Temporary login state for 2-step phone auth
    def save_temp_auth(
        self,
        auth_token: str,
        phone: str,
        phone_code_hash: str,
        api_id: int,
        api_hash: str,
        proxy: Optional[Dict[str, Any]] = None,
        session_string: Optional[str] = None,
    ):
        now = datetime.now(timezone.utc).isoformat()
        proxy_json = json.dumps(proxy) if proxy else None
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO temp_auth (
                    auth_token, phone, phone_code_hash, api_id, api_hash, proxy, session_string, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (auth_token, phone, phone_code_hash, api_id, api_hash, proxy_json, session_string, now),
            )
            conn.commit()

    def get_temp_auth(self, auth_token: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM temp_auth WHERE auth_token = ?", (auth_token,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            if res.get("proxy"):
                try:
                    res["proxy"] = json.loads(res["proxy"])
                except Exception:
                    res["proxy"] = None
            return res

    def delete_temp_auth(self, auth_token: str):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM temp_auth WHERE auth_token = ?", (auth_token,))
            conn.commit()


db = Database()
