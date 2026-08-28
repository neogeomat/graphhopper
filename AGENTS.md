# Repository Guidelines

## Project Overview

GraphHopper 12.0-SNAPSHOT — a fast, memory-efficient OpenStreetMap routing engine (Java, Maven multi-module, 10 modules). Imports `.osm.pbf` files into a custom binary graph (`graph-cache/`), then serves REST routing via a Dropwizard web app (web fat-jar). Core: `graphhopper-core`.

**This fork adds a landmark detection feature**: a `has_landmark` boolean encoded value flagging edges with nearby POI nodes and a `landmark_name` string encoded value storing the nearest landmark's name. Landmark names surface per-edge in route `details` and in turn-instruction `text` ("… near \<landmark\>").

Do NOT confuse the fork's landmark feature with upstream **A\* landmark preprocessing** (`core/.../routing/lm/*`, `docs/core/landmarks.md`, `profiles_lm` in config) — that is hybrid-mode routing acceleration, unrelated to POI landmarks.

## Architecture & Data Flow

**Request flow**: HTTP → `RouteResource` (JAX-RS, `web-bundle/.../resources/RouteResource.java`) → `GHRequest` → `Router` (`core/.../routing/Router.java`) → solver (CH / LM / flexible, selected in `createSolver`) → `Weighting` from `CustomModelParser` (Janino-compiled) → Dijkstra/A* on a `QueryGraph` → `ResponsePath` → JSON/GPX.

**OSM import (two-pass)** — `OSMReader` + `WaySegmentParser` (`core/.../reader/osm/`):
1. Pass 1 scans ways, records junctions.
2. Pass 2 processes nodes then ways. `ReaderWay` gets artificial tags (`node_tags`, `nearby_landmarks`, `edge_distance`, `point_list`) before `OSMParsers` dispatches each edge's tags to every registered `TagParser.handleWayTags()`.
3. `TagParser`s write `EncodedValue`s; encoded values are registered via `ImportUnit`s in `DefaultImportRegistry` (`core/.../routing/ev/`).

**Landmark data flow**: `WaySegmentParser` feeds off-way POI nodes to `LandmarkNodeIndex` (grid index, ~100m cells) via `landmarkNodeConsumer` → `OSMReader.setArtificialWayTags()` queries the index (100m radius) and sets the `nearby_landmarks` tag → `LandmarkParser` (a `TagParser`) reads `node_tags` + `nearby_landmarks`, sets `has_landmark` and `landmark_name`. On routing, `InstructionsFromEdges` copies `landmark_name` onto instruction extra info and `Instruction.getTurnDescription()` appends it via the `near_landmark` i18n key.

**Graph cache validation**: `GraphHopper.load()` compares stored vs configured profile hashes (`Profile.getVersion()` = hash of name + turn_costs + weighting + hints, which includes the custom model). Changing a profile's `custom_model_files` or `config.yml` profile settings → `Profile 'car' does not match` → must delete `graph-cache/` and re-import. The encoded-values string (`graph.encoded_values`) is also persisted (`EncodingManager.fromProperties`). Query-time custom models do NOT affect the hash — no re-import needed.

## Key Directories

| Path | Purpose |
|---|---|
| `core/` | Engine: import (`reader/osm/`), routing (`routing/` incl. `routing/ev/` encoded values, `routing/util/parsers/` tag parsers, `routing/weighting/custom/`), storage (`storage/` BaseGraph), `GraphHopper.java` facade |
| `web-bundle/` | Dropwizard bundle + JAX-RS resources (`resources/`), `http/GraphHopperBundle.java` DI wiring |
| `web/` | Fat-jar app: `application/GraphHopperApplication.java` main, `application/cli/ImportCommand.java`, serves `/maps/` UI |
| `web-api/` | Shared API types: `GHRequest`/`GHResponse`, `CustomModel`, `Instruction`, `PMap`, `JsonFeature`, `json/Statement.java` |
| `tools/` | `Measurement` CLI benchmark (shaded jar, manifest main) |
| `navigation/` | `/navigate` turn-by-turn web service for Maplibre Navigation SDK / ferrostar |
| `map-matching/` | GPX-to-road snapping (HMM/Viterbi), `/match` endpoint |
| `reader-gtfs/` | Public transit (GTFS + OSM walk network) |
| `client-hc/` | Hand-crafted Java/Android HTTP client for Directions API |
| `example/` | Usage examples (`RoutingExample`, `LowLevelAPIExample`, …) |
| `incident-wrapper/` | Python FastAPI sidecar (NOT part of the Java build): `/incidents` CRUD + `/route` proxy that adds `custom_model` and applies incidents |

