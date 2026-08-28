# syntax=docker/dockerfile:1

###############################################################################
# Build stage: compile the web fat-jar with Maven on JDK 25 (release target 25)
###############################################################################
FROM maven:3.9-eclipse-temurin-25 AS build
WORKDIR /build

# Layer-cache Maven deps: copy poms first so a source-only change doesn't
# re-download the world. `-pl web -am` builds web + its module deps (core,
# web-api, web-bundle, reader-gtfs, map-matching, navigation, client-hc).
COPY pom.xml .
COPY core/pom.xml         core/
COPY web-bundle/pom.xml   web-bundle/
COPY web-api/pom.xml      web-api/
COPY web/pom.xml          web/
COPY navigation/pom.xml   navigation/
COPY map-matching/pom.xml map-matching/
COPY reader-gtfs/pom.xml  reader-gtfs/
COPY client-hc/pom.xml    client-hc/
COPY tools/pom.xml        tools/
COPY example/pom.xml      example/
RUN mvn -B -q -pl web -am dependency:go-offline || true

COPY . .
RUN mvn -B clean install -DskipTests -pl web -am

###############################################################################
# Runtime stage: slim JRE, the fat-jar, and the fork's config.yml
###############################################################################
FROM eclipse-temurin:25-jre
LABEL org.opencontainers.image.title="graphhopper-landmark" \
      org.opencontainers.image.description="GraphHopper 12.0 fork with POI landmark detection (has_landmark / landmark_name)"

WORKDIR /app

COPY --from=build /build/web/target/graphhopper-web-12.0-SNAPSHOT.jar app.jar
COPY config.yml config.yml

# The 173M Nepal graph-cache loads into RAM_STORE; 4g is plenty for serving.
# Bump -Xmx before importing a bigger extract (import is more memory-hungry).
ENV JAVA_OPTS="-Xmx4g -Xms512m" \
    DATAREADER_FILE="/data/Nepal_data.v07172026.osm.pbf" \
    GRAPH_LOCATION="/data/graph-cache"

EXPOSE 8989 8990

# config.yml pins bind_host: localhost; republish on 0.0.0.0 so the container
# is reachable from the host. Override keys must use the YAML's snake_case
# (application_connectors / bind_host), NOT the camelCase Java property names.
# `exec` keeps java as PID 1 so SIGTERM reaches Dropwizard for a graceful shutdown.
# Import runs automatically if /data/graph-cache is empty.
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS \
  -Ddw.graphhopper.datareader.file=$DATAREADER_FILE \
  -Ddw.graphhopper.graph.location=$GRAPH_LOCATION \
  -Ddw.server.application_connectors[0].bind_host=0.0.0.0 \
  -Ddw.server.admin_connectors[0].bind_host=0.0.0.0 \
  -jar app.jar server config.yml"]
