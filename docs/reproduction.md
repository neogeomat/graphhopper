# Reproduction Guide — GraphHopper landmark fork (engine)

How to rebuild and run the engine of the **Rasuwa Flood — Dynamic Real-Time Road
Update & Route Monitoring System** on a clean machine. This repo is the
GraphHopper Java fork **only**.

The system has three pieces, each in its own repo since the 2026-09-02 split:

| Piece | Repo | Notes |
|---|---|---|
| Engine (this repo) | `neogeomat/graphhopper`, branch `rasuwa_flood_dyn_routing` | Java fork, unmodified upstream + landmark feature |
| Wrapper | `incident-wrapper` (separate repo) | FastAPI sidecar: incidents, custom-model routing, Baato proxy, map dashboard. Own `Dockerfile` + `docker-compose.yml`; reaches the engine over HTTP via `GRAPHOPPER_URL`. Run/tests/env/auth/UI docs live in **its** README. |
| Deployment glue + bundle | `rasuwa-flood-export` | Combined `docker-compose.yml` (both services on one network), `assemble.sh`, `start.sh`; produces the ship bundle |

Two paths, both documented below:

- **Path A — build from source** (clone, compile, import, run)
- **Path B — prebuilt bundle** (no build, no import, no config)

---

## 1. Architecture

```
browser ──► wrapper :8000 (separate repo) ──► graphhopper :8989 (this repo)
```

- The Java fork is **never modified**; all custom behaviour lives in the
  wrapper (its own repo). The wrapper talks to this engine only over HTTP.
- Data in this repo: `graph-cache/` (imported road graph) and the OSM PBF.
  The incident store (`data/incidents.db`) lives in the wrapper repo.

---

## 2. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| JDK | 25+ | compile target `<release>25</release>` |
| Maven | 3.9+ | multi-module build |
| Docker + compose | any recent | Path B, and running the stack |

---

## 3. Path A — build the engine from source

### 3.1 Get the code

```bash
git clone git@github.com:neogeomat/graphhopper.git
cd graphhopper
git checkout rasuwa_flood_dyn_routing
```

`neogeomat` is the fork; `origin` (github.com/graphhopper/graphhopper) is
upstream — never push upstream. (`landmark_from_gh` is a legacy branch; all
current work is on `rasuwa_flood_dyn_routing`.)

### 3.2 Build

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

The wrapper is **not in this repo** since the 2026-09-02 split. Get it from its
own repository, then:

```bash
cd <wrapper repo>
./run.sh        # bootstraps .venv, installs deps, sources .env, runs uvicorn :8000
```

`.env` (gitignored) holds `BAATO_KEY`, `GRAPHOPPER_URL`
(default `http://localhost:8989`), `INCIDENTS_DB`, `PORT`, and the
`ADMIN_USERNAME`/`ADMIN_PASSWORD` login for editing incidents. Full
run/tests/UI documentation: the wrapper repo's `README.md`.

---

## 4. Docker (from this repo)

```bash
docker compose up -d
```

One service (since the split):

| Service | Image | Notes |
|---|---|---|
| `graphhopper` | `graphhopper-landmark:latest` | multi-stage Maven build, ~577 MB, 8989/8990 |

Key details (each one earned in testing):

- Bind-mounts `./graph-cache` (persists, no re-import) and the PBF read-only.
- The healthcheck is `bash` + `/dev/tcp` because the JRE image has **no curl or
  wget**; `start_period: 300s` covers the cold graph load.
- The `wrapper` service used to live here too; it now has its own compose in
  the wrapper repo (single service, `GRAPHOPPER_URL` default
  `http://host.docker.internal:8989` — same Docker host). For both services on
  **one** compose network (wrapper reaching the engine by service name), use
  the combined deploy compose in `rasuwa-flood-export/docker-compose.yml`.

---

## 5. Path B — prebuilt bundle (whole system, no setup)

The export bundle ships both docker images plus the imported graph, the PBF,
the incident DB and the key — a fresh machine needs only Docker.

```bash
tar -xzf rasuwa-flood-<version>-<date>.tar.gz
./start.sh          # docker load -i images.tar.gz && docker compose up -d
```

| Service | URL |
|---|---|
| Dashboard (map, incidents, routing, geocoding) | http://localhost:8000 |
| GraphHopper API | http://localhost:8989 |
| GraphHopper admin | http://localhost:8990 |

See the bundle's `README.md` for the data layout, persistence and the API-key
handling note, and this repo §3 for rebuilding the engine image from source.

---

## 6. Verify the engine is up

```bash
docker compose ps                              # graphhopper (healthy)

# Engine directly (this repo):
curl "http://localhost:8989/route?point=27.7172,85.3240&point=27.7215,85.3310&profile=car"
# → {"paths":[{...}]}

# Whole system (engine + wrapper): the wrapper's /health shows the engine it is
# wired to; the dashboard loads at http://localhost:8000 — see the wrapper repo.
```

---

## 7. Known gotchas

- **`.osmf.pbf` vs `.osm.pbf`** — the on-disk config has a stale filename; always
  start with the `-Ddw.graphhopper.datareader.file=` override.
- **`Profile 'car' does not match`** — you changed profiles/encoded values after
  import. Delete `graph-cache/` and re-import.
- **camelCase Dropwizard overrides fail** (`node with index not found`) — use the
  YAML snake_case keys.
- **`pkill -f graphhopper-web-12.0-SNAPSHOT.jar`** also kills the launching shell —
  stop by PID instead.
- Wrapper/dashboard gotchas (blocking-polygon geometry, `queryRenderedFeatures`
  undercounts under terrain, Baato font 403s, terrain-before-setStyle crashes)
  are documented in the wrapper repo's `README.md`/`AGENTS.md`.
