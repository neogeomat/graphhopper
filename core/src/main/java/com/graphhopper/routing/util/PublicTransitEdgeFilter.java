/*
 * Copyright 2013 Thomas Buerli <tbuerli@student.ethz.ch>.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package com.graphhopper.routing.util;

import com.graphhopper.util.EdgeIterator;

/**
 *
 * @author Thomas Buerli <tbuerli@student.ethz.ch>
 */
public class PublicTransitEdgeFilter implements EdgeFilter {

    private PublicTransitFlagEncoder encoder;
    
    private final boolean in;
    private final boolean out;
    private final boolean transit;
    private final boolean boarding;
    private final boolean alight;

    public PublicTransitEdgeFilter(PublicTransitFlagEncoder encoder, boolean in, boolean out, boolean transit, boolean boarding, boolean alight) {
        this.encoder = encoder;
        this.in = in;
        this.out = out;
        this.transit = transit;
        this.boarding = boarding;
        this.alight = alight;
    }

    @Override
    public boolean accept(EdgeIterator iter) {
        int flags = iter.flags();
        return checkEdgeDirection(flags) && checkEdgeType(flags);
    }
    
    private boolean checkEdgeType(int flags) {
        return ((transit == encoder.isTransit(flags)) && (boarding == encoder.isBoarding(flags)) && (alight == encoder.isAlight(flags)));
    }
    
    private boolean checkEdgeDirection(int flags) {
        return (out && encoder.isForward(flags)) || (in && encoder.isBackward(flags));
    }
}