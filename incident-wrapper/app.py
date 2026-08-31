#!/usr/bin/env python3
"""
GraphHopper incident & custom-model wrapper (Python sidecar).

A small service that sits in front of a running GraphHopper server. It provides:

  * /incidents  -- CRUD for road incidents / closures (SQLite-backed)
  * /route      -- routing proxy that accepts a `custom_model` parameter
                   (which the fork's plain GET /route lacks) and injects every
                   active incident as a blocked polygon area.

Configuration (environment variables):
  GRAPHOPPER_URL   upstream GraphHopper base URL (default http://localhost:8989)
  INCIDENTS_DB     SQLite file for incidents (default ./incidents.db next to this file)
  PORT             listen port (default 8000)
  ADMIN_USERNAME   login username (default 'admin')
  ADMIN_PASSWORD   login password (default 'admin' — change it!)
  TOKEN_TTL_HOURS  login session lifetime in hours (default 24)

Run:
  ./run.sh            # bootstraps a venv, installs deps, starts uvicorn on :8000
  # then open http://localhost:8000/docs
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit

import requests
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

GRAPHOPPER_URL = os.environ.get("GRAPHOPPER_URL", "http://localhost:8989").rstrip("/")
BAATO_KEY = os.environ.get("BAATO_KEY", "")
DB_PATH = os.environ.get("INCIDENTS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "incidents.db"))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Authentication — only authenticated users may add/edit/delete incidents.
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_HOURS", "24")) * 3600

_LOGGER = logging.getLogger("incident-wrapper")
if ADMIN_PASSWORD == "admin":
    _LOGGER.warning("ADMIN_PASSWORD is still the default 'admin' — set it via the environment")

app = FastAPI(title="GraphHopper incident & custom-model wrapper", version="1.0.0")

_db_lock = threading.Lock()


@contextmanager
def db():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id          TEXT PRIMARY KEY,
                type        TEXT NOT NULL DEFAULT 'ROAD_CLOSURE',
                description TEXT NOT NULL DEFAULT '',
                active      INTEGER NOT NULL DEFAULT 1,
                coordinates TEXT NOT NULL,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            )
            """
        )


_init_db()


# ---------------------------------------------------------------------------
# authentication — HMAC-signed bearer tokens (stdlib only, no new deps)
# ---------------------------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _signing_key() -> bytes:
    """A stable key derived from the admin password — rotating the password
    invalidates every token already issued."""
    return hashlib.sha256(("incident-wrapper:" + ADMIN_PASSWORD).encode()).digest()


def _sign_token(username: str) -> str:
    payload = {"sub": username, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest())
    return body + "." + sig


def _verify_token(token: str) -> str:
    """Return the token's subject, or raise 401."""
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
    expected = hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest()
    try:
        provided = _b64d(sig)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        payload = json.loads(_b64d(body))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="Token expired")
    return payload.get("sub", "")


