package com.graphhopper.routing.util.parsers;

import com.graphhopper.reader.ReaderWay;
import com.graphhopper.routing.ev.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

class LandmarkParserTest {

    private LandmarkParser parser;
    private LandmarkParser parserWithName;
    private BooleanEncodedValue hasLandmark;
    private StringEncodedValue landmarkName;

    @BeforeEach
    public void setup() {
        hasLandmark = new SimpleBooleanEncodedValue("has_landmark", true);
        hasLandmark.init(new EncodedValue.InitializerConfig());
        parser = new LandmarkParser(hasLandmark);

        landmarkName = new StringEncodedValue("landmark_name", 50_000, false);
        landmarkName.init(new EncodedValue.InitializerConfig());
        parserWithName = new LandmarkParser(hasLandmark, landmarkName);
    }

    @Test
    public void testOnWayNode_amenity() {
        EdgeIntAccess edgeIntAccess = new ArrayEdgeIntAccess(1);
        Map<String, Object> nodeTags = new HashMap<>();
        nodeTags.put("amenity", "restaurant");
        ReaderWay way = new ReaderWay(1);
        way.setTag("node_tags", Collections.singletonList(nodeTags));
        parser.handleWayTags(0, edgeIntAccess, way, null);
        assertTrue(hasLandmark.getBool(false, 0, edgeIntAccess));
    }

    @Test
    public void testOnWayNode_tourism() {
        EdgeIntAccess edgeIntAccess = new ArrayEdgeIntAccess(1);
        Map<String, Object> nodeTags = new HashMap<>();
        nodeTags.put("tourism", "museum");
        ReaderWay way = new ReaderWay(1);
        way.setTag("node_tags", Collections.singletonList(nodeTags));
        parser.handleWayTags(0, edgeIntAccess, way, null);
        assertTrue(hasLandmark.getBool(false, 0, edgeIntAccess));
    }

    @Test
    public void testNearbyLandmarks() {
        EdgeIntAccess edgeIntAccess = new ArrayEdgeIntAccess(1);
        Map<String, Object> nearbyTags = new HashMap<>();
        nearbyTags.put("amenity", "fuel");
        ReaderWay way = new ReaderWay(1);
        way.setTag("nearby_landmarks", Collections.singletonList(nearbyTags));
        parser.handleWayTags(0, edgeIntAccess, way, null);
        assertTrue(hasLandmark.getBool(false, 0, edgeIntAccess));
    }

    @Test
    public void testNoLandmark() {
        EdgeIntAccess edgeIntAccess = new ArrayEdgeIntAccess(1);
        Map<String, Object> nodeTags = new HashMap<>();
        nodeTags.put("highway", "residential");
        ReaderWay way = new ReaderWay(1);
        way.setTag("node_tags", Collections.singletonList(nodeTags));
        parser.handleWayTags(0, edgeIntAccess, way, null);
        assertFalse(hasLandmark.getBool(false, 0, edgeIntAccess));
    }

    @Test
    public void testNoTags() {
        EdgeIntAccess edgeIntAccess = new ArrayEdgeIntAccess(1);
        ReaderWay way = new ReaderWay(1);
        parser.handleWayTags(0, edgeIntAccess, way, null);
        assertFalse(hasLandmark.getBool(false, 0, edgeIntAccess));
    }
}
