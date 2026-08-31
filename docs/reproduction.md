# Reproduction Guide

How to rebuild and run the **Rasuwa Flood — Dynamic Real-Time Road Update &
Route Monitoring System** on a clean machine. The system is the GraphHopper
landmark fork (Java) plus a FastAPI wrapper (Python) that adds incidents,
per-request road blocking, Baato basemaps and the map dashboard.

Two paths, both documented below:

- **Path A — build from source** (clone, compile, import, run)
- **Path B — prebuilt bundle** (no build, no import, no config)

---

## 1. Architecture

```
browser ──► wrapper :8000 (FastAPI) ──► graphhopper :8989 (unmodified Java fork)
```

- The Java fork is **never modified**; all custom behaviour lives in the wrapper.
- The browser talks only to `:8000` — the Baato API key never reaches it
  (the wrapper proxies Baato server-side).
- Data: `graph-cache/` (imported road graph) and
  `incident-wrapper/data/incidents.db` (SQLite incident store).

---

## 2. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| JDK | 25+ | compile target `<release>25</release>` |
| Maven | 3.9+ | multi-module build |
| Python | 3.12 | wrapper only (not the Java build) |
| Docker + compose | any recent | Path B, and running the stack |

The wrapper's only Python dependencies are `fastapi`, `uvicorn`, `requests`
(plus `pytest`/`httpx` for tests).

---

## 3. Path A — build from source

### 3.1 Get the code

```bash
git clone git@github.com:neogeomat/graphhopper.git
cd graphhopper
git checkout landmark_from_gh
```

`neogeomat` is the fork; `origin` (github.com/graphhopper/graphhopper) is
upstream. All work lives on the `landmark_from_gh` branch.

### 3.2 Build the Java fork

```bash
mvn clean install -DskipTests
```

This produces the fat jar `web/target/graphhopper-web-12.0-SNAPSHOT.jar`.

### 3.3 Data files

Two things must be present next to the jar (they are gitignored):

- `Nepal_data.v07172026.osm.pbf` (~387 MB) — OSM extract
- `graph-cache/` (~173 MB) — the imported graph

**If you have the pre-imported `graph-cache/`, skip 3.4** — the engine serves
immediately. Only a fresh import needs the PBF (and SRTM elevation data, which
is downloaded from the network during import).

### 3.4 Import (only if `graph-cache/` is absent)

The import runs automatically on first start when `graph-cache/` is empty, or
explicitly via the CLI import command. Either way the config below drives it.
Memory: `JAVA_OPTS="-Xmx4g -Xms512m"` is plenty for serving; bump `-Xmx` for a
larger extract.

### 3.5 `config.yml`

`config.yml` is **gitignored** and does not survive a fresh clone — recreate it.
Working configuration (comments stripped):

```yaml
graphhopper:
  datareader.file: Nepal_data.v07172026.osm.pbf
  graph.location: graph-cache

  profiles:
    - name: car
      custom_model_files: [car.json]
    - name: foot
      custom_model_files: [foot.json, foot_elevation.json]
    - name: bike
      custom_model_files: [bike.json, bike_elevation.json]

  profiles_lm: []                       # unrelated to POI landmarks

  graph.encoded_values: |
    has_landmark, landmark_name, average_slope, bike_access, bike_average_speed, bike_priority, bike_road_access, bike_network, car_access, car_average_speed, country, ferry_speed, foot_access, foot_average_speed, foot_priority, foot_road_access, hike_rating, road_class, road_environment, roundabout, max_speed, mtb_rating

  prepare.lm.landmarks: 16
  graph.elevation.provider: srtm
  graph.elevation.dataaccess: RAM_STORE
  prepare.min_network_size: 200
  prepare.subnetworks.threads: 1
  routing.snap_preventions_default: tunnel, bridge, ferry
  routing.timeout_ms: 3000000
  routing.non_ch.max_waypoint_distance: 1000000
  graph.dataaccess.default_type: RAM_STORE

server:
  application_connectors:
    - type: http
      port: 8989
      bind_host: localhost
  admin_connectors:
    - type: http
      port: 8990
      bind_host: localhost
```

Two facts that matter:

- `has_landmark` and `landmark_name` **must lead** `graph.encoded_values` — they
  are this fork's encoded values and their ordering is part of the persisted
  `EncodingManager` string.
- The on-disk fork config points `datareader.file` at
  `Nepal_data.v07172026.osmf.pbf` (a stale name). The real file is `.osm.pbf`, so
  start with the override:

```bash
java -Ddw.graphhopper.datareader.file=Nepal_data.v07172026.osm.pbf \
     -jar web/target/graphhopper-web-12.0-SNAPSHOT.jar server config.yml
```

Any config key is overridable as `-Ddw.<yaml.path>=<value>`. Note the override
keys use the YAML's **snake_case** paths (`application_connectors`), not the
camelCase Java property names.

> **Graph-cache validation.** The engine hashes each profile (name + turn costs +
> weighting + hints, incl. the custom model). If you change a profile's
> `custom_model_files` or `graph.encoded_values`, startup fails with
> `Profile 'car' does not match` — delete `graph-cache/` and re-import. Query-time
> custom models (what the wrapper injects) do **not** affect the hash.

