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

> **This fork is the routing *engine* only.** The FastAPI `incident-wrapper` sidecar and the combined two-service deployment are NOT part of this repo — they moved to their own repos on 2026-09-02 (see below). Do not add wrapper code here.

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

**Docker** (`Dockerfile` + this repo's `docker-compose.yml`): `docker compose up -d` runs the **engine only** (the fork's own compose is a single `graphhopper` service). It builds the multi-stage image (Maven → `eclipse-temurin:25-jre`, ~577MB) on 8989/8990, bind-mounting `./graph-cache` (persists, no re-import) and the PBF read-only; its healthcheck is `bash` + `/dev/tcp` because the JRE image has **no curl or wget**, with `start_period: 300s` for the cold graph load. The GraphHopper entrypoint republishes the connectors on 0.0.0.0 with **snake_case** Dropwizard overrides (`-Ddw.server.application_connectors[0].bind_host=0.0.0.0`) — camelCase override keys fail with `node with index not found`. (The wrapper sidecar and the combined two-service `graphhopper`+`wrapper` deploy are separate repos — see "Related repos" below.)

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

## Related repos (product split 2026-09-02)

This fork is the **routing engine** piece of the larger Rasuwa Flood dynamic routing system. Related code lives in separate repos:

- **`neogeomat/incident-wrapper`** — the FastAPI `incident-wrapper` sidecar (road-incident CRUD + the `/route` custom-model proxy + the MapLibre dashboard). It keeps this Java fork unmodified by injecting incidents as blocked `custom_model` areas. All incident/route-proxy/baato-key/dashboard work happens there; its `AGENTS.md` and `README.md` are authoritative.
- **`rasuwa-flood-export`** (`main`) — deployment glue: the **combined two-service** `docker-compose.yml` (`graphhopper` + `wrapper`), `assemble.sh`, `start.sh`, and the release tarball. This repo does not ship a wrapper.

Engine release docs: see `docs/reproduction.md` (split-built bundle guide, points at both repos).

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
