import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Header, Query, HTTPException, Depends
from pydantic import BaseModel, Field

from app.config import settings
from app.database import db
from app.core.client_manager import client_manager
from app.models.schemas import TelegramResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Server Administration"])


class UpdateQuotaRequest(BaseModel):
    quota_mb: int = Field(..., description="Storage quota in Megabytes (e.g. 1000 for 1GB)")


def verify_admin(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(None),
    admin_token: Optional[str] = Query(None),
):
    """Dependency verifying admin credentials against ADMIN_TOKEN in .env."""
    provided = x_admin_token or admin_token
    if not provided and authorization:
        if authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        else:
            provided = authorization.strip()

    if not provided or provided != settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=401,
            detail={"ok": False, "error_code": 401, "description": "Unauthorized: Invalid or missing admin token."},
        )
    return True


@router.get("/stats", response_model=TelegramResponse)
async def get_admin_stats(authenticated: bool = Depends(verify_admin)):
    """
    Get server-wide statistics, active session counts, and storage utilization.
    Requires admin authentication.
    """
    stats = db.get_stats_summary()
    return TelegramResponse(ok=True, result=stats)


@router.get("/sessions", response_model=TelegramResponse)
async def list_admin_sessions(authenticated: bool = Depends(verify_admin)):
    """
    Get all registered sessions with detailed user info, permissions, storage usage, and quota limits.
    Requires admin authentication.
    """
    sessions = db.list_all_sessions_admin()
    return TelegramResponse(ok=True, result=sessions)


@router.post("/sessions/{token}/quota", response_model=TelegramResponse)
async def update_session_quota(token: str, req: UpdateQuotaRequest, authenticated: bool = Depends(verify_admin)):
    """
    Configure the maximum disk storage quota (in Megabytes) for a specific user session.
    Requires admin authentication.
    """
    session = db.get_session(token)
    if not session:
        return TelegramResponse(ok=False, error_code=404, description="Session token not found.")

    success = db.update_user_quota(token, req.quota_mb)
    if success:
        return TelegramResponse(
            ok=True,
            result={
                "token": token,
                "storage_quota_mb": req.quota_mb,
                "message": f"Storage quota successfully updated to {req.quota_mb}MB.",
            },
        )
    return TelegramResponse(ok=False, error_code=500, description="Failed to update quota in database.")


@router.delete("/sessions/{token}", response_model=TelegramResponse)
async def admin_delete_session(token: str, terminate: bool = False, authenticated: bool = Depends(verify_admin)):
    """
    Admin endpoint to unlink or permanently terminate any session.
    If terminate=True, logs out of Telegram. Otherwise unlinks locally.
    """
    session = db.get_session(token)
    if not session:
        return TelegramResponse(ok=False, error_code=404, description="Session token not found.")

    if terminate:
        await client_manager.terminate_session(token)
        msg = "Session terminated on Telegram servers and deleted from server."
    else:
        await client_manager.unlink_session(token)
        msg = "Session unlinked and deleted from server."

    return TelegramResponse(ok=True, result={"token": token, "message": msg})
