"""Incident CRUD + storage behaviour."""
import json

import app as app_module


def test_list_empty(client):
    r = client.get("/incidents")
    assert r.status_code == 200
    assert r.json() == []


def test_create_returns_201_and_generated_id(client, box):
    r = client.post("/incidents", json={"coordinates": box()})
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("inc_")
    assert len(body["id"]) == len("inc_") + 12
    assert body["type"] == "ROAD_CLOSURE"      # documented default
    assert body["description"] == ""
    assert body["source"] == ""                # source is optional
    assert body["active"] is True
    assert body["created_at"] == body["updated_at"]


def test_create_closes_the_ring(client, box):
    """A 4-corner box is stored as 5 points; GraphHopper needs a closed ring."""
    ring = box()
    assert ring[0] != ring[-1]
    body = client.post("/incidents", json={"coordinates": ring}).json()
    assert len(body["coordinates"]) == len(ring) + 1
    assert body["coordinates"][0] == body["coordinates"][-1]


def test_already_closed_ring_is_not_double_closed(client, box):
    ring = box()
    ring.append(list(ring[0]))
    body = client.post("/incidents", json={"coordinates": ring}).json()
    assert len(body["coordinates"]) == len(ring)


def test_coordinates_stored_as_json_text(client, box, make_incident):
    inc = make_incident()
    with app_module.db() as conn:
        row = conn.execute("SELECT coordinates, typeof(coordinates) AS t, active, "
                           "typeof(active) AS at FROM incidents WHERE id = ?",
                           (inc["id"],)).fetchone()
    assert row["t"] == "text"                       # geometry is JSON in a TEXT column
    assert json.loads(row["coordinates"]) == inc["coordinates"]
    assert row["at"] == "integer" and row["active"] == 1


def test_reject_too_few_points(client):
    r = client.post("/incidents", json={"coordinates": [[85.0, 27.0], [85.1, 27.1]]})
    assert r.status_code == 400
    assert "at least 3" in r.json()["detail"]


def test_reject_empty_ring(client):
    r = client.post("/incidents", json={"coordinates": []})
    assert r.status_code == 400
    assert "non-empty" in r.json()["detail"]


def test_reject_malformed_coordinates(client):
    r = client.post("/incidents", json={"coordinates": "not-a-ring"})
    assert r.status_code == 422        # pydantic rejects before our handler


def test_get_by_id_and_404(client, make_incident):
    inc = make_incident(description="pipeline works")
    assert client.get(f"/incidents/{inc['id']}").json()["description"] == "pipeline works"
    r = client.get("/incidents/inc_doesnotexist")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_partial_update_only_touches_given_fields(client, make_incident):
    inc = make_incident(type="ACCIDENT", description="keep me")
    r = client.put(f"/incidents/{inc['id']}", json={"active": False})
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is False
    assert body["type"] == "ACCIDENT"          # untouched
    assert body["description"] == "keep me"    # untouched
    assert body["created_at"] == inc["created_at"]
    assert body["updated_at"] >= inc["updated_at"]


def test_update_reclosees_new_ring(client, make_incident, box):
    inc = make_incident()
    new = box(lon=86.0, lat=28.0, d=0.01)
    body = client.put(f"/incidents/{inc['id']}", json={"coordinates": new}).json()
    assert body["coordinates"][0] == body["coordinates"][-1]
    assert len(body["coordinates"]) == len(new) + 1


def test_update_missing_is_404(client, box):
    r = client.put("/incidents/inc_nope", json={"active": False})
    assert r.status_code == 404


def test_delete_returns_204_then_404(client, make_incident):
    inc = make_incident()
    assert client.delete(f"/incidents/{inc['id']}").status_code == 204
    assert client.get(f"/incidents/{inc['id']}").status_code == 404
    assert client.delete(f"/incidents/{inc['id']}").status_code == 404


def test_list_is_ordered_by_created_at(client, make_incident):
    a = make_incident(description="first")
    b = make_incident(description="second")
    ids = [i["id"] for i in client.get("/incidents").json()]
    assert ids == [a["id"], b["id"]]


def test_active_incidents_helper_filters_inactive(client, make_incident):
    on = make_incident(description="on")
    off = make_incident(description="off", active=False)
    active_ids = [i["id"] for i in app_module.active_incidents()]
    assert on["id"] in active_ids
    assert off["id"] not in active_ids


def test_create_with_source_and_echo(client, make_incident):
    inc = make_incident(description="landslide", source="Field team 3")
    assert client.get(f"/incidents/{inc['id']}").json()["source"] == "Field team 3"


def test_patch_source(client, make_incident):
    inc = make_incident()
    body = client.put(f"/incidents/{inc['id']}", json={"source": "Police report"}).json()
    assert body["source"] == "Police report"
    assert body["description"] == ""          # untouched


def test_patch_source_to_blank_clears_it(client, make_incident):
    inc = make_incident(source="old source")
    body = client.put(f"/incidents/{inc['id']}", json={"source": ""}).json()
    assert body["source"] == ""