## Development Commands

```bash
mvn clean install -DskipTests          # full build (rebuilds web fat-jar; REQUIRED before web/web-bundle tests)
mvn clean test -pl core                # module-scoped
mvn test -pl web -Dtest=RouteResourceTest -am   # single class, -am builds upstream modules
mvn test -pl core -Dtest=GraphHopperTest#testMonacoDifferentAlgorithms   # single method
mvn verify -pl reader-gtfs             # integration tests (failsafe, only reader-gtfs has *IT)
mvn clean test verify                  # CONTRIBUTING.md PR requirement
mvn checkstyle:check                   # lint; NOT bound to lifecycle, NOT in CI (line length 500)
mvn forbiddenapis:check                # deprecated-API lint; NOT in CI
```

CI (`.github/workflows/build.yml`) runs only `mvn -B clean test` on Java 26 + 27-ea (temurin). Java 25 compile target (`<release>25</release>`).

**Run the server**:
```bash
java -Ddw.graphhopper.datareader.file=Nepal_data.v07172026.osm.pbf -jar web/target/graphhopper-web-12.0-SNAPSHOT.jar server config.yml
```
Import runs automatically if `graph-cache/` is missing; ports 8989 (app) / 8990 (admin). Dropwizard `-Ddw.<yaml.path>=<value>` overrides any config key. Stop via PID (`pgrep -f 'graphhopper-web-12.0.SNAPSHOT.jar'` then `kill <pid>`) — `pkill -f graphhopper-web-12.0-SNAPSHOT.jar` also matches the launching shell and kills it.

**Docker** (`Dockerfile` + `docker-compose.yml`): `docker compose up -d` builds a multi-stage image (Maven → `eclipse-temurin:25-jre`, ~577MB) and serves on 8989/8990, bind-mounting `./graph-cache` (persists, no re-import) and the PBF read-only. The entrypoint republishes the connectors on 0.0.0.0 with **snake_case** Dropwizard overrides (`-Ddw.server.application_connectors[0].bind_host=0.0.0.0`) — camelCase override keys fail with `node with index not found`.

## Code Conventions & Common Patterns

- **Error handling**: `IllegalArgumentException` with actionable messages (e.g. Router.java: `"The \`block_area\` parameter is no longer supported. Use a custom model with \`areas\` instead."`). No checked exceptions in routing paths; invalid requests surface as 400s with a `message` + `hints[]`.
- **Naming**: `*EncodedValue` for encoded values (`HasLandmark`, `LandmarkName`), `*Parser` for `TagParser`s, `*Resource` for JAX-RS endpoints, builder-style fluent setters (`profile.setCustomModel(cm)`, `GHRequest#setPoints(...).setProfile(...)`).
- **Dependency injection**: Dropwizard Jersey — resources registered in `GraphHopperBundle` / `GraphHopperApplication.run()`, constructor `@Inject` with `@Named("hasElevation")`-style qualifiers.
- **Hints/params**: `PMap` (web-api) for all request hints; `Profile.getHints()` also a PMap. Statements are `record`s (`web-api/.../json/Statement.java`) with `If`/`Else`/`LIMIT`/`MULTIPLY` factories.
- **Java features**: modern — records, switch expressions (`case X ->`), `List.of`, sealed-ish typing via interfaces. 4-space indent, ~100-col, Unix line endings.
- **Logging**: slf4j `LoggerFactory.getLogger(X.class)`; import progress/info at INFO, tests set `com.graphhopper` to warn via `core/src/test/resources/logback-test.xml`.
- **Custom model parsing specifics** (fork quirk): areas are referenced as bare identifiers `in_<areaId>` (e.g. `in_block`) — the newer `in_area('x')` syntax is NOT supported and fails with `Cannot compile expression` (`ConditionalExpressionVisitor.java:64`). Conditions are whitelisted (no method calls except `edge.*`, `Math.*`, `country.*`), compiled with Janino at request time. `CustomModel.merge(baseModel, queryModel)` appends query statements AFTER profile statements — profile `multiply_by: 0` blocks always win over query overrides.
- **Convention**: reuse existing patterns — a second convention beside an existing one is prohibited.

