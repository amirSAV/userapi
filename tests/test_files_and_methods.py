import pytest
import io
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings
from app.database import db
from app.core.file_manager import (
    generate_file_id,
    parse_file_id,
    check_storage_quota,
    save_uploaded_file,
)


def test_file_id_generation_and_parsing():
    fid = generate_file_id(-100123456789, 42, "photo")
    assert fid == "msg_n100123456789_42_photo"

    parsed = parse_file_id(fid)
    assert parsed is not None
    assert parsed["type"] == "message"
    assert parsed["chat_id"] == -100123456789
    assert parsed["message_id"] == 42
    assert parsed["media_type"] == "photo"

    up_fid = "up_abcdef12_uuid123_test.png"
    up_parsed = parse_file_id(up_fid)
    assert up_parsed is not None
    assert up_parsed["type"] == "upload"


@pytest.mark.asyncio
async def test_storage_quota_enforcement():
    token = "usr_quota_test_token"
    db.save_session(
        token=token,
        session_name="quota_test_sess",
        session_type="string",
        api_id=123,
        api_hash="hash",
    )
    # Set quota to 1MB
    db.update_user_quota(token, quota_mb=1)

    # 500KB should pass
    assert check_storage_quota(token, 500 * 1024) is True

    # 2MB should fail
    with pytest.raises(PermissionError):
        check_storage_quota(token, 2 * 1024 * 1024)

    # Clean up
    db.hard_delete_session(token)


@pytest.mark.asyncio
async def test_file_upload_and_download_endpoint():
    token = "usr_upload_test_token"
    db.save_session(
        token=token,
        session_name="upload_test_sess",
        session_type="string",
        api_id=123,
        api_hash="hash",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Save a test uploaded file via save_uploaded_file
        test_bytes = b"Hello, UserAPI file test!"
        file_info = await save_uploaded_file(token, "test.txt", test_bytes)
        assert file_info["file_size"] == len(test_bytes)
        assert "file_path" in file_info

        # Download via /file/bot<token>/<file_path>
        dl_resp = await client.get(f"/file/bot{token}/{file_info['file_path']}")
        assert dl_resp.status_code == 200
        assert dl_resp.content == test_bytes

    # Clean up
    db.hard_delete_session(token)
    p = Path(file_info["disk_path"])
    if p.exists():
        p.unlink()
