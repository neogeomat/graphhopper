"""Authentication: login, token validation and protecting incident mutations."""
import app as app_module

ADMIN_USERNAME = app_module.ADMIN_USERNAME
ADMIN_PASSWORD = app_module.ADMIN_PASSWORD


def _login(client):
    r = client.post("/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# --- login ---------------------------------------------------------------
def test_login_success_returns_token(anon_client):
    r = anon_client.post("/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["username"] == ADMIN_USERNAME
    assert body["expires_in"] == app_module.TOKEN_TTL_SECONDS


def test_login_wrong_password_is_401(anon_client):
    r = anon_client.post("/login", json={"username": ADMIN_USERNAME, "password": "wrong"})
    assert r.status_code == 401


def test_login_wrong_username_is_401(anon_client):
    r = anon_client.post("/login", json={"username": "nobody", "password": ADMIN_PASSWORD})
    assert r.status_code == 401


# --- protection ----------------------------------------------------------
def test_create_requires_auth(anon_client, box):
    assert anon_client.post("/incidents", json={"coordinates": box()}).status_code == 401


def test_update_requires_auth(anon_client, make_incident):
    inc = make_incident()
    r = anon_client.put(f"/incidents/{inc['id']}", json={"active": False})
    assert r.status_code == 401


def test_delete_requires_auth(anon_client, make_incident):
    inc = make_incident()
    assert anon_client.delete(f"/incidents/{inc['id']}").status_code == 401


def test_garbage_token_is_401(anon_client, box):
    r = anon_client.post("/incidents", json={"coordinates": box()},
                         headers={"Authorization": "Bearer not.a.real.token"})
    assert r.status_code == 401


def test_missing_bearer_prefix_is_401(anon_client, box):
    r = anon_client.post("/incidents", json={"coordinates": box()},
                         headers={"Authorization": "some-token"})
    assert r.status_code == 401


def test_valid_token_allows_create(anon_client, box):
    token = _login(anon_client)
    r = anon_client.post("/incidents", json={"coordinates": box()},
                         headers={"Authorization": "Bearer " + token})
    assert r.status_code == 201


def test_valid_token_allows_delete(anon_client, make_incident):
    inc = make_incident()
    token = _login(anon_client)
    r = anon_client.delete(f"/incidents/{inc['id']}",
                           headers={"Authorization": "Bearer " + token})
    assert r.status_code == 204


# --- expiry --------------------------------------------------------------
def test_expired_token_is_rejected(anon_client, box, monkeypatch):
    real_time = app_module.time.time
    t0 = 1_000_000
    monkeypatch.setattr(app_module.time, "time", lambda: t0)
    token = app_module._sign_token(ADMIN_USERNAME)
    # clock moves past the token's lifetime
    monkeypatch.setattr(app_module.time, "time", lambda: t0 + app_module.TOKEN_TTL_SECONDS + 1)
    r = anon_client.post("/incidents", json={"coordinates": box()},
                         headers={"Authorization": "Bearer " + token})
    assert r.status_code == 401


# --- status --------------------------------------------------------------
def test_auth_status_reports_whether_a_token_is_valid(anon_client):
    assert anon_client.get("/auth/status").json() == {"authenticated": False, "username": None}
    token = _login(anon_client)
    body = anon_client.get("/auth/status",
                           headers={"Authorization": "Bearer " + token}).json()
    assert body == {"authenticated": True, "username": ADMIN_USERNAME}


# --- public endpoints stay open ------------------------------------------
def test_read_and_public_endpoints_do_not_require_auth(anon_client):
    assert anon_client.get("/incidents").status_code == 200
    assert anon_client.get("/health").status_code == 200
    assert anon_client.get("/config").status_code == 200
    assert anon_client.get("/auth/status").status_code == 200
    # a public read of a specific incident is also open
    assert anon_client.get("/incidents/inc_doesnotexist").status_code == 404
