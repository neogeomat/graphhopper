# AGENTS.md

## Build & Test

```bash
mvn clean install -DskipTests          # full build (rebuilds web fat-jar)
mvn clean test -pl core                # single module
mvn test -pl core -Dtest=GraphHopperTest   # single test class
mvn test -pl core -Dtest=GraphHopperTest#testWithQueryGraph  # single method
mvn checkstyle:check                   # lint (line length 500)
mvn verify -B && mvn checkstyle:check forbiddenapis:check -B  # CI suite
```

Java 25, Maven multi-module (10 modules). Core is `graphhopper-core`.

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

This fork adds a `has_landmark` boolean encoded value that flags edges with nearby POI nodes, and a `landmark_name` string encoded value that stores the name (or type) of the nearest landmark.

### How it works

1. **`WaySegmentParser`** calls a `landmarkNodeConsumer` for every OSM node with landmark-relevant tags (`amenity`, `tourism`, `historic`, `leisure`, `shop`, `public_transport`, `natural`, `man_made`), even if the node is not on any accepted way.
2. **`OSMReader`** feeds these nodes into a **`LandmarkNodeIndex`** (grid-based spatial index, ~100m cells).
3. During edge creation, **`OSMReader.setArtificialWayTags()`** queries the index (100m radius) and sets a `"nearby_landmarks"` tag on the way.
4. **`LandmarkParser`** (a `TagParser`) reads both `node_tags` (on-way nodes) and `nearby_landmarks` (off-way nodes within 100m) and sets `has_landmark` and optionally `landmark_name` on the edge.

### Key files

| File | Role |
|------|------|
| `.../ev/HasLandmark.java` | Boolean encoded value, key `"has_landmark"` |
| `.../ev/LandmarkName.java` | String encoded value, key `"landmark_name"` (512 chars max) |
| `.../parsers/LandmarkParser.java` | TagParser that sets both encoded values |
| `.../parsers/LandmarkNodeIndex.java` | Grid-based spatial index with radius query |
| `.../osm/OSMReader.java` | Wires collection + query (search radius hardcoded at 100m, line 160) |
| `.../osm/WaySegmentParser.java` | Has `landmarkNodeConsumer` + builder method |
| `.../ev/DefaultImportRegistry.java` | Registers the import unit |

### Activation

Add to config (note: YAML multiline string `|`, add to the existing list):
```yaml
graph.encoded_values: |
  has_landmark, landmark_name, car_access, car_average_speed, country, road_class, roundabout, max_speed, road_environment,
  foot_access, foot_average_speed, foot_priority, foot_road_access, hike_rating, average_slope,
  bike_access, bike_average_speed, bike_priority, bike_road_access, bike_network, mtb_rating, ferry_speed
```

The `INCLUDE_IF_NODE_TAGS` set in `WaySegmentParser.java:63` controls which node keys survive OSM import. Landmark keys were added alongside `barrier`, `highway`, `railway`, etc.

### Verification & usage

1. **Rebuild** after any code changes: `mvn clean install -DskipTests`
2. **Delete old graph cache** (`graph-cache/` or whatever `graph.location` points to)
3. **Start server** — import runs automatically if no cache exists
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

### To extend

- **Add more OSM keys**: edit `LandmarkNodeIndex.LANDMARK_KEYS`
- **Change search radius**: edit `new LandmarkNodeIndex(100)` in OSMReader.java line 160
- **Store more detail**: replace `boolean` with `StringEncodedValue` in `HasLandmark.java`

## Architecture notes

- OSM import is two-pass: Pass 1 scans ways (records junctions), Pass 2 processes nodes then ways. `TagParser.handleWayTags()` runs per edge during Pass 2.
- `ReaderWay` gets artificial tags (`node_tags`, `edge_distance`, `point_list`, `nearby_landmarks`) before parsers run.
- New `TagParser` + `EncodedValue` + `DefaultImportRegistry` entry = standard extension pattern.
- Test data files are in `core/files/` (small OSM extracts like `andorra.osm.pbf`, `monaco.osm.gz`).
- `config-example.yml` documents all profile, CH, LM, elevation settings.
