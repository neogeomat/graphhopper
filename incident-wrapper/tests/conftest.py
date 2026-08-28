"""Shared fixtures.

IMPORTANT: app.py reads INCIDENTS_DB and BAATO_KEY at *import* time and calls
_init_db() at module level, so both must be set before `import app`.
"""
import os
import pathlib
import sys
import tempfile

import pytest

WRAPPER_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WRAPPER_DIR))

# point the app at a throwaway DB and give it a known key *before* importing it
_TMP_DB = pathlib.Path(tempfile.mkdtemp(prefix="incident-tests-")) / "test_incidents.db"
os.environ["INCIDENTS_DB"] = str(_TMP_DB)
os.environ["BAATO_KEY"] = "bpk.TEST_KEY_NOT_REAL"

import app as app_module  # noqa: E402

TEST_KEY = app_module.BAATO_KEY


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
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