### 3.6 The wrapper

```bash
cd incident-wrapper
./run.sh                    # bootstraps .venv, installs deps, sources .env, runs uvicorn :8000
```

`run.sh` creates `.venv` and installs `requirements.txt` on first run, then
sources `.env` and starts uvicorn. `.env` is gitignored — create it yourself from
§3.7 before the first run.

### 3.7 Environment (gitignored `incident-wrapper/.env`)

```bash
BAATO_KEY=<your-key>          # required for the Baato Breeze basemap + geocoding
GRAPHOPPER_URL=http://localhost:8989
INCIDENTS_DB=<absolute-or-relative-path>/incidents.db   # default: data/incidents.db
PORT=8000
ADMIN_USERNAME=admin          # login for editing incidents
ADMIN_PASSWORD=change-me      # change from the default 'admin'
```

The wrapper falls back to Esri World Imagery (with a notice) when `BAATO_KEY`
is absent, so the stack still runs without it.

**Authentication**: editing incidents (create/update/delete) requires a login —
`POST /login` returns a bearer token that the dashboard stores and sends as
`Authorization: Bearer …`. Reads stay public. The credentials default to
`admin`/`admin`; set a real `ADMIN_PASSWORD` (rotating it invalidates all
tokens).

### 3.8 Tests

```bash
cd incident-wrapper
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest        # 56 tests, ~0.5s
```

GraphHopper-dependent tests skip automatically when `GRAPHOPPER_URL` is
unreachable, so the suite passes standalone.

---

## 4. Path B — prebuilt bundle (no setup)

The export bundle ships both docker images plus the imported graph, the PBF,
the incident DB and the key — a fresh machine needs only Docker.

```bash
tar -xzf rasuwa-flood-<date>.tar.gz
./start.sh          # docker load -i images.tar.gz && docker compose up -d
```

| Service | URL |
|---|---|
| Dashboard (map, incidents, routing, geocoding) | http://localhost:8000 |
| GraphHopper API | http://localhost:8989 |
| GraphHopper admin | http://localhost:8990 |

See the bundle's `README.md` for the data layout, persistence and the API-key
handling note.

---

## 5. Docker (from the repo)

```bash
docker compose up -d
```

Two services:

| Service | Image | Notes |
|---|---|---|
| `graphhopper` | `graphhopper-landmark:latest` | multi-stage Maven build, ~577 MB |
| `wrapper` | `graphhopper-incident-wrapper:latest` | python:3.12-slim, :8000 |

Key details (each one earned in testing):

- The wrapper reaches the engine as `http://graphhopper:8989` (service name),
  **not** `localhost`.
- `BAATO_KEY` is injected at runtime via `env_file … required: false`; the
  `.dockerignore` keeps `.env` out of the image.
- The incident DB is a **directory** mount (`./incident-wrapper/data:/data`), not
  a single file — Docker creates a single-file mount as a *directory* on a fresh
  clone, and SQLite needs to write its journal beside the db.
- `static/` is baked into the wrapper image, so a dashboard edit needs
  `docker compose build wrapper && docker compose up -d wrapper` — not a refresh.
- The `graphhopper` healthcheck is `bash` + `/dev/tcp` because the JRE image has
  no `curl` or `wget`; `start_period: 300s` covers the cold graph load.

---

## 6. Verify it is up

```bash
docker compose ps                              # both (healthy)

curl http://localhost:8000/health
# → {"status":"ok","upstream":"http://graphhopper:8989"}

curl http://localhost:8000/config
# → {"baato_configured":true}          # never the key itself

curl "http://localhost:8000/route?point=27.7172,85.3240&point=27.7215,85.3310&profile=car"
# → {"paths":[{"distance":…, "time":…}]}

curl "http://localhost:8000/incidents"
# → [] (or the pre-seeded closures in the bundle)
```

The dashboard should load at `http://localhost:8000` with the title
**Rasuwa Flood — Dynamic Real-Time Road Update & Route Monitoring System**,
Baato Breeze as the basemap, and 3D terrain.

---

## 7. Known gotchas

- **`.osmf.pbf` vs `.osm.pbf`** — the on-disk config has a stale filename; always
  start with the `-Ddw.graphhopper.datareader.file=` override.
- **`Profile 'car' does not match`** — you changed profiles/encoded values after
  import. Delete `graph-cache/` and re-import.
- **camelCase Dropwizard overrides fail** (`node with index not found`) — use the
  YAML snake_case keys.
- **Blocking geometry** — an incident polygon must actually intersect the road.
  A ±0.0016° box (~175 m) does *not* block; ±0.006° (~660 m) does.
- **`queryRenderedFeatures` undercounts** under pitch/terrain — verify rendering
  with a screenshot pixel/diff, not feature counts.
- **Baato font 403s** on emoji/symbol glyph ranges are Baato's content gap,
  keyless, and harmless.
- **`pkill -f graphhopper-web-12.0-SNAPSHOT.jar`** also kills the launching shell —
  stop by PID instead.
