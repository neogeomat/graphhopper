# GraphHopper Routing Engine

## Get Started
```bash
java -Ddw.graphhopper.datareader.file=ktm.osm.pbf -jar web/target/graphhopper-web-*.jar server config.yml
```
Web UI: http://localhost:8989
Tested Route API: 
add &details=landmark_name

## Building
```bash
mvn clean install -DskipTests
```

## GraphHopper Maps

The GraphHopper routing server uses GraphHopper Maps as web interface, which is also [open source](https://github.com/graphhopper/graphhopper-maps).

To see GraphHopper Maps in action go to [graphhopper.com/maps/](https://graphhopper.com/maps/),
which is an instance of GraphHopper Maps and available for free, via encrypted connections and from German servers - for a nice and private route planning experience!

[![GraphHopper Maps](https://www.graphhopper.com/wp-content/uploads/2026/05/graphhopper-maps.png)](https://graphhopper.com/maps)

## GraphHopper Directions API

The GraphHopper Directions API is [our](https://www.graphhopper.com/) commercial offering that provides
[multiple APIs](https://docs.graphhopper.com) based on this open source routing engine: the Routing API, the Matrix API, the Isochrone API and the Map Matching API.

It also provides the Route Optimization API, which is based on our open source [jsprit project](http://jsprit.github.io/) and uses the fast Matrix API behind the scenes.

The address search is based on the open source [photon project](https://github.com/komoot/photon), which is supported by GraphHopper GmbH.

## Public Transit

[Get started](./reader-gtfs/README.md#quick-start)

[![Realtime Demo](https://www.graphhopper.com/wp-content/uploads/2018/05/Screen-Shot-2018-05-16-at-21.23.25-600x538.png)](./reader-gtfs/README.md#quick-start)

## Mobile Apps

### Online

There is the [/navigate web service](./navigation) that can be consumed by [the Maplibre Navigation SDK](https://github.com/maplibre/maplibre-navigation-android) or [the ferrostar SDK](https://github.com/stadiamaps/ferrostar).

[<img src="https://raw.githubusercontent.com/maplibre/maplibre-navigation-android/main/.github/preview.png" width="400">](https://github.com/graphhopper/graphhopper-navigation-example)

### Offline

Offline routing is [no longer officially supported](https://github.com/graphhopper/graphhopper/issues/1940)
but should still work as Android supports most of Java. See [version 1.0](https://github.com/graphhopper/graphhopper/blob/1.0/docs/android/index.md)
with the Android demo and also see [this pull request](http://github.com/graphhopper/graphhopper-ios) of the iOS fork including a demo for iOS.

[<img src="https://www.graphhopper.com/wp-content/uploads/2016/10/android-demo-screenshot-2.png" width="600">](./android/README.md)

## Analysis

Use isochrones to calculate and visualize the reachable area for a certain travel mode.

You can try the debug user interface at http://localhost:8989/maps/isochrone/ to see the `/isochrone` and `/spt` endpoint in action.

### [Isochrone Web API](./docs/web/api-doc.md#isochrone)

[![Isochrone API image](./docs/isochrone/images/isochrone.png)](./docs/web/api-doc.md#isochrone)

### [Shortest Path Tree API](//www.graphhopper.com/blog/2018/07/04/high-precision-reachability/)

[![high precision reachability image](https://www.graphhopper.com/wp-content/uploads/2018/06/berlin-reachability-768x401.png)](https://www.graphhopper.com/blog/2018/07/04/high-precision-reachability/)

### [Map Matching](./map-matching)

There is the map matching subproject to snap GPX traces to the road.

[![map-matching-example](https://raw.githubusercontent.com/graphhopper/directions-api-doc/master/web/img/map-matching-example.gif)](./map-matching)


# Technical Overview

GraphHopper supports several routing algorithms, such as 
<a href="https://en.wikipedia.org/wiki/Dijkstra%27s_algorithm">Dijkstra</a> and 
<a href="https://en.wikipedia.org/wiki/A*_search_algorithm">A</a>`*` and its bidirectional variants. 
Furthermore, it allows you to use 
<a href="https://en.wikipedia.org/wiki/Contraction_hierarchies">Contraction Hierarchies</a> (CH) 
very easily. We call this **speed mode**; without this CH preparation, we call it **flexible mode**.

The speed mode comes with very fast and lightweight (less RAM) responses and it does not use heuristics. 
However, only predefined vehicle profiles are possible and this additional CH preparation is time and resource consuming.

Then there is the **hybrid mode** which also requires more time and memory for the preparation,
but it is much more flexible regarding changing properties per request or e.g. integrating traffic data. 
Furthermore, this hybrid mode is slower than the speed mode, but it is an 
order of magnitude faster than the flexible mode and uses less RAM for one request.

If the preparations exist you can switch between all modes at request time.

Read more about the technical details [here](./docs/core/technical.md).

## License

We chose the Apache License to make it easy for you to embed GraphHopper in your products, even closed source.
We suggest that you contribute back your changes, as GraphHopper evolves fast.

## OpenStreetMap Support

OpenStreetMap is directly supported by GraphHopper. Without the amazing data from
OpenStreetMap, GraphHopper wouldn't be possible at all. 
Other map data will need a custom import procedure, see e.g. <a href="https://github.com/graphhopper/graphhopper/issues/277">Ordnance Survey</a>,
<a href="https://github.com/graphhopper/graphhopper-reader-shp">Shapefile like ESRI</a> or <a href="https://github.com/OPTITOOL/morituri">Navteq</a>.

## Written in Java

GraphHopper is written in Java and officially runs on Linux, Mac OS X and Windows.

### Maven

Embed GraphHopper with OpenStreetMap support into your Java application via the following snippet:

```xml
<dependency>
    <groupId>com.graphhopper</groupId>
    <artifactId>graphhopper-core</artifactId>
    <version>[LATEST-VERSION]</version>
</dependency>
```

See [our example application](./example/src/main/java/com/graphhopper/example/RoutingExample.java) to get started fast.

## Customizable

You can customize GraphHopper with Java knowledge (with a high and low level API) and also without Java knowledge using the [custom models](./docs/core/custom-models.md).

### Web API

With the web module, we provide code to query GraphHopper over HTTP and decrease bandwidth usage as much as possible.
For that we use an efficient polyline encoding, the Ramer–Douglas–Peucker algorithm, and a simple 
GZIP servlet filter.                 

On the client side, we provide a [Java](./client-hc) and [JavaScript](https://github.com/graphhopper/directions-api-js-client)
client.

### Desktop

GraphHopper also runs on the Desktop in a Java application without internet access. For debugging
purposes GraphHopper can produce vector tiles, i.e. a visualization of the road network in the
browser (see #1572). Also a more low level Swing-based UI is provided via MiniGraphUI in the
tools module, see some visualizations done with it [here](https://graphhopper.com/blog/2016/01/19/alternative-roads-to-rome/).
A fast and production-ready map visualization for the Desktop can be implemented via [mapsforge](https://github.com/mapsforge/mapsforge) or [mapsforge vtm](https://github.com/mapsforge/vtm).

# Features

 * Works out of the box with OpenStreetMap (osm/xml and pbf) and can be adapted to custom data
 * OpenStreetMap integration: stores and considers road type, speed limit, the surface, barriers, access restrictions, ferries, conditional access restrictions and more
 * GraphHopper is fast. And with the so called "Contraction Hierarchies" it can be even faster (enabled by default).
 * Memory efficient data structures, algorithms and [the low and high level API](./docs/core/low-level-api.md) is tuned towards ease of use and efficiency
 * Pre-built routing profiles: car, bike, racing bike, mountain bike, foot, hike, truck, bus, motorcycle, ...
 * [Customization of these profiles](./docs/core/profiles.md#custom-profiles) are possible. Read about it [here](https://www.graphhopper.com/blog/2020/05/31/examples-for-customizable-routing/).
 * Provides a powerful [web API](./docs/web/api-doc.md) that exposes the data from OpenStreetMap and allows customizing the vehicle profiles per request. With JavaScript and Java clients.
 * Provides [map matching](./map-matching) i.e. "snap to road".
 * Supports time-dependent public transit routing and reading [GTFS](./reader-gtfs/README.md).
 * Offers turn instructions in more than 45 languages. Contribute or improve [here](./docs/core/translations.md).
 * Displays and takes into account [elevation data](./docs/core/elevation.md).
 * Supports [alternative routes](https://discuss.graphhopper.com/t/alternative-routes/424).
 * Supports [turn costs and restrictions](./docs/core/turn-restrictions.md).
 * Offers country-specific routing via country rules.
 * Allows customizing routing behavior using custom areas.
 * Scales from small indoor-sized to world-wide-sized graphs.
 * Finds nearest point on street e.g. to get elevation or 'snap to road' or being used as spatial index (see [#1485](https://github.com/graphhopper/graphhopper/pull/1485)).
 * Calculates isochrones and [shortest path trees](https://github.com/graphhopper/graphhopper/pull/1577).
 * Shows the whole road network in the browser for debugging purposes ("vector tile support"), see [#1572](https://github.com/graphhopper/graphhopper/pull/1572).
 * Shows so called "path details" along a route like road_class or max_speed, see [#1142](https://github.com/graphhopper/graphhopper/pull/1142) or the web documentation.
 * Written in Java and simple to start for developers via Maven.
