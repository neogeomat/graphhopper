# Changelog — Rasuwa Flood routing system

Release history of the deployment bundle (incident wrapper + dashboard +
containerized GraphHopper landmark fork). Git tags follow
`rasuwa-flood-vX.Y-YYYYMMDD`; export tarballs are
`rasuwa-flood-vX.Y-YYYYMMDD.tar.gz`.

## v3.2 — 2026-09-02 (tag `rasuwa-flood-v3.2-20260902`)

Reroute attribution and route comparison:

- `/route?reroute_details=true` (with incidents active) now runs a second,
  incident-free baseline route and returns per-incident attribution on
  `paths[0]`: `reroutes[]` (`incident_id`, `type`, `description`, `avoided`,
  `detour`) and the full `baseline` LineString. Geometry diffing is done in the
  wrapper with shapely — the Java fork stays unmodified.
- Dashboard draws the **incident-free baseline in red underneath** and the
  **incidents-applied route in blue on top** (white casing), so overlapping
  stretches read as a single blue line and red shows only where the route
  actually diverges.
- A **route key legend** ("Blocked route (without incidents)" / "Alternate
  route (with incidents)") plus per-incident reroute rows with extra distance
  appears under the summary; hidden when nothing diverges so red is never shown
  misleadingly.
- **Marker fix:** waypoint markers stretched across the full map width because
  a class overwrite dropped MapLibre's `maplibregl-marker` (which provides
  absolute positioning). Markers keep that class and append the role class.

Incidents panel:

- New optional **`source`** field on incidents (may be blank): SQLite column
  with automatic `ALTER TABLE` migration for existing databases, API
  create/update support, inputs in both the record and edit modals, and display
  in the list cards and map popups.
- Incidents panel widened **290 → 370 px**.
- **Data disclaimer** at the top of the panel: incident information is
  collected from various sources and may not be up to date; users are invited
  to report updates via the Baato Facebook / Instagram pages.

Earlier work included in this round: incident text + type editing with
"Updated …" timestamps, right-click context-menu labels (origin / stop /
destination), pill-shaped markers, geocode fly-to, and a Baato proxy regression
test for non-default ports.

## v3.1 — 2026-09-02 (tag `rasuwa-flood-v3.1-20260901`)

- Baato proxied tile URLs rewritten to **https** so the dashboard works behind a
  TLS reverse proxy; local (http) setups keep working.
- The key-bearing tile source is still rewritten to the local `/baato/api/…`
  proxy, which re-appends the key server-side — the key never reaches the
  browser.

## v3.0 — 2026-09-01 (tag `rasuwa-flood-v3-20260901`)

- **Login auth** for incident mutations: HMAC-signed bearer tokens
  (`POST /login`, `GET /auth/status`), dashboard login gate, read endpoints stay
  public.
- **Editable polygons**: drag vertices, insert on edge click, right-click to
  remove.
- Hillshade/label layering polish (hillshade under labels), basemap/layer
  control refinement.
- **User-added tile-layer UI removed** (add form, list, save locally).

## v2.0 — 2026-08-29 (export `rasuwa-flood-v2-20260829.tar.gz`)

- Containerized GraphHopper landmark fork + FastAPI wrapper sidecar with the
  incident database bind-mounted for persistence.
- Incident CRUD (`/incidents`) with per-request hard-block routing
  (`/route`, custom-model `in_<id>` → `multiply_by: 0`).
- Baato key-hiding proxy (style rewrite + tile proxy + two-hop geocoding).
- 3D MapLibre dashboard (terrain, basemap switcher, right-click multi-stop
  routing, incident drawing).
