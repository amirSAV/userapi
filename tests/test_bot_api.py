import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_help_json():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/help?format=json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "supported_bot_api_methods" in data["result"]
        assert "sendMessage" in data["result"]["supported_bot_api_methods"]
        assert "bot_only_unsupported_features" in data["result"]


@pytest.mark.asyncio
async def test_help_html():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/help")
        assert resp.status_code == 200
        assert "UserAPI Documentation" in resp.text


@pytest.mark.asyncio
async def test_bot_only_methods_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # setMyCommands
        resp = await client.post("/botfake_token/setMyCommands")
        assert resp.status_code == 400
        data = resp.json()
        assert data["ok"] is False
        assert data["error_code"] == 400
        assert "restricted to Bot accounts only" in data["description"]

        # answerCallbackQuery
        resp2 = await client.post("/botfake_token/answerCallbackQuery")
        assert resp2.status_code == 400
        data2 = resp2.json()
        assert data2["ok"] is False
        assert "answerCallbackQuery" in data2["description"]

        # sendInvoice
        resp3 = await client.post("/botfake_token/sendInvoice")
        assert resp3.status_code == 400
        data3 = resp3.json()
        assert data3["ok"] is False
        assert "Payments and invoices" in data3["description"]


@pytest.mark.asyncio
async def test_invalid_token_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/botnon_existent_token_12345/getMe")
        assert resp.status_code == 401
        data = resp.json()
        assert data["ok"] is False
        assert data["error_code"] == 401
        assert "Unauthorized" in data["description"]


@pytest.mark.asyncio
async def test_auth_register_validation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Missing api_id and api_hash
        resp = await client.post("/auth/register")
        assert resp.status_code == 200  # returns 200 with ok=False in Telegram Bot API style
        data = resp.json()
        assert data["ok"] is False
        assert "api_id" in data["description"]


@pytest.mark.asyncio
async def test_proxy_unauthorized_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/botunknown_token/setProxy",
            json={"proxy": "socks5://127.0.0.1:1080"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["error_code"] == 401


@pytest.mark.asyncio
async def test_rotate_token_and_unlink():
    from app.database import db

    # Seed mock session
    test_token = "usr_test_rotate_123"
    db.save_session(
        token=test_token,
        session_name="test_session_mock",
        session_type="string",
        api_id=12345,
        api_hash="hash123",
        session_string="mock_str",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Rotate token
        resp = await client.post(
            f"/bot{test_token}/rotateToken",
            json={"new_token": "usr_test_rotated_new"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["result"]["new_token"] == "usr_test_rotated_new"

        # Verify old token no longer exists and new token does
        assert db.get_session(test_token) is None
        assert db.get_session("usr_test_rotated_new") is not None

        # Unlink session
        unlink_resp = await client.post("/botusr_test_rotated_new/unlink")
        assert unlink_resp.status_code == 200
        assert unlink_resp.json()["ok"] is True

        # Verify removed from database
        assert db.get_session("usr_test_rotated_new") is None


@pytest.mark.asyncio
async def test_bot_relay_registration_and_proxy():
    bot_token = "987654321:AAF_TEST_BOT_TOKEN_12345"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register bot token
        reg_resp = await client.post(
            "/auth/register_bot",
            json={
                "bot_token": bot_token,
                "proxy": "socks5://127.0.0.1:1080",
            },
        )
        assert reg_resp.status_code == 200
        data = reg_resp.json()
        assert data["ok"] is True
        assert data["result"]["type"] == "bot_relay"

        # Get proxy
        p_resp = await client.get(f"/bot{bot_token}/getProxy")
        assert p_resp.status_code == 200
        p_data = p_resp.json()
        assert p_data["ok"] is True
        assert p_data["result"]["proxy"]["type"] == "socks5"
        assert p_data["result"]["proxy"]["port"] == 1080

        # Delete proxy
        del_resp = await client.post(f"/bot{bot_token}/deleteProxy")
        assert del_resp.status_code == 200
        assert del_resp.json()["ok"] is True

        # Unlink bot
        unlink_resp = await client.post(f"/bot{bot_token}/unlink")
        assert unlink_resp.status_code == 200
        assert unlink_resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_admin_stats_and_quota():
    from app.config import settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Without admin token -> 401
        unauth_resp = await client.get("/admin/stats")
        assert unauth_resp.status_code == 401

        # With correct admin token
        headers = {"X-Admin-Token": settings.ADMIN_TOKEN}
        resp = await client.get("/admin/stats", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "total_active_sessions" in data["result"]
        assert "default_user_quota_mb" in data["result"]

        # List admin sessions
        sessions_resp = await client.get("/admin/sessions", headers=headers)
        assert sessions_resp.status_code == 200
        assert sessions_resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_public_proxy_test_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Missing proxy
        resp1 = await client.post("/proxy/test", json={})
        assert resp1.status_code == 200
        assert resp1.json()["ok"] is False

        # Invalid scheme
        resp2 = await client.post("/proxy/test", json={"proxy": "invalid://127.0.0.1"})
        assert resp2.status_code == 200
        assert resp2.json()["ok"] is False
        assert "error" in resp2.json()["result"]


@pytest.mark.asyncio
async def test_session_export():
    from app.database import db

    test_token = "usr_export_test_token_123"
    db.save_session(
        token=test_token,
        session_name="export_test_name",
        session_type="string",
        api_id=12345,
        api_hash="hash",
        session_string="1BJWap_mock_export",
        username="export_user",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Export metadata
        resp = await client.get(f"/session/export?token={test_token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["result"]["username"] == "export_user"
        assert data["result"]["session_string"] == "1BJWap_mock_export"
        assert "file_download_url" in data["result"]

        # Clean up
        db.hard_delete_session(test_token)