## Important Files

| File | Role |
|---|---|
| `config.yml` (gitignored, on disk) | Fork's server config: `datareader.file` (**points at `Nepal_data.v07172026.osmf.pbf`, actual file is `.osm.pbf`** — start with the `-Ddw.graphhopper.datareader.file=` override), `graph.location: graph-cache`, profiles car/foot/bike with `custom_model_files`, `graph.encoded_values` (starts `has_landmark, landmark_name, ...`) |
| `core/.../routing/ev/HasLandmark.java`, `LandmarkName.java` | Fork's encoded values (keys `"has_landmark"`, `"landmark_name"`; string cap `1_000_000`) |
| `core/.../routing/util/parsers/LandmarkParser.java`, `LandmarkNodeIndex.java` | Fork's tag parser + grid index (search radius hardcoded 100m in `OSMReader.java:159,316`) |
| `core/.../reader/osm/OSMReader.java`, `WaySegmentParser.java` | Import pipeline; landmark wiring (`landmarkNodeConsumer`, `INCLUDE_IF_NODE_TAGS` set, lines 63-64) |
| `core/.../routing/ev/DefaultImportRegistry.java` | `ImportUnit` registration (landmark pair at lines 346-356) |
| `core/.../routing/InstructionsFromEdges.java` + `web-api/.../util/Instruction.java` | Landmark → instruction text (`near_landmark` key, en_US.txt: `%1$s near %2$s`) |
| `core/src/main/resources/com/graphhopper/custom_models/*.json` | Built-in custom models (`car.json`, `foot.json`, `bike.json`); resolution: jar resource first, then `custom_models.directory` (or working dir). Name collisions with built-ins are errors |
| `web/src/main/java/com/graphhopper/application/GraphHopperApplication.java` | Main class (IntelliJ run config: main `com.graphhopper.application.GraphHopperApplication`, args `server config.yml`) |

**API facts**: GET `/route` has no `custom_model` param in this fork — custom models are POST-body only. POST body uses **[lon, lat]** point order (GET query uses lat,lon). `block_area` param is removed (Router.java rejects it). Details (`has_landmark`, `landmark_name`) require explicit `details=` params. Per-request blocking = POST with `custom_model` + `areas` polygon (`in_<id> → multiply_by 0`) — no re-import.

## Incident & custom-model wrapper (Python sidecar)

`incident-wrapper/` is a FastAPI service that runs in front of GraphHopper and keeps the Java fork unmodified:

- `/incidents` — CRUD for road closures (SQLite `incident-wrapper/incidents.db`; env `INCIDENTS_DB`). Body: `{type, description, active, coordinates}` where `coordinates` is a GeoJSON polygon ring of `[lon, lat]` pairs (auto-closed).
- `/route` (GET + POST) — proxy that accepts a `custom_model` parameter (the fork's plain GET `/route` can't) and injects every **active** incident as a blocked area: `priority: [{if: in_<id>, multiply_by: "0"}]`. A priority of 0 → infinite edge weight → hard block (`CustomWeighting#calcEdgeWeight`).
- `/`, `/map`, `/route-ui` — single-page **MapLibre GL 5.24.0** dashboard (`static/map.html` + `static/dashboard.js`, served via a `StaticFiles` mount at `/static`). **No tabs** — three separate surfaces: **Incidents** = left panel (`#panel-incidents`, hand-rolled polygon draw, no Leaflet.draw, data-driven fill colours by type), **Routing** = right panel (`#panel-routing`, click/drag origin + destination, route re-fetches automatically on any change, debounced 300ms with a request-sequence guard, no map re-fit on auto-updates; `#result` summary + instructions render inside this panel), **Layers** = the bottom-left map control (`#layers-content` is authored in the HTML then relocated into `BasemapSwitcher.onAdd` so every id/handler keeps working — terrain controls, basemap list, Baato key, added layers, add-layer form). Each panel collapses via `togglePanel(which)`; MapLibre's own controls are on `bottom-right`. `.panel` uses `max-height: calc(100% - 80px)` and `.maplibregl-ctrl-bottom-left` gets `z-index: 8` so a long incident list can never cover or intercept clicks on the Layers control.
- **Incident → route coupling**: every incidents-layer mutation (`saveIncident`, `toggleIncident`, `deleteIncident`) calls `loadIncidents()` then `scheduleRoute(0)`, so the displayed route always reflects the current blocks. When a route request fails, `runRoute()` clears the route source, summary and instructions, then raises the **alert box** (`#alertbox`, z-index 30) via `showAlert()`; `routeFailureMessage()` humanises GraphHopper's error (`Connection between locations not found` → "No route could be found between A and B") and, when `apply_incidents` is on with active incidents, appends the hint that a hard block may be cutting the only path. Identical consecutive failures do not stack (`lastAlertMsg`), and a successful route calls `closeAlert()`. **Testing note**: a blocking polygon must actually intersect the road — a ±0.0016° box (~175 m) at the corridor midpoint does *not* block, ±0.006° (~660 m) does. Also `queryRenderedFeatures`/`querySourceFeatures` undercount under pitch/terrain, so verify rendering with a screenshot pixel/diff check rather than feature counts.
- **3D terrain**: Mapterhorn `https://tiles.mapterhorn.com/{z}/{x}/{y}.webp`, `raster-dem`, `encoding: terrarium`, `tileSize: 512`, **`maxzoom: 12`** (z13+ 404s — do not raise it), CORS `*`. Exposed via `map.setTerrain({source, exaggeration})` plus a hillshade layer on a second identical source. **Leaflet cannot render terrain** — that is why this UI is MapLibre, not Leaflet.
- **Basemaps**: default is **Baato Breeze** (vector style, needs `BAATO_KEY` env var — exposed to the page via `GET /config`, overridable from the Layers control into `localStorage`); falls back to Esri World Imagery with a visible notice when the key is missing/rejected. Raster presets (Esri World Imagery, OSM, OpenTopoMap) swap only the `basemap` source; vector styles (Baato Breeze, OpenFreeMap Liberty) replace the whole style via `rebuildStyle()`, which re-applies terrain, hillshade, overlays, incidents and the live route. **Detach terrain (`setTerrain(null)`) before `setStyle()`** — otherwise MapLibre throws `cannot read properties of undefined (reading 'shaderPreludeCode')`. An on-map layers control sits **bottom-left**; it must be registered inside `map.on('load')` because `BasemapSwitcher.prototype.onAdd` is assigned later in the file (function declarations hoist, prototype assignments do not).

Run: `cd incident-wrapper && ./run.sh` (bootstraps `.venv`, uvicorn on :8000, docs at `/docs`, dashboard at `/`). Env: `GRAPHOPPER_URL` (default `http://localhost:8989`), `INCIDENTS_DB`, `PORT`. GET points are `lat,lon`; POST accepts GraphHopper's `[lon,lat]` body verbatim. `apply_incidents=false` opts out per request. A user-supplied `custom_model` is forwarded verbatim, so its `areas` must be valid **closed** GeoJSON rings (open rings fail with `Unable to process JSON`).

