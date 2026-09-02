"""Routing wrapper: incident injection into the custom model, and /route plumbing.

The custom-model tests are pure logic (no network). The tests that need a live
GraphHopper are marked `integration` and skip automatically when it is down.
"""
import json

import pytest
import requests

import app as app_module

GH_UP = None


def graphhopper_up():
    global GH_UP
    if GH_UP is None:
        try:
            GH_UP = requests.get(f"{app_module.GRAPHOPPER_URL}/health", timeout=4).status_code == 200
        except requests.RequestException:
            GH_UP = False
    return GH_UP


needs_gh = pytest.mark.skipif(not graphhopper_up(),
                              reason="GraphHopper not reachable at GRAPHOPPER_URL")


# --- custom-model merging (pure) ------------------------------------------
def test_no_incidents_no_model():
    assert app_module.merge_custom_model(None, apply_incidents=True) is None


def test_user_model_passes_through_untouched():
    user = {"speed": [{"if": "true", "limit_to": "20"}]}
    out = app_module.merge_custom_model(user, apply_incidents=False)
    assert out == user


def test_active_incident_becomes_a_hard_block(make_incident):
    inc = make_incident()
    cm = app_module.merge_custom_model(None, apply_incidents=True)
    assert cm is not None
    area_id = inc["id"]                       # already [a-z0-9_], so unchanged
    assert area_id in cm["areas"]
    assert cm["areas"][area_id]["type"] == "Feature"
    assert cm["areas"][area_id]["geometry"]["type"] == "Polygon"
    # ring is nested one level deep, and closed
    ring = cm["areas"][area_id]["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    # priority 0 => infinite weight => hard block
    assert {"if": "in_" + area_id, "multiply_by": "0"} in cm["priority"]


def test_inactive_incident_is_not_injected(make_incident):
    make_incident(active=False)
    assert app_module.merge_custom_model(None, apply_incidents=True) is None


def test_apply_incidents_false_skips_injection(make_incident):
    make_incident()
    assert app_module.merge_custom_model(None, apply_incidents=False) is None


def test_incidents_are_appended_to_a_user_model(make_incident):
    make_incident()
    user = {"priority": [{"if": "road_class == MOTORWAY", "multiply_by": "0.5"}],
            "areas": {"mine": {"type": "Feature", "geometry": {}}}}
    cm = app_module.merge_custom_model(user, apply_incidents=True)
    assert cm is not None
    assert "mine" in cm["areas"] and len(cm["areas"]) == 2
    # the user's own statement stays first
    assert cm["priority"][0]["if"] == "road_class == MOTORWAY"
    assert len(cm["priority"]) == 2


def test_many_incidents_each_get_an_area(make_incident):
    ids = [make_incident()["id"] for _ in range(3)]
    cm = app_module.merge_custom_model(None, apply_incidents=True)
    assert cm is not None
    assert sorted(cm["areas"]) == sorted(ids)
    assert len(cm["priority"]) == 3


# --- area-id sanitising ---------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("inc_abc123", "inc_abc123"),
    ("has-dashes", "has_dashes"),
    ("dots.and spaces", "dots_and_spaces"),
    ("__leading_and_trailing__", "leading_and_trailing"),
    ("", "unknown"),
    ("!!!", "unknown"),
])
def test_sanitize_id(raw, expected):
    assert app_module.sanitize_id(raw) == expected


# --- user custom_model parsing -------------------------------------------
def test_bad_custom_model_json_is_400(client):
    r = client.get("/route", params={"point": ["27.7,85.3", "27.8,85.4"],
                                     "custom_model": "{not json"})
    assert r.status_code == 400
    assert "Invalid custom_model JSON" in r.json()["detail"]


def test_non_object_custom_model_is_400(client):
    r = client.get("/route", params={"point": ["27.7,85.3", "27.8,85.4"],
                                     "custom_model": "[1,2,3]"})
    assert r.status_code == 400
    assert "must be a JSON object" in r.json()["detail"]


def test_malformed_point_is_400(client):
    r = client.get("/route", params={"point": ["not-a-point", "27.8,85.4"]})
    assert r.status_code == 400
    assert "expected 'lat,lon'" in r.json()["detail"]


def test_single_point_still_reaches_upstream(client, monkeypatch):
    """The wrapper does not enforce >=2 points itself; GraphHopper reports that."""
    captured = {}

    class R:
        status_code = 400
        content = b'{"message":"at least 2 points"}'
        headers = {"content-type": "application/json"}

    def spy(url, json=None, timeout=None):
        captured["body"] = json
        return R()

    monkeypatch.setattr(requests, "post", spy)
    client.get("/route", params={"point": ["27.7,85.3"]})
    assert captured["body"]["points"] == [[85.3, 27.7]]     # flipped to [lon,lat]