def require_auth(authorization: Optional[str] = Header(None)) -> str:
    """FastAPI dependency: reject requests without a valid bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    return _verify_token(authorization[len("Bearer "):].strip())


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/login")
def login(body: LoginIn):
    if not (hmac.compare_digest(body.username, ADMIN_USERNAME)
            and hmac.compare_digest(body.password, ADMIN_PASSWORD)):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": _sign_token(body.username), "username": body.username,
            "expires_in": TOKEN_TTL_SECONDS}


@app.get("/auth/status")
def auth_status(authorization: Optional[str] = Header(None)):
    """Tell the dashboard whether a stored token is still valid (never 401s)."""
    if not authorization or not authorization.startswith("Bearer "):
        return {"authenticated": False, "username": None}
    try:
        user = _verify_token(authorization[len("Bearer "):].strip())
        return {"authenticated": True, "username": user}
    except HTTPException:
        return {"authenticated": False, "username": None}


# ---------------------------------------------------------------------------
# models & helpers
# ---------------------------------------------------------------------------
class IncidentIn(BaseModel):
    type: str = "ROAD_CLOSURE"
    description: str = ""
    active: bool = True
    coordinates: List[List[float]]  # GeoJSON polygon ring, [lon, lat]


class IncidentPatch(BaseModel):
    type: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    coordinates: Optional[List[List[float]]] = None


def _row_to_incident(row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "description": row["description"],
        "active": bool(row["active"]),
        "coordinates": json.loads(row["coordinates"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _get_row(incident_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
    return row


def sanitize_id(s: str) -> str:
    """Reduce a string to a valid custom-model area id ([a-zA-Z0-9_], no '__')."""
    s = re.sub(r"[^a-zA-Z0-9_]", "_", s or "")
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unknown"


def close_ring(coords: List[List[float]]) -> List[List[float]]:
    if not coords:
        raise HTTPException(status_code=400, detail="coordinates must be a non-empty polygon ring")
    if len(coords) < 3:
        raise HTTPException(status_code=400, detail="coordinates must contain at least 3 [lon, lat] points")
    ring = [list(c) for c in coords]
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


def active_incidents() -> List[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM incidents WHERE active = 1 ORDER BY created_at").fetchall()
    return [_row_to_incident(r) for r in rows]


def merge_custom_model(user_model, apply_incidents: bool) -> Optional[dict]:
    """Return the custom model to send upstream: the caller's model plus (optionally)
    one blocked polygon area per active incident."""
    cm = dict(user_model or {})
    if apply_incidents:
        areas = {}
        priority = []
        for inc in active_incidents():
            area_id = sanitize_id(inc["id"])
            areas[area_id] = {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [inc["coordinates"]]},
                "properties": {"type": inc["type"], "description": inc["description"]},
            }
            priority.append({"if": "in_" + area_id, "multiply_by": "0"})
        if areas:
            cm.setdefault("areas", {}).update(areas)
            cm.setdefault("priority", []).extend(priority)
    return cm or None


def _parse_user_model(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid custom_model JSON: {e}")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="custom_model must be a JSON object")
    return parsed


def _forward(resp: requests.Response) -> Response:
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


# ---------------------------------------------------------------------------
# incident CRUD
# ---------------------------------------------------------------------------
@app.get("/incidents")
def list_incidents():
    with db() as conn:
        rows = conn.execute("SELECT * FROM incidents ORDER BY created_at").fetchall()
    return [_row_to_incident(r) for r in rows]


@app.post("/incidents", status_code=201)
def create_incident(body: IncidentIn, auth_user: str = Depends(require_auth)):
    coords = close_ring(body.coordinates)
    incident_id = "inc_" + uuid.uuid4().hex[:12]
    now = int(time.time() * 1000)
    with db() as conn:
        conn.execute(
            "INSERT INTO incidents (id, type, description, active, coordinates, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (incident_id, body.type, body.description, int(body.active), json.dumps(coords), now, now),
        )
    return _row_to_incident(_get_row(incident_id))


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    return _row_to_incident(_get_row(incident_id))


@app.put("/incidents/{incident_id}")
def update_incident(incident_id: str, patch: IncidentPatch, auth_user: str = Depends(require_auth)):
    _get_row(incident_id)  # 404 if missing
    fields, values = [], []
    if patch.type is not None:
        fields.append("type = ?")
        values.append(patch.type)
    if patch.description is not None:
        fields.append("description = ?")
        values.append(patch.description)
    if patch.active is not None:
        fields.append("active = ?")
        values.append(int(patch.active))
    if patch.coordinates is not None:
        fields.append("coordinates = ?")
        values.append(json.dumps(close_ring(patch.coordinates)))
    fields.append("updated_at = ?")
    values.append(int(time.time() * 1000))
    values.append(incident_id)
    with db() as conn:
        conn.execute(f"UPDATE incidents SET {', '.join(fields)} WHERE id = ?", values)
    return _row_to_incident(_get_row(incident_id))


@app.delete("/incidents/{incident_id}", status_code=204)
def delete_incident(incident_id: str, auth_user: str = Depends(require_auth)):
    _get_row(incident_id)  # 404 if missing
    with db() as conn:
        conn.execute("DELETE FROM incidents WHERE id = ?", (incident_id,))
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# routing wrapper
# ---------------------------------------------------------------------------
@app.get("/route")
def route_get(
    point: List[str] = Query(..., description="lat,lon (repeatable), e.g. ?point=27.71,85.32&point=28.21,83.99"),
    profile: str = Query("car"),
    custom_model: Optional[str] = Query(None, description="URL-encoded custom_model JSON"),
    apply_incidents: bool = Query(True),
    details: Optional[List[str]] = Query(None),
    instructions: bool = Query(True),
    calc_points: bool = Query(True),
    elevation: bool = Query(False),
    points_encoded: bool = Query(True),
    points_encoded_multiplier: float = Query(1e5),
    algorithm: Optional[str] = Query(None),
    locale: str = Query("en"),
    heading: Optional[List[float]] = Query(None),
    snap_prevention: Optional[List[str]] = Query(None),
):
    points = []
    for p in point:
        try:
            lat, lon = (float(x) for x in p.split(","))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid point '{p}', expected 'lat,lon'")
        points.append([lon, lat])  # upstream POST body uses [lon, lat]

    body = {
        "points": points,
        "profile": profile,
        "instructions": instructions,
        "calc_points": calc_points,
        "elevation": elevation,
        "points_encoded": points_encoded,
        "points_encoded_multiplier": points_encoded_multiplier,
        "locale": locale,
    }
    if details:
        body["details"] = details
    if algorithm:
        body["algorithm"] = algorithm
    if heading:
        body["headings"] = heading
    if snap_prevention:
        body["snap_preventions"] = snap_prevention

    cm = merge_custom_model(_parse_user_model(custom_model), apply_incidents)
    if cm:
        body["custom_model"] = cm

    resp = requests.post(f"{GRAPHOPPER_URL}/route", json=body, timeout=300)
    return _forward(resp)


@app.post("/route")
def route_post(payload: dict = Body(...), apply_incidents: bool = Query(True)):
    cm = merge_custom_model(payload.get("custom_model"), apply_incidents)
    if cm:
        payload["custom_model"] = cm
    resp = requests.post(f"{GRAPHOPPER_URL}/route", json=payload, timeout=300)
    return _forward(resp)


@app.get("/health")
def health():
    return {"status": "ok", "upstream": GRAPHOPPER_URL}


@app.get("/config")
def config():
    """Front-end config. The Baato key is deliberately NOT sent to the browser —
    only whether the server has one. Baato styles/tiles are proxied instead."""
    return {"baato_configured": bool(BAATO_KEY)}


# ---------------------------------------------------------------------------
# Baato proxy — keeps BAATO_KEY server-side
# ---------------------------------------------------------------------------
BAATO_API = "https://api.baato.io/api/v1"
BAATO_STYLES = {"breeze", "monochrome", "retro", "dark"}


def _scrub_baato_url(url: str, base: str) -> str:
    """Re-point any Baato URL that carries the key at our own proxy."""
    if not isinstance(url, str) or not BAATO_KEY or BAATO_KEY not in url:
        return url
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "key"]
    path = parts.path
    if path.startswith("/api/v1/"):
        path = path[len("/api/v1/"):]
    out = f"{base}/baato/api/{path.lstrip('/')}"
    if query:
        out += "?" + urlencode(query)
    return out


@app.get("/baato/style/{style}")
def baato_style(style: str, request: Request):
    """Fetch a Baato style server-side and strip the key out of it."""
    if not BAATO_KEY:
        raise HTTPException(status_code=503, detail="BAATO_KEY is not configured on the server")
    if style not in BAATO_STYLES:
        raise HTTPException(status_code=404, detail=f"Unknown Baato style '{style}'")
    try:
        r = requests.get(f"{BAATO_API}/styles/{style}", params={"key": BAATO_KEY}, timeout=30)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Baato unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail="Baato rejected the style request")

    style_json = r.json()
    base = str(request.base_url).rstrip("/")
    for src in (style_json.get("sources") or {}).values():
        if isinstance(src.get("tiles"), list):
            src["tiles"] = [_scrub_baato_url(u, base) for u in src["tiles"]]
        src["url"] = _scrub_baato_url(src["url"], base) if isinstance(src.get("url"), str) else src.get("url")
        if src.get("url") is None:
            src.pop("url", None)
    return style_json


@app.get("/baato/api/{path:path}")
def baato_proxy(path: str, request: Request):
    """Transparent GET proxy that appends the key (tiles, sprites, anything)."""
    if not BAATO_KEY:
        raise HTTPException(status_code=503, detail="BAATO_KEY is not configured on the server")
    params = dict(request.query_params)
    params["key"] = BAATO_KEY
    try:
        r = requests.get(f"{BAATO_API}/{path}", params=params, timeout=30)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Baato unreachable: {exc}") from exc
    # requests already decompressed the body, so Content-Encoding must NOT be echoed
    headers = {}
    if "content-type" in r.headers:
        headers["Content-Type"] = r.headers["content-type"]
    headers["Cache-Control"] = r.headers.get("cache-control", "public, max-age=86400")
    return Response(content=r.content, status_code=r.status_code, headers=headers)


# ---------------------------------------------------------------------------
# map UI (record incidents as polygons)
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
@app.get("/map", include_in_schema=False)
@app.get("/route-ui", include_in_schema=False)
def map_ui():
    return FileResponse(os.path.join(STATIC_DIR, "map.html"))


# Serves dashboard.js (and any future assets) next to map.html.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