## Runtime/Tooling Preferences

- **Java 25+** required (release 25 target; CI tests 26/27-ea). Maven multi-module; run per-module with `-pl ... -am` to avoid full builds.
- **No package manager beyond Maven**; the `/maps/` web UI is a prebuilt npm artifact unzipped into `web-bundle/target/classes` by Maven (source not in repo) — it renders only instruction `text`/`street_name`, ignoring extra info like `landmark_name`.
- **Gitignored**: `graph-cache/`, `/config.yml` (fork's config is on disk but uncommitted), `*.pbf`, `logs/`.
- **Git status noise**: ~1324 files show "modified" in `git status`, but they are all file-mode-only changes (`100644 → 100755`, executable bit set globally on this filesystem) — no content changed. Find real edits with `git diff --numstat` (nonzero `+`/`-` rows) or `git diff --summary` (the `mode change` lines are the noise).
- **Translations**: `core/src/main/resources/com/graphhopper/util/*.txt` generated from a Google Spreadsheet via `./core/files/update-translations.sh`; missing keys auto-fill from `en_US.txt` (`TranslationMap.postImportHook`), so adding a key only to `en_US.txt` suffices. Adding a new language requires touching both `TranslationMap.LOCALES` and the script's language list.
- **Stale fat-jar gotcha**: `mvn -pl core` builds do NOT rebuild `web/target/graphhopper-web-*.jar` — a stale jar causes NPEs in `StringDetails` after source changes; run `mvn clean install -DskipTests` (full reactor) and restart.

## Testing & QA

- **JUnit Jupiter 6.0.2** (BOM), plain `org.junit.jupiter.api.Assertions` everywhere in core/web (AssertJ only in reader-gtfs; Mockito declared but unused — hand-build fixtures instead). Hamcrest only in web tests (web/pom.xml pins hamcrest **1.3**, overriding parent's 3.0). Surefire 3.5.4 with global argLine `-Duser.language=en` (tests assert English strings); failsafe 3.5.4 for `*IT` (reader-gtfs only).
- **Fork's landmark tests**: `core/src/test/.../routing/util/parsers/LandmarkParserTest.java` (5 tests; fakes `node_tags`/`nearby_landmarks` then `handleWayTags`). No tests cover `LandmarkNodeIndex`, instruction extra-info, or `near_landmark` text. `GraphHopperLandmarksTest` (web) is upstream A\* landmarks — unrelated.
- **Test data**: `core/files/` (`andorra.osm.pbf`, `monaco.osm.gz`, `belarus-east.osm.gz`, …) referenced by relative path `"../core/files/..."` from module cwd (not classpath). GTFS feeds in `reader-gtfs/files/`. Temp graphs under `target/`, wiped in `@BeforeAll/@AfterAll`.
- **Fixtures**: no `AbstractRoutingAlgorithmTester` — use the `Fixture` + `@ParameterizedTest @ArgumentsSource(FixtureProvider.class)` pattern (`RoutingAlgorithmTest.java:209-241`); helpers `com.graphhopper.routing.TestProfiles` (main source), `GHUtility.comparePaths`, `web/src/test/.../resources/Util.java` (`getWithStatus`/`postWithStatus`).
- **Run**: `mvn test -pl core -Dtest=LandmarkParserTest`; web tests boot real Dropwizard servers on random ports and re-import `andorra.osm.pbf` per class — `mvn test -pl web` is the slowest module.
- **Coverage**: no jacoco/coverage plugin, no coverage gate. Tests are behavior contracts (exact distances/times/instructions on tiny hand-built graphs, tolerance assertions on real extracts). 19 `@Disabled` tests (network-dependent DEM providers).
