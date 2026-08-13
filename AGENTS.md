# AGENTS.md

## Build & Test

```bash
mvn clean install -DskipTests          # full build (rebuilds web fat-jar)
mvn clean test -pl core                # single module
mvn test -pl core -Dtest=GraphHopperTest   # single test class
mvn test -pl core -Dtest=GraphHopperTest#testWithQueryGraph  # single method
mvn checkstyle:check                   # lint (line length 500, core/files/checkstyle.xml)
mvn forbiddenapis:check                # deprecation lint
mvn clean test verify                  # CONTRIBUTING.md requirement for PRs
```

CI (`.github/workflows/build.yml`) runs only `mvn -B clean test` on Java 26 + 27-ea; checkstyle/forbiddenapis are not in CI. Java 25 compile target (pom.xml), Maven multi-module (10 modules). Core is `graphhopper-core`.

## Module quick-map

| Module | Purpose |
|--------|---------|
| `core` | Engine, OSM import, routing algorithms, graph storage |
| `web-bundle` | Dropwizard bundle, REST resources (`RouteResource`, etc.) |
| `web` | Fat-jar with `GraphHopperApplication` main class |
| `web-api` | Shared API types (`GHRequest`, `GHResponse`) |
| `tools` | CLI benchmarking (`Measurement`) |
| `navigation` | Turn-by-turn service |
| `map-matching` | GPX-to-road snapping |
| `reader-gtfs` | Public transit |
| `client-hc` | Java HTTP client for Directions API |
| `example` | Usage examples (`RoutingExample`, etc.) |

## Custom landmark detection feature

This fork adds a `has_landmark` boolean encoded value that flags edges with nearby POI nodes, and a `landmark_name` string encoded value that stores the name (or type) of the nearest landmark. Landmark names surface in two places: per-edge path `details`, and turn-instruction `text` (as "… near <landmark>").

### How it works

1. **`WaySegmentParser`** calls a `landmarkNodeConsumer` for every OSM node with landmark-relevant tags (`amenity`, `tourism`, `historic`, `leisure`, `shop`, `public_transport`, `natural`, `man_made`) that is **not** on any accepted way. Landmark nodes that *are* on a way flow through the normal `node_tags` artificial tag instead.
2. **`OSMReader`** feeds these nodes into a **`LandmarkNodeIndex`** (grid-based spatial index, ~100m cells).
3. During edge creation, **`OSMReader.setArtificialWayTags()`** queries the index (100m radius) and sets a `"nearby_landmarks"` tag on the way.
4. **`LandmarkParser`** (a `TagParser`) reads both `node_tags` (on-way nodes) and `nearby_landmarks` (off-way nodes within 100m) and sets `has_landmark` and optionally `landmark_name` on the edge.
5. **`InstructionsFromEdges`** copies `landmark_name` onto each turn instruction's extra info, and **`Instruction.getTurnDescription()`** appends it to the instruction `text` via the `near_landmark` translation key (`… near <landmark>`).

### Key files

| File | Role |
|------|------|
| `core/.../routing/ev/HasLandmark.java` | Boolean encoded value, key `"has_landmark"` |
| `core/.../routing/ev/LandmarkName.java` | String encoded value, key `"landmark_name"` (`1_000_000` unique values cap) |
| `core/.../routing/util/parsers/LandmarkParser.java` | TagParser that sets both encoded values |
| `core/.../routing/util/parsers/LandmarkNodeIndex.java` | Grid-based spatial index with radius query |
| `core/.../reader/osm/OSMReader.java` | Wires collection + query (search radius hardcoded at 100m, lines 159, 316) |
| `core/.../reader/osm/WaySegmentParser.java` | Has `landmarkNodeConsumer` + builder method |
| `core/.../routing/ev/DefaultImportRegistry.java` | Registers the import unit |
| `core/.../routing/InstructionsFromEdges.java` | Copies `landmark_name` onto instruction extra info (`Details.LANDMARK_NAME`) |
| `web-api/.../util/Instruction.java` | `getTurnDescription()` appends "near <landmark>" to text |
| `web-api/.../util/Parameters.java` | `Details.LANDMARK_NAME` constant |
| `core/.../resources/.../util/en_US.txt` | `near_landmark` translation key |

All landmark classes live under `com.graphhopper.routing.*` and `com.graphhopper.reader.osm` in the `core` module.

### Activation

This fork's `config.yml` already includes `has_landmark, landmark_name` first in `graph.encoded_values:`. To add to a fresh config:

```yaml
graph.encoded_values: |
  has_landmark, landmark_name, car_access, car_average_speed, country, road_class, roundabout, max_speed, road_environment,
  foot_access, foot_average_speed, foot_priority, foot_road_access, hike_rating, average_slope,
  bike_access, bike_average_speed, bike_priority, bike_road_access, bike_network, mtb_rating, ferry_speed
```

