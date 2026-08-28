# GraphHopper incident & custom-model wrapper

A small Python sidecar that runs in front of the GraphHopper server. It keeps the
GraphHopper fork itself unmodified and adds two things on top:

1. **Incident recording** (`/incidents`) — CRUD for road closures / incidents,
   persisted in a local SQLite file.
2. **`custom_model` routing** (`/route`) — the fork's plain `GET /route` has no
   `custom_model` parameter; this wrapper accepts one (GET query param or POST body)
   and forwards a `POST /route` to GraphHopper with the model applied. Every active
   incident is automatically injected as a blocked polygon area
   (`priority: {if: in_<id>, multiply_by: 0}`).

## Run

```bash
./run.sh          # bootstraps a venv and starts uvicorn on :8000
```

Interactive API docs at http://localhost:8000/docs.

## Tests

```bash
pip install -r requirements-dev.txt     # pytest + httpx
python -m pytest                        # from incident-wrapper/
```

56 tests, ~0.5 s. They never touch your real data: `tests/conftest.py` points
`INCIDENTS_DB` at a temp file and injects a dummy `BAATO_KEY` **before** importing
`app` (both are read at import time), and every test starts with an empty table.

| File | Covers |
|---|---|
| `tests/test_incidents.py` | CRUD, 404s, partial updates, ring auto-closing, rejection of <3-point rings, and that geometry really is JSON in a TEXT column |
| `tests/test_baato_proxy.py` | the key never leaves the server: `/config` returns only a boolean, `_scrub_baato_url()` rewrites the key-bearing source, `/baato/style/*` output is asserted key-free, the tile proxy appends the key and does **not** echo `Content-Encoding`, plus 404/503/502 paths |
| `tests/test_route.py` | incident→custom-model injection (`multiply_by: 0`), area-id sanitising, `lat,lon` → `[lon,lat]` flipping and point order, `custom_model` validation, and live-GraphHopper checks |

Tests needing a running GraphHopper are marked and **skip automatically** when
`GRAPHOPPER_URL` is unreachable, so the suite still passes standalone. With it up
they also assert a real multi-stop route is longer than the direct one, that a
blocking incident detours or blocks the route, and that the fork's
`landmark_name` / `has_landmark` details come back.

The suite was mutation-checked — inverting the key scrubbing, `/config` leaking the
key, `multiply_by: 0`→`1`, echoing `Content-Encoding`, and skipping ring closure each
make it fail.

## Dashboard (map UI)

A single-page **MapLibre GL** dashboard with 3D terrain, served at the root:

- http://localhost:8000/  (aliases: /map, /route-ui)

Three independent surfaces (no tabs):

- **Incidents — left panel.** Click **Draw polygon**, then click the map to add
  corners (Finish / double-click / Enter to close, Cancel / Esc to abort). Saves via
  `POST /incidents`. Saved incidents render coloured by type (grey when inactive),
  are clickable for a popup, and are listed with show/deactivate/delete actions.
  **Any change to the incidents layer — save, activate, deactivate, delete —
  immediately re-runs the current route.**
- **Routing — right panel.** Points are placed with **right-click** on the map,
  which opens a context menu: *Set as origin (A)* · *Add stop* · *Set as
  destination (B)* · *Clear all points*. Stops are inserted **between** A and B and
  numbered 1, 2, 3… in travel order, so any number of via-points is supported.
  Remove a point by right-clicking its marker or hitting ✕ in the list; drag a
  marker to move it; edit a row's `lat,lon` to type coordinates. The route
  recalculates **automatically** (debounced) on any change — points added, moved,
  removed, profile switched, or the incident toggle flipped. Summary, distance/time
  and turn-by-turn instructions with landmark badges render in the same panel.
  Dropping below two points clears the line and the summary.
  **Left-click never places routing points** — that is reserved for inspecting
  incidents and drawing polygons, so clicking an incident no longer moves the
  destination.
- **Layers — the map control, bottom-left.** Click *Layers · \<current basemap\>* to
  expand terrain controls, the basemap list, the Baato key field, added layers and
  the add-a-layer form. Collapsed by default.

Each panel collapses independently via its header. Map controls (zoom, pitch, globe,
scale) sit bottom-right so they never collide with the panels.

### When no route is possible

If routing fails, an **alert box** appears over the map (⚠ *Route not possible*) with
a plain-language reason, and the stale route line, summary and instructions are
cleared so nothing misleading stays on screen. GraphHopper's raw errors are
translated: *Connection between locations not found* → "No route could be found
between A and B", out-of-bounds points and missing-point errors likewise.

When incident blocking is on and active incidents exist, the alert appends the
likely cause:

> 3 active incidents are applied as hard blocks — one may be cutting the only path.
> Untick "Apply active incidents (blocking)" to check.

Repeated identical failures (e.g. while dragging a marker through a blocked area) do
not stack alerts, and a successful route dismisses the box automatically.

### 3D terrain

Terrain comes from [Mapterhorn](https://mapterhorn.com) —
`https://tiles.mapterhorn.com/{z}/{x}/{y}.webp`, `raster-dem`, **terrarium**
encoding, tileSize **512**, **maxzoom 12** (z13+ returns 404; MapLibre overzooms
above that). Controls: enable/disable terrain, exaggeration (0–3), pitch (0–85°),
hillshade toggle, and a terrain-source selector.

### Dynamic tile layers

**Default basemap is Baato Breeze** (vector style), served through the wrapper so the
API key never reaches the browser:

1. Put the key in `incident-wrapper/.env` (gitignored) as `BAATO_KEY=…`; `run.sh`
   sources it. Any other env mechanism works too.
2. `GET /config` reports only `{"baato_configured": true}` — never the key itself.
3. `GET /baato/style/breeze` fetches the style server-side and **rewrites the one
   source URL that embeds the key** (`qvez6ula1`, Baato's main vector tile source) to
   point at `GET /baato/api/{path}`, a transparent proxy that re-appends the key
   server-side. Baato's other sources, glyphs and sprite are already keyless CDN URLs
   and are left untouched.

**If `BAATO_KEY` is absent the dashboard falls back to Esri World Imagery and shows a
notice** — it never boots into a broken map. There is deliberately no key input in the
UI; the key is server-side only.

Basemaps, all selectable from the on-map Layers control (bottom-left):

| Kind | Entries | Key needed |
|---|---|---|
| Vector style | Baato Breeze *(default)* | yes (`BAATO_KEY`) |
| Vector style | OpenFreeMap Liberty | no |
| Raster | Esri World Imagery, OpenStreetMap, OpenTopoMap | no |

Raster basemaps swap just the one source. Vector styles replace the whole style, so
they go through `rebuildStyle()`, which re-applies terrain, hillshade, added
overlays, incidents and the current route afterwards. **Terrain is detached before
`setStyle()`** — calling `setStyle()` with terrain active crashes MapLibre with
`cannot read properties of undefined (reading 'shaderPreludeCode')`.

"Add a tile layer" accepts three kinds:

| Type | URL expected | Notes |
|---|---|---|
| XYZ raster | `https://host/{z}/{x}/{y}.png` | added as an overlay with an opacity slider; "Use as base" promotes it to the base layer |
| WMS | `https://host/geoserver/wms` + layer name | the `GetMap` query is built for you using `{bbox-epsg-3857}` |
| Terrain / DEM | `https://host/{z}/{x}/{y}.webp` + encoding | no visible layer; appears in the terrain-source selector via "Use for terrain" |

**Saving added layers** — the add form has a *"Save locally for future sessions"*
checkbox (on by default):

- checked → written to `localStorage`, badged **SAVED**, returns on every reload
- unchecked → session only, badged **SESSION**, gone after a reload

Either decision is reversible from the layer row: **Save locally** promotes a session
layer to permanent, **Forget** demotes a saved one (it stays on the map for the rest
of the session but is dropped from storage). **Remove** deletes it outright.

Layer order is fixed: basemap → added overlays → hillshade → incidents → draft → route.

Google's XYZ tile endpoints are not included — they require the Google Map Tiles
API and their ToS disallows direct `mt*.google.com` use.

Environment variables:

| var            | default                                  | meaning                      |
|----------------|------------------------------------------|------------------------------|
| `GRAPHOPPER_URL` | `http://localhost:8989`                | upstream GraphHopper base URL |
| `INCIDENTS_DB` | `./incidents.db` (next to app.py)        | SQLite file for incidents    |
| `PORT`         | `8000`                                   | listen port                  |

## Record an incident

```bash
curl -s -X POST http://localhost:8000/incidents -H 'Content-Type: application/json' -d '{
  "type": "ROAD_CLOSURE",
  "description": "Bridge collapse on Ring Road",
  "coordinates": [[85.31, 27.71], [85.33, 27.71], [85.33, 27.73], [85.31, 27.73]]
}'
```

`coordinates` is a GeoJSON polygon ring of `[lon, lat]` pairs (auto-closed if needed).

## Route with incidents + custom_model applied

```bash
# GET: points are lat,lon; incidents are applied by default
curl -s "http://localhost:8000/route?point=27.7172,85.3240&point=28.2096,83.9856&profile=car"

# pass an extra custom_model on the query string, incidents still applied
curl -s "http://localhost:8000/route?point=27.7172,85.3240&point=28.2096,83.9856&profile=car&custom_model=%7B%22priority%22%3A%5B%7B%22if%22%3A%22road_class%20%3D%3D%20PRIMARY%22%2C%22multiply_by%22%3A%220.5%22%7D%5D%7D"

# opt out of incident injection for a single request
curl -s "http://localhost:8000/route?point=27.7172,85.3240&point=28.2096,83.9856&profile=car&apply_incidents=false"
```

The `POST /route` endpoint accepts the same JSON body as GraphHopper's `POST /route`
(points in `[lon, lat]` order) and forwards it, injecting incidents and merging the
`custom_model` field.
