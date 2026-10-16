import os
from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    APP_NAME: str = "UserAPI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Storage directory for sessions, database, and temporary uploads
    STORAGE_DIR: str = Field(default="./data", description="Path to persist sessions and database")

    # Optional default Telegram API credentials (if client does not provide their own)
    DEFAULT_API_ID: Optional[int] = None
    DEFAULT_API_HASH: Optional[str] = None

    # Optional global fallback proxy (e.g. socks5://127.0.0.1:1080 or mtproto://secret@host:port)
    DEFAULT_PROXY: Optional[str] = None

    # Admin token for server management and user monitoring
    ADMIN_TOKEN: str = Field(default="admin_secret_token_123", description="Secret token for admin API access")

    # Default disk storage quota per user session in Megabytes
    DEFAULT_USER_QUOTA_MB: int = Field(default=500, description="Default storage quota in MB per session")

    # Max upload file size in Megabytes
    MAX_UPLOAD_SIZE_MB: int = 50

    # CORS origins
    CORS_ORIGINS: List[str] = ["*"]

    # Session settings
    FLOOD_SLEEP_THRESHOLD: int = 60
    REQUEST_RETRIES: int = 5
    CONNECTION_RETRIES: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def storage_path(self) -> Path:
        path = Path(self.STORAGE_DIR).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def sessions_path(self) -> Path:
        path = self.storage_path / "sessions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def uploads_path(self) -> Path:
        path = self.storage_path / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def files_path(self) -> Path:
        path = self.storage_path / "files"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_path(self) -> Path:
        return self.storage_path / "userapi.db"


settings = Settings()
