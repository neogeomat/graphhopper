"""Reroute-section attribution: which stretch of a route was rerouted by which
incident polygon.

Pure geometry — no network, no DB.  compute_reroutes(actual, baseline,
incidents) compares the route computed WITH incidents (actual) against the
route computed WITHOUT them (baseline), and for every active incident polygon
that cuts the baseline reports the avoided stretch and the detour the actual
route takes around it.
"""
import requests

import app as app_module


# baseline: straight west→east at lat 0, lon 0..10
BASE = [[lon, 0.0] for lon in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]

# actual: leaves the baseline at (4,0), arcs north over lat 1.2, rejoins at (6,0)
ACTUAL = [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [4, 0.6], [5, 1.2],
          [6, 0.6], [6, 0], [7, 0], [8, 0], [9, 0], [10, 0]]

# blocking square: lon 4..6, lat -1..1 (open ring, like the DB stores)
POLY = [[4, -1], [6, -1], [6, 1], [4, 1]]


def test_detects_one_reroute_for_one_blocking_polygon():
    reroutes = app_module.compute_reroutes(
        ACTUAL, BASE,
        [{"id": "i1", "coordinates": POLY, "type": "ROAD_CLOSURE",
          "description": "landslide"}])
    assert len(reroutes) == 1
    r = reroutes[0]
    assert r["incident_id"] == "i1"
    assert r["type"] == "ROAD_CLOSURE"
    # avoided stretch lies on/in the polygon (lon 4..6 at lat 0), allowing the
    # 25 m capture buffer which extends the cut a hair past the polygon edge
    assert len(r["avoided"]) >= 2
    assert 4.0 - 0.001 <= min(p[0] for p in r["avoided"])
    assert max(p[0] for p in r["avoided"]) <= 6.0 + 0.001
    # detour leaves/joins at the polygon corners and actually goes around
    assert len(r["detour"]) >= 2
    assert max(p[1] for p in r["detour"]) > 1.0        # rose above the top edge
    assert min(p[0] for p in r["detour"]) <= 4.0       # starts at/left of the box
    assert max(p[0] for p in r["detour"]) >= 6.0       # ends at/right of the box


def test_no_reroutes_when_baseline_avoids_all_polygons():
    far = [[lon, 5.0] for lon in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]
    assert app_module.compute_reroutes(
        ACTUAL, far,
        [{"id": "i1", "coordinates": POLY, "type": "ROAD_CLOSURE",
          "description": "x"}]) == []


def test_empty_inputs_yield_no_reroutes():
    assert app_module.compute_reroutes([], [], []) == []
    assert app_module.compute_reroutes(ACTUAL, [], []) == []
    assert app_module.compute_reroutes(ACTUAL, BASE, []) == []


# --- /route reroute_details wiring ----------------------------------------
def _gh_path_payload(coords, distance=12000, time=600000):
    return {"paths": [{"points": {"type": "LineString", "coordinates": coords},
                       "distance": distance, "time": time}],
            "info": {"took": 5}}


def test_reroute_details_attaches_attribution(client, monkeypatch, make_incident):
    """apply_incidents=true + reroute_details=true runs a second (incident-free)
    route upstream and returns per-incident rerouted stretches."""
    inc = make_incident(coordinates=[list(p) for p in POLY])
    calls = []

    class R:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

    def fake_post(url, json=None, timeout=None):
        calls.append(json)
        has_areas = bool((json.get("custom_model") or {}).get("areas"))
        r = R()
        r._payload = _gh_path_payload(ACTUAL if has_areas else BASE)
        return r

    monkeypatch.setattr(requests, "post", fake_post)
    r = client.get("/route", params={"point": ["0,0", "0,10"],
                                     "apply_incidents": "true",
                                     "reroute_details": "true",
                                     "points_encoded": "false"})
    assert r.status_code == 200
    assert len(calls) == 2                      # actual + baseline
    path0 = r.json()["paths"][0]
    assert "baseline" in path0
    reroutes = path0["reroutes"]
    assert len(reroutes) == 1
    assert reroutes[0]["incident_id"] == inc["id"]
    assert len(reroutes[0]["detour"]) >= 2
    assert len(reroutes[0]["avoided"]) == 2


def test_reroute_details_requires_active_incidents(client, monkeypatch):
    """No incidents -> no second upstream call, no reroutes key."""
    calls = []

    class R:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

    def fake_post(url, json=None, timeout=None):
        calls.append(json)
        r = R()
        r._payload = _gh_path_payload(BASE)
        return r

    monkeypatch.setattr(requests, "post", fake_post)
    r = client.get("/route", params={"point": ["0,0", "0,10"],
                                     "apply_incidents": "true",
                                     "reroute_details": "true",
                                     "points_encoded": "false"})
    assert r.status_code == 200
    assert len(calls) == 1
    assert "reroutes" not in r.json()["paths"][0]


def test_reroute_details_false_is_single_call_and_unchanged(client, monkeypatch, make_incident):
    """Default behaviour: exactly one upstream call, response passes through."""
    make_incident(coordinates=[list(p) for p in POLY])
    calls = []

    class R:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

    def fake_post(url, json=None, timeout=None):
        calls.append(json)
        r = R()
        r._payload = _gh_path_payload(ACTUAL)
        return r

    monkeypatch.setattr(requests, "post", fake_post)
    r = client.get("/route", params={"point": ["0,0", "0,10"],
                                     "apply_incidents": "true",
                                     "points_encoded": "false"})
    assert r.status_code == 200
    assert len(calls) == 1
    body = r.json()
    assert "reroutes" not in body["paths"][0]
    assert "baseline" not in body["paths"][0]
