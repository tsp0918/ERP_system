"""Tests for authentication."""
def test_login_success(client, admin_user):
    r = client.post("/auth/token", data={
        "username": admin_user.email,
        "password": "test-password",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["email"] == admin_user.email
    assert len(body["access_token"]) > 50


def test_login_wrong_password(client, admin_user):
    r = client.post("/auth/token", data={
        "username": admin_user.email,
        "password": "wrong",
    })
    assert r.status_code == 401


def test_login_unknown_user(client):
    r = client.post("/auth/token", data={
        "username": "nobody@example.com",
        "password": "x",
    })
    assert r.status_code == 401


def test_me_requires_auth(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_returns_user(client, auth_headers, admin_user):
    r = client.get("/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == admin_user.email
