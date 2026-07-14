package com.graphhopper.routing.util.parsers;

import java.util.*;

public class LandmarkNodeIndex {

    public static final Set<String> LANDMARK_KEYS = new HashSet<>(Arrays.asList(
            "amenity", "tourism", "historic", "leisure",
            "shop", "public_transport", "natural", "man_made"
    ));

    public static class LandmarkNode {
        final double lat;
        final double lon;
        final Map<String, Object> tags;

        LandmarkNode(double lat, double lon, Map<String, Object> tags) {
            this.lat = lat;
            this.lon = lon;
            this.tags = tags;
        }

        public Map<String, Object> getTags() {
            return tags;
        }
    }

    private final double cellSizeDeg;
    private final Map<Long, List<LandmarkNode>> grid = new HashMap<>();

    public LandmarkNodeIndex(double cellSizeMeters) {
        this.cellSizeDeg = cellSizeMeters / 111_320.0;
    }

    public void add(double lat, double lon, Map<String, Object> tags) {
        long cellKey = cellKey(lat, lon);
        grid.computeIfAbsent(cellKey, k -> new ArrayList<>()).add(new LandmarkNode(lat, lon, tags));
    }

    public List<LandmarkNode> query(double lat, double lon, double radiusMeters) {
        double radiusDeg = radiusMeters / 111_320.0;
        int cellSpan = (int) Math.ceil(radiusDeg / cellSizeDeg);
        long cx = cellX(lon);
        long cy = cellY(lat);
        List<LandmarkNode> results = new ArrayList<>();
        double radiusSq = radiusDeg * radiusDeg;
        for (long dx = -cellSpan; dx <= cellSpan; dx++) {
            for (long dy = -cellSpan; dy <= cellSpan; dy++) {
                List<LandmarkNode> nodes = grid.get(key(cx + dx, cy + dy));
                if (nodes == null) continue;
                for (LandmarkNode n : nodes) {
                    double dlat = n.lat - lat;
                    double dlon = (n.lon - lon) * Math.cos(Math.toRadians((lat + n.lat) / 2));
                    if (dlat * dlat + dlon * dlon <= radiusSq) {
                        results.add(n);
                    }
                }
            }
        }
        return results;
    }

    private long cellKey(double lat, double lon) {
        return key(cellX(lon), cellY(lat));
    }

    private long cellY(double lat) {
        return Math.round(Math.floor((lat + 90) / cellSizeDeg));
    }

    private long cellX(double lon) {
        return Math.round(Math.floor((lon + 180) / cellSizeDeg));
    }

    private static long key(long cx, long cy) {
        return (cx << 32) | (cy & 0xFFFFFFFFL);
    }
}
