package com.graphhopper.routing.util.parsers;

import com.graphhopper.reader.ReaderWay;
import com.graphhopper.routing.ev.BooleanEncodedValue;
import com.graphhopper.routing.ev.EdgeIntAccess;
import com.graphhopper.routing.ev.StringEncodedValue;
import com.graphhopper.storage.IntsRef;

import java.util.*;

public class LandmarkParser implements TagParser {

    protected final BooleanEncodedValue hasLandmarkEnc;
    protected final StringEncodedValue landmarkNameEnc;

    public LandmarkParser(BooleanEncodedValue hasLandmarkEnc) {
        this(hasLandmarkEnc, null);
    }

    public LandmarkParser(BooleanEncodedValue hasLandmarkEnc, StringEncodedValue landmarkNameEnc) {
        this.hasLandmarkEnc = hasLandmarkEnc;
        this.landmarkNameEnc = landmarkNameEnc;
    }

    @Override
    public void handleWayTags(int edgeId, EdgeIntAccess edgeIntAccess, ReaderWay readerWay, IntsRef relationFlags) {
        String name = checkNodeTags(readerWay.getTag("node_tags", null));
        if (name == null)
            name = checkNearbyLandmarks(readerWay.getTag("nearby_landmarks", null));
        if (name != null) {
            hasLandmarkEnc.setBool(false, edgeId, edgeIntAccess, true);
            if (landmarkNameEnc != null)
                landmarkNameEnc.setString(false, edgeId, edgeIntAccess, name);
        }
    }

    private String checkNodeTags(List<Map<String, Object>> nodeTags) {
        if (nodeTags == null) return null;
        for (Map<String, Object> tags : nodeTags) {
            if (tags == null) continue;
            String key = findLandmarkKey(tags);
            if (key != null) {
                String name = (String) tags.get("name");
                if (name != null) return name;
                Object val = tags.get(key);
                return val instanceof String ? key + "=" + val : key;
            }
        }
        return null;
    }

    private String checkNearbyLandmarks(List<Map<String, Object>> nearbyLandmarks) {
        if (nearbyLandmarks == null) return null;
        for (Map<String, Object> tags : nearbyLandmarks) {
            if (tags == null) continue;
            String key = findLandmarkKey(tags);
            if (key != null) {
                String name = (String) tags.get("name");
                if (name != null) return name;
                Object val = tags.get(key);
                return val instanceof String ? key + "=" + val : key;
            }
        }
        return null;
    }

    private String findLandmarkKey(Map<String, Object> tags) {
        for (String key : LandmarkNodeIndex.LANDMARK_KEYS) {
            if (tags.containsKey(key))
                return key;
        }
        return null;
    }
}
