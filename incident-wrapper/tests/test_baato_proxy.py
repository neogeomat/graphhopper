"""The Baato key must never reach the browser.

These are the regression tests for the proxy: /config exposes only a boolean,
the style endpoint strips the key out of the style JSON, and the tile proxy
re-appends it server-side.
"""
import json

import pytest
import requests

import app as app_module
from conftest import TEST_KEY


# --- a minimal stand-in for Baato's real style response --------------------
def fake_style(key):
    return {
        "version": 8,
        "glyphs": "https://baatocdn.example/fonts/{fontstack}/{range}.pbf.gz",
        "sprite": "https://baatocdn.example/icons/breeze/icons",
        "sources": {
            # the only source that carries the key, as in the real style
            "qvez6ula1": {"type": "vector",
                          "tiles": [f"https://api.baato.io/api/v1/maps/{{z}}/{{x}}/{{y}}.pbf?key={key}"]},
            # keyless CDN sources must be left alone
            "buildings": {"type": "vector",
                          "tiles": ["https://baatooffline.example/buildings/{z}/{x}/{y}.pbf"]},
            "Boundary-Country": {"type": "geojson",
                                 "data": "https://baatocdn.example/boundaries/country.json"},
            "with_url": {"type": "vector",
                         "url": f"https://api.baato.io/api/v1/tilejson.json?key={key}"},
        },
        "layers": [{"id": "bg", "type": "background"}],
    }


class FakeResponse:
    def __init__(self, payload, status=200, headers=None, content=None):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {"content-type": "application/json"}
        self.content = content if content is not None else json.dumps(payload).encode()

    def json(self):
        return self._payload


# --- /config ---------------------------------------------------------------
def test_config_never_returns_the_key(client):
    r = client.get("/config")
    assert r.status_code == 200
    body = r.json()
    assert body == {"baato_configured": True}
    assert TEST_KEY not in r.text


def test_config_reports_false_when_unset(client, monkeypatch):
    monkeypatch.setattr(app_module, "BAATO_KEY", "")
    assert client.get("/config").json() == {"baato_configured": False}


# --- URL scrubbing (unit) -------------------------------------------------
def test_scrub_rewrites_key_bearing_url():
    url = f"https://api.baato.io/api/v1/maps/{{z}}/{{x}}/{{y}}.pbf?key={TEST_KEY}"
    out = app_module._scrub_baato_url(url, "http://testserver")
    assert TEST_KEY not in out
    assert out == "http://testserver/baato/api/maps/{z}/{x}/{y}.pbf"
    assert "{z}/{x}/{y}" in out          # placeholders must survive


def test_scrub_preserves_other_query_params():
    url = f"https://api.baato.io/api/v1/maps/1/2/3.pbf?key={TEST_KEY}&foo=bar"
    out = app_module._scrub_baato_url(url, "http://testserver")
    assert "foo=bar" in out and TEST_KEY not in out


def test_scrub_leaves_keyless_urls_untouched():
    url = "https://baatocdn.example/boundaries/country.json"
    assert app_module._scrub_baato_url(url, "http://testserver") == url


def test_scrub_ignores_non_strings():
    assert app_module._scrub_baato_url(None, "http://testserver") is None  # type: ignore[arg-type]


# --- /baato/style ---------------------------------------------------------
def test_style_is_scrubbed_end_to_end(client, monkeypatch):
    monkeypatch.setattr(requests, "get",
                        lambda url, **kw: FakeResponse(fake_style(TEST_KEY)))
    r = client.get("/baato/style/breeze")
    assert r.status_code == 200
    # the single most important assertion in this file
    assert TEST_KEY not in r.text

    style = r.json()
    assert style["sources"]["qvez6ula1"]["tiles"][0].endswith("/baato/api/maps/{z}/{x}/{y}.pbf")
    assert style["sources"]["with_url"]["url"].startswith("http://testserver/baato/api/")
    # keyless sources unchanged
    assert style["sources"]["buildings"]["tiles"] == ["https://baatooffline.example/buildings/{z}/{x}/{y}.pbf"]
    assert style["sources"]["Boundary-Country"]["data"] == "https://baatocdn.example/boundaries/country.json"
    # glyphs/sprite are required for labels and icons to render
    assert style["glyphs"] and style["sprite"]
    assert style["layers"]


def test_style_sends_the_key_upstream(client, monkeypatch):
    seen = {}

    def spy(url, **kw):
        seen["url"] = url
        seen["params"] = kw.get("params")
        return FakeResponse(fake_style(TEST_KEY))

    monkeypatch.setattr(requests, "get", spy)
    client.get("/baato/style/breeze")
    assert seen["url"] == "https://api.baato.io/api/v1/styles/breeze"
    assert seen["params"]["key"] == TEST_KEY


def test_style_defaults_keyed_tiles_to_https_behind_tls(client, monkeypatch):
    # On a TLS-terminated deployment the wrapper only ever sees http:// inbound,
    # so it must NOT let that leak into the proxied tile URL (mixed content would
    # silently kill the vector/road layers). A non-localhost host => https.
    monkeypatch.setattr(requests, "get",
                        lambda url, **kw: FakeResponse(fake_style(TEST_KEY)))
    r = client.get("/baato/style/breeze", headers={"Host": "rasuwaflood.baato.io"})
    style = r.json()
    tile = style["sources"]["qvez6ula1"]["tiles"][0]
    assert tile.startswith("https://rasuwaflood.baato.io/baato/api/maps/")
    url = style["sources"]["with_url"]["url"]
    assert url.startswith("https://rasuwaflood.baato.io/baato/api/")


def test_style_honors_forwarded_proto(client, monkeypatch):
    monkeypatch.setattr(requests, "get",
                        lambda url, **kw: FakeResponse(fake_style(TEST_KEY)))
    r = client.get(
        "/baato/style/breeze",
        headers={"Host": "rasuwaflood.baato.io", "X-Forwarded-Proto": "http"},
    )
    style = r.json()
    assert style["sources"]["qvez6ula1"]["tiles"][0].startswith(
        "http://rasuwaflood.baato.io/baato/api/")
    # forwarded host wins for the base
    r2 = client.get(
        "/baato/style/breeze",
        headers={"Host": "internal:8000", "X-Forwarded-Host": "rasuwaflood.baato.io",
                 "X-Forwarded-Proto": "https"},
    )
    assert r2.json()["sources"]["qvez6ula1"]["tiles"][0].startswith(
        "https://rasuwaflood.baato.io/baato/api/")


def test_style_keeps_localhost_on_http(client, monkeypatch):
    # Local dev has no TLS; the default host in tests is 'testserver', so the
    # fallback stays http (matches the existing end-to-end scrub test).
    monkeypatch.setattr(requests, "get",
                        lambda url, **kw: FakeResponse(fake_style(TEST_KEY)))
    r = client.get("/baato/style/breeze")
    style = r.json()
    assert style["sources"]["with_url"]["url"].startswith("http://testserver/baato/api/")


def test_unknown_style_is_404(client):
    r = client.get("/baato/style/not-a-style")
    assert r.status_code == 404
    assert "Unknown Baato style" in r.json()["detail"]


def test_style_requires_server_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "BAATO_KEY", "")
    r = client.get("/baato/style/breeze")
    assert r.status_code == 503
    assert "BAATO_KEY" in r.json()["detail"]


def test_style_propagates_upstream_rejection(client, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, **kw: FakeResponse({}, status=403))
    assert client.get("/baato/style/breeze").status_code == 403


def test_style_handles_unreachable_baato(client, monkeypatch):
    def boom(url, **kw):
        raise requests.RequestException("dns go boom")
    monkeypatch.setattr(requests, "get", boom)
    r = client.get("/baato/style/breeze")
    assert r.status_code == 502


# --- /baato/api proxy -----------------------------------------------------
def test_proxy_appends_key_and_forwards_body(client, monkeypatch):
    seen = {}

    def spy(url, **kw):
        seen["url"] = url
        seen["params"] = kw.get("params")
        return FakeResponse(None, headers={"content-type": "application/x-protobuf"},
                            content=b"\x1a\x0bTILEBYTES")

    monkeypatch.setattr(requests, "get", spy)
    r = client.get("/baato/api/maps/13/6037/3438.pbf")
    assert r.status_code == 200
    assert r.content == b"\x1a\x0bTILEBYTES"
    assert seen["url"] == "https://api.baato.io/api/v1/maps/13/6037/3438.pbf"
    assert seen["params"]["key"] == TEST_KEY


def test_proxy_does_not_echo_content_encoding(client, monkeypatch):
    """requests already decompressed the body — echoing gzip would corrupt tiles."""
    monkeypatch.setattr(requests, "get", lambda url, **kw: FakeResponse(
        None,
        headers={"content-type": "application/x-protobuf", "content-encoding": "gzip"},
        content=b"already-decompressed"))
    r = client.get("/baato/api/maps/1/2/3.pbf")
    assert r.content == b"already-decompressed"
    assert "content-encoding" not in {k.lower() for k in r.headers}


def test_proxy_requires_server_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "BAATO_KEY", "")
    assert client.get("/baato/api/maps/1/2/3.pbf").status_code == 503


def test_static_assets_contain_no_key(client):
    """The dashboard JS/HTML are served to the browser — they must be clean."""
    for path in ("/route-ui", "/static/dashboard.js"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert TEST_KEY not in r.text, path
        # and no hardcoded real-looking Baato key either
        assert "bpk." not in r.text.replace('placeholder="bpk..."', ""), path