def test_points_are_flipped_and_ordered(client, monkeypatch):
    """GET takes lat,lon; the upstream POST body needs [lon,lat] in travel order."""
    captured = {}

    class R:
        status_code = 200
        content = b'{"paths":[]}'
        headers = {"content-type": "application/json"}

    monkeypatch.setattr(requests, "post",
                        lambda url, json=None, timeout=None: (captured.update(body=json), R())[1])
    client.get("/route", params={"point": ["27.70,85.30", "27.75,85.35", "27.80,85.40"],
                                "profile": "bike"})
    assert captured["body"]["points"] == [[85.30, 27.70], [85.35, 27.75], [85.40, 27.80]]
    assert captured["body"]["profile"] == "bike"


def test_incident_model_is_attached_to_the_upstream_request(client, monkeypatch, make_incident):
    inc = make_incident()
    captured = {}

    class R:
        status_code = 200
        content = b'{"paths":[]}'
        headers = {"content-type": "application/json"}

    monkeypatch.setattr(requests, "post",
                        lambda url, json=None, timeout=None: (captured.update(body=json), R())[1])
    client.get("/route", params={"point": ["27.7,85.3", "27.8,85.4"], "apply_incidents": "true"})
    cm = captured["body"]["custom_model"]
    assert inc["id"] in cm["areas"]
    assert cm["priority"][0]["multiply_by"] == "0"


def test_apply_incidents_false_sends_no_model(client, monkeypatch, make_incident):
    make_incident()
    captured = {}

    class R:
        status_code = 200
        content = b'{"paths":[]}'
        headers = {"content-type": "application/json"}

    monkeypatch.setattr(requests, "post",
                        lambda url, json=None, timeout=None: (captured.update(body=json), R())[1])
    client.get("/route", params={"point": ["27.7,85.3", "27.8,85.4"], "apply_incidents": "false"})
    assert "custom_model" not in captured["body"]


# --- live GraphHopper -----------------------------------------------------
@needs_gh
def test_health_reports_upstream(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["version"] == app_module.APP_VERSION
    assert body["upstream"] == app_module.GRAPHOPPER_URL


def test_health_reports_version_without_upstream(anon_client):
    # /health never calls upstream — the version banner must work standalone.
    body = anon_client.get("/health").json()
    assert body["status"] == "ok"
    assert body["version"] == app_module.APP_VERSION


@needs_gh
def test_real_two_point_route(client):
    r = client.get("/route", params={"point": ["27.7172,85.3240", "27.7215,85.3310"],
                                     "profile": "car", "points_encoded": "false"})
    assert r.status_code == 200, r.text
    path = r.json()["paths"][0]
    assert path["distance"] > 0
    assert path["points"]["type"] == "LineString"
    assert len(path["points"]["coordinates"]) > 2


@needs_gh
def test_real_route_with_a_via_point_is_longer(client):
    two = client.get("/route", params={"point": ["27.7172,85.3240", "27.7215,85.3310"],
                                       "profile": "car"}).json()["paths"][0]["distance"]
    three = client.get("/route", params={"point": ["27.7172,85.3240", "27.7290,85.3175",
                                                   "27.7215,85.3310"],
                                         "profile": "car"}).json()["paths"][0]["distance"]
    assert three > two


@needs_gh
def test_blocking_incident_changes_or_blocks_the_route(client, box):
    """A wide enough polygon across the corridor must block it.

    NOTE: geometry matters — a ~175 m box at the midpoint does NOT intersect the
    road, a ~660 m one does. Verified by hand before writing this test.
    """
    pts = {"point": ["27.7172,85.3240", "27.7215,85.3310"], "profile": "car"}
    before = client.get("/route", params=pts)
    assert before.status_code == 200
    baseline = before.json()["paths"][0]["distance"]

    inc = client.post("/incidents", json={
        "type": "ROAD_CLOSURE", "description": "pytest block",
        "coordinates": box(lon=85.3275, lat=27.7195, d=0.006),
    }).json()
    try:
        after = client.get("/route", params=pts)
        if after.status_code == 200:
            assert after.json()["paths"][0]["distance"] != baseline    # detoured
        else:
            assert after.status_code == 400                            # fully blocked
            assert "not found" in after.text.lower()
        # and with blocking off, the original route is available again
        off = client.get("/route", params={**pts, "apply_incidents": "false"})
        assert off.status_code == 200
        assert off.json()["paths"][0]["distance"] == baseline
    finally:
        client.delete(f"/incidents/{inc['id']}")


@needs_gh
def test_landmark_details_are_available(client):
    """The fork's reason for existing: has_landmark / landmark_name encoded values."""
    r = client.get("/route", params={"point": ["27.7172,85.3240", "27.7215,85.3310"],
                                     "profile": "car", "points_encoded": "false",
                                     "details": ["landmark_name", "has_landmark"]})
    assert r.status_code == 200, r.text
    details = r.json()["paths"][0]["details"]
    assert "landmark_name" in details
    assert "has_landmark" in details
