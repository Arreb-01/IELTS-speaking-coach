"""认证流程测试。"""

from sqlalchemy import select

from app.core.security import verify_password
from app.db.models import User


async def test_register_success(client, db_session):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "newbie@example.com", "password": "pass1234"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["access_token"] and data["refresh_token"]
    assert data["user"]["email"] == "newbie@example.com"
    # 未提供昵称时取邮箱前缀
    assert data["user"]["nickname"] == "newbie"

    user = await db_session.scalar(select(User).where(User.email == "newbie@example.com"))
    assert user is not None
    # 数据库中不存明文密码
    assert user.hashed_password != "pass1234"
    assert verify_password("pass1234", user.hashed_password)


async def test_register_duplicate_email(client):
    body = {"email": "dup@example.com", "password": "pass1234"}
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 201
    resp = await client.post("/api/v1/auth/register", json=body)
    assert resp.status_code == 409


async def test_register_invalid_payload(client):
    # 非法邮箱
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": "pass1234"}
    )
    assert resp.status_code == 422
    # 密码过短
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "a@example.com", "password": "p1"}
    )
    assert resp.status_code == 422
    # 密码缺少数字
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "a@example.com", "password": "passwordonly"}
    )
    assert resp.status_code == 422


async def test_login_success(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "login@example.com", "password": "pass1234"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "LOGIN@example.com", "password": "pass1234"},  # 邮箱大小写不敏感
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_login_wrong_password(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "wrongpw@example.com", "password": "pass1234"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "wrongpw@example.com", "password": "badpass1"},
    )
    assert resp.status_code == 401


async def test_login_rate_limited(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "limit@example.com", "password": "pass1234"},
    )
    body = {"email": "limit@example.com", "password": "badpass1"}
    for _ in range(5):
        resp = await client.post("/api/v1/auth/login", json=body)
        assert resp.status_code == 401
    # 第 6 次即使密码正确也被限流
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "limit@example.com", "password": "pass1234"},
    )
    assert resp.status_code == 429


async def test_refresh_rotation(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "refresh@example.com", "password": "pass1234"},
    )
    old_refresh = resp.json()["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert new_tokens["refresh_token"] != old_refresh

    # 旧 refresh token 轮换后立即失效
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 401
    # 新 refresh token 可继续使用
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert resp.status_code == 200


async def test_logout_invalidates_refresh(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "logout@example.com", "password": "pass1234"},
    )
    refresh = resp.json()["refresh_token"]

    assert (await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})).status_code == 200
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401


async def test_me(client, auth_headers):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "tester@example.com"


async def test_me_requires_token(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_me_rejects_refresh_token_as_access(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "tokenmix@example.com", "password": "pass1234"},
    )
    refresh = resp.json()["refresh_token"]
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"}
    )
    assert resp.status_code == 401


async def test_update_user_profile(client, auth_headers):
    resp = await client.put(
        "/api/v1/users/me",
        headers=auth_headers,
        json={"nickname": "冲刺7分", "target_band": 7.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["nickname"] == "冲刺7分"
    assert float(data["target_band"]) == 7.0

    # target_band 超出雅思分数范围
    resp = await client.put(
        "/api/v1/users/me", headers=auth_headers, json={"target_band": 12.0}
    )
    assert resp.status_code == 422
