package com.graphhopper.routing.ev;

public class LandmarkName {
    public static final String KEY = "landmark_name";

    public static StringEncodedValue create() {
        return new StringEncodedValue(KEY, 1_000_000, false);
    }
}
