"""API Key（BYOK）管理测试。"""

from sqlalchemy import select

from app.core.crypto import decrypt_secret
from app.db.models import UserApiKey


async def _get_row(db_session, email="tester@example.com"):
    from app.db.models import User

    user = await db_session.scalar(select(User).where(User.email == email))
    return await db_session.scalar(
        select(UserApiKey).where(UserApiKey.user_id == user.id)
    )


async def test_requires_auth(client):
    assert (await client.get("/api/v1/api-keys")).status_code == 401


async def test_save_and_list(client, auth_headers, db_session):
    resp = await client.put(
        "/api/v1/api-keys/llm",
        headers=auth_headers,
        json={"key": "sk-test-1234-abcd-wxyz", "config": {"model": "doubao-1.5-pro-32k-250115"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["status"] == "unverified"
    assert data["key_last4"] == "wxyz"
    # 响应中不能出现完整 Key
    assert "sk-test-1234-abcd" not in resp.text

    # 落库的是密文，且可解密还原
    row = await _get_row(db_session)
    assert row.key_encrypted != "sk-test-1234-abcd-wxyz"
    assert decrypt_secret(row.key_encrypted) == "sk-test-1234-abcd-wxyz"

    # 列表返回全部四类服务，未配置的为 not_configured
    resp = await client.get("/api/v1/api-keys", headers=auth_headers)
    assert resp.status_code == 200
    services = {item["service_type"]: item for item in resp.json()}
    assert set(services) == {"llm", "asr", "tts", "evaluation"}
    assert services["llm"]["configured"] is True
    assert services["tts"]["configured"] is False
    assert services["tts"]["status"] == "not_configured"


async def test_save_overwrite(client, auth_headers):
    first = await client.put(
        "/api/v1/api-keys/tts", headers=auth_headers, json={"key": "aaaaaaaa1111"}
    )
    assert first.json()["key_last4"] == "1111"
    second = await client.put(
        "/api/v1/api-keys/tts",
        headers=auth_headers,
        json={"key": "bbbbbbbb2222", "config": {"voice": "anna"}},
    )
    assert second.json()["key_last4"] == "2222"
    assert second.json()["config"] == {"voice": "anna"}


async def test_config_only_update(client, auth_headers, db_session):
    await client.put(
        "/api/v1/api-keys/tts", headers=auth_headers, json={"key": "aaaaaaaa1111"}
    )
    # 不带 key 仅更新 config：Key 保持不变，last4 不变
    resp = await client.put(
        "/api/v1/api-keys/tts", headers=auth_headers, json={"config": {"voice": "jackson"}}
    )
    assert resp.status_code == 200
    assert resp.json()["key_last4"] == "1111"
    assert resp.json()["config"] == {"voice": "jackson"}

    # 未保存过 Key 的服务不能仅更新 config
    resp = await client.put(
        "/api/v1/api-keys/asr", headers=auth_headers, json={"config": {"version": "2.0"}}
    )
    assert resp.status_code == 400


async def test_save_invalid_service_type(client, auth_headers):
    resp = await client.put(
        "/api/v1/api-keys/translate", headers=auth_headers, json={"key": "x" * 12}
    )
    assert resp.status_code == 422


async def test_delete(client, auth_headers):
    await client.put(
        "/api/v1/api-keys/asr", headers=auth_headers, json={"key": "cccccccc3333"}
    )
    resp = await client.delete("/api/v1/api-keys/asr", headers=auth_headers)
    assert resp.status_code == 204

    resp = await client.get("/api/v1/api-keys", headers=auth_headers)
    services = {item["service_type"]: item for item in resp.json()}
    assert services["asr"]["configured"] is False


async def test_llm_connection_success(client, auth_headers, db_session, monkeypatch):
    async def fake_test(api_key, model=None):
        assert api_key == "sk-live-9999-good"
        return True, "连接成功", 88

    monkeypatch.setattr("app.api.v1.api_keys.ark.test_connection", fake_test)

    await client.put(
        "/api/v1/api-keys/llm", headers=auth_headers, json={"key": "sk-live-9999-good"}
    )
    resp = await client.post("/api/v1/api-keys/llm/test", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["key_source"] == "user"
    assert data["latency_ms"] == 88

    row = await _get_row(db_session)
    assert row.status == "valid"
    assert row.last_verified_at is not None


async def test_llm_connection_invalid_key(client, auth_headers, db_session, monkeypatch):
    async def fake_test(api_key, model=None):
        return False, "API Key 无效或无访问权限", 40

    monkeypatch.setattr("app.api.v1.api_keys.ark.test_connection", fake_test)

    await client.put(
        "/api/v1/api-keys/llm", headers=auth_headers, json={"key": "sk-live-9999-bad0"}
    )
    resp = await client.post("/api/v1/api-keys/llm/test", headers=auth_headers)
    data = resp.json()
    assert data["success"] is False
    assert data["key_source"] == "user"

    row = await _get_row(db_session)
    assert row.status == "invalid"


async def test_llm_test_without_any_key(client, auth_headers):
    # 未配置用户 Key 且平台默认 Key 为空（conftest 已隔离）
    resp = await client.post("/api/v1/api-keys/llm/test", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["key_source"] == "none"


async def test_llm_test_fallback_to_platform_key(client, auth_headers, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "volc_ark_default_api_key", "sk-platform-key")

    async def fake_test(api_key, model=None):
        assert api_key == "sk-platform-key"
        return True, "连接成功", 10

    monkeypatch.setattr("app.api.v1.api_keys.ark.test_connection", fake_test)

    resp = await client.post("/api/v1/api-keys/llm/test", headers=auth_headers)
    data = resp.json()
    assert data["key_source"] == "platform"
    assert data["success"] is True


async def test_voice_services_pending(client, auth_headers):
    for service in ("asr", "tts", "evaluation"):
        resp = await client.post(f"/api/v1/api-keys/{service}/test", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["testable"] is False
