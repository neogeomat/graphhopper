"""Shared fixtures.

IMPORTANT: app.py reads INCIDENTS_DB, BAATO_KEY, ADMIN_USERNAME and
ADMIN_PASSWORD at *import* time and calls _init_db() at module level, so all of
them must be set before `import app`.
"""
import os
import pathlib
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

WRAPPER_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WRAPPER_DIR))

# point the app at a throwaway DB, give it a known key, and enable auth with
# fixed credentials *before* importing it
_TMP_DB = pathlib.Path(tempfile.mkdtemp(prefix="incident-tests-")) / "test_incidents.db"
os.environ["INCIDENTS_DB"] = str(_TMP_DB)
os.environ["BAATO_KEY"] = "bpk.TEST_KEY_NOT_REAL"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-password"

import app as app_module  # noqa: E402

TEST_KEY = app_module.BAATO_KEY
ADMIN_USERNAME = app_module.ADMIN_USERNAME
ADMIN_PASSWORD = app_module.ADMIN_PASSWORD


class AuthedTestClient(TestClient):
    """A TestClient that attaches the bearer token to every request, so the
    pre-existing CRUD tests don't each need to pass auth headers."""

    def __init__(self, app, token, **kwargs):
        super().__init__(app, **kwargs)
        self._auth_token = token

    def request(self, method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        if not any(k.lower() == "authorization" for k in headers):
            headers["Authorization"] = "Bearer " + self._auth_token
        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


@pytest.fixture(scope="session")
def auth_token():
    """Log in once and return a bearer token."""
    with TestClient(app_module.app) as raw:
        r = raw.post("/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        return r.json()["token"]


@pytest.fixture(scope="session")
def client(auth_token):
    """A client that is already authenticated — most tests exercise CRUD."""
    with AuthedTestClient(app_module.app, auth_token) as c:
        yield c


@pytest.fixture(scope="session")
def anon_client():
    """A client with no auth headers, for testing the 401 paths."""
    with TestClient(app_module.app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db():
    """Every test starts with an empty incidents table."""
    with app_module.db() as conn:
        conn.execute("DELETE FROM incidents")
    yield
    with app_module.db() as conn:
        conn.execute("DELETE FROM incidents")


@pytest.fixture
def box():
    """A closed-ish square ring as [lon, lat] pairs (open on purpose)."""
    def _box(lon=85.3240, lat=27.7172, d=0.004):
        return [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d]]
    return _box


@pytest.fixture
def make_incident(client, box):
    def _make(**kw):
        payload = {"type": "ROAD_CLOSURE", "description": "", "active": True,
                   "coordinates": box()}
        payload.update(kw)
        r = client.post("/incidents", json=payload)
        assert r.status_code == 201, r.text
        return r.json()
    return _make
