package com.graphhopper.routing.ev;

public class HasLandmark {
    public static final String KEY = "has_landmark";

    public static BooleanEncodedValue create() {
        return new SimpleBooleanEncodedValue(KEY, true);
    }
}