Note: `landmark_name` has no parser of its own — it is registered via `has_landmark`'s `ImportUnit` in `DefaultImportRegistry.java:346-354`. It is an output-only `StringEncodedValue` set by `LandmarkParser`.

The `INCLUDE_IF_NODE_TAGS` set in `WaySegmentParser.java:63-64` controls which node keys survive OSM import. Landmark keys were added alongside `barrier`, `highway`, `railway`, etc.

### Verification & usage

1. **Rebuild** after any code changes: `mvn clean install -DskipTests`
2. **Delete old graph cache** (`graph-cache/` or whatever `graph.location` points to)
3. **Start server** — import runs automatically if no cache exists
   ```bash
   java -jar web/target/graphhopper-web-*.jar server config.yml
   ```
   To use a different OSM file without editing config.yml: `java -Ddw.graphhopper.datareader.file=some.pbf -jar web/target/graphhopper-web-*.jar server config.yml`
4. **Check `/info`** shows both encoded values:
   ```bash
   curl http://localhost:8989/info | jq '.encoded_values | {has_landmark, landmark_name}'
   # → {"has_landmark": ["true", "false"], "landmark_name": ["text"]}
   ```
5. **Request them in route details** (required — not returned by default):
   ```bash
   curl "http://localhost:8989/route?point=...&point=...&profile=car&details=has_landmark&details=landmark_name"
   ```
   The `details` query parameter is how GraphHopper returns per-edge attributes. Without it, landmark data is stored on edges but omitted from responses.

6. **Landmarks in instruction text**: `landmark_name` is also folded into each turn instruction's `text` (e.g. `"Turn left onto X near My Choice Restaurant & Bar"`). Returned whenever `instructions=true`.

### Gotchas

- **`config.yml` points at a nonexistent PBF**: `datareader.file` is `Nepal_data.v07172026.osmf.pbf` but the file on disk is `Nepal_data.v07172026.osm.pbf`. Start with `-Ddw.graphhopper.datareader.file=Nepal_data.v07172026.osm.pbf ...` or the server throws "Your specified OSM file does not exist".
- **Stale fat-jar → NPE**: `web/target/graphhopper-web-*.jar` can lag the source (the `mvn -pl core` build does not rebuild it). A landmark route then fails with `NullPointerException ... String.equals ... because "val" is null` in `StringDetails.isEdgeDifferentToLastEdge`. Fix by `mvn clean install -DskipTests` (full reactor) and restart.
- **Killing the server**: `pkill -f graphhopper-web-12.0-SNAPSHOT.jar` also matches the launching shell's own command line and kills it (hangs the tool). Use the PID, e.g. `pgrep -f 'graphhopper-web-12.0.SNAPSHOT.jar'` then `kill <pid>`, or a pattern that doesn't match your own shell.

### To extend

- **Add more OSM keys**: edit `LandmarkNodeIndex.LANDMARK_KEYS`
- **Change search radius**: edit `new LandmarkNodeIndex(100)` in OSMReader.java line 159
- **Store more detail**: replace `boolean` with `StringEncodedValue` in `HasLandmark.java`

## Architecture notes

- OSM import is two-pass: Pass 1 scans ways (records junctions), Pass 2 processes nodes then ways. `TagParser.handleWayTags()` runs per edge during Pass 2.
- `ReaderWay` gets artificial tags (`node_tags`, `edge_distance`, `point_list`, `nearby_landmarks`) before parsers run.
- New `TagParser` + `EncodedValue` + `DefaultImportRegistry` entry = standard extension pattern.
- Test data files are in `core/files/` (small OSM extracts like `andorra.osm.pbf`, `monaco.osm.gz`).
- `config-example.yml` documents all profile, CH, LM, elevation settings.
- Java 25 compile target; CI matrix tests on Java 26 and 27-ea (`build.yml`).
- Checkstyle enforces 500-char lines; `.editorconfig` says 100 (IDE formatting, not enforced by CI).
- `config.yml` and `graph-cache/` are gitignored (this fork's `config.yml` exists on disk but is not committed).
- The web UI at `/maps/` is a **prebuilt** `@graphhopper/graphhopper-maps-bundle` npm artifact (downloaded + unzipped into `web-bundle/target/classes` by Maven at build time; source not in this repo). It renders only the instruction `text` and `street_name`/`sign` fields and **ignores extra info like `landmark_name`** — which is why landmarks are injected into `text` server-side.
- Translation `.txt` files under `core/src/main/resources/com/graphhopper/util/` are generated from a spreadsheet (`./core/files/update-translations.sh`); missing keys are auto-filled from `en_US.txt` by `TranslationMap.postImportHook`, so adding a key only to `en_US.txt` is enough.
