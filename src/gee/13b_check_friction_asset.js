// =====================================================================
// 13b_check_friction_asset
// Shore-Gate: Egress
// Verify frozen friction_v1 + cleaned destination asset
// =====================================================================


// ---- 1. Study area ----------------------------------------------------
var analysisBox = ee.Geometry.Rectangle(
  [-175.3661011546799, -21.28198284420156,
   -175.02167858181292, -21.053702480502235],
  null,
  false
);


// ---- 2. Load frozen assets -------------------------------------------
var friction = ee.Image(
  'projects/shore-gate-egress/assets/friction_v1'
);

var destinations = ee.FeatureCollection(
  'projects/shore-gate-egress/assets/tongatapu_destinations_20220115_gee'
);


// ---- 3. Basic asset checks -------------------------------------------
print('FRICTION ASSET:', friction);

print(
  'Friction bands (expect 12):',
  friction.bandNames()
);

print(
  'Number of bands:',
  friction.bandNames().size()
);

print(
  'Friction projection:',
  friction.select('friction').projection()
);

print(
  'Friction nominal scale (expect ~10 m):',
  friction.select('friction')
    .projection()
    .nominalScale()
);


// ---- 4. Destination checks -------------------------------------------
print(
  'Destination count (expect 363):',
  destinations.size()
);

print(
  'Destinations by type:',
  destinations.aggregate_histogram('dest_type')
);

print(
  'Destinations by tier:',
  destinations.aggregate_histogram('tier')
);

print(
  'Example destination:',
  destinations.first()
);


// ---- 5. Friction summary statistics ----------------------------------
var frictionStats = friction
  .select('friction')
  .reduceRegion({
    reducer: ee.Reducer.minMax()
      .combine({
        reducer2: ee.Reducer.mean(),
        sharedInputs: true
      }),
    geometry: analysisBox,
    scale: 30,
    maxPixels: 1e9,
    tileScale: 8
  });

print(
  'Friction min / max / mean:',
  frictionStats
);


// ---- 6. Confirm important routing bands -------------------------------
print(
  'Road impact excess min/max:',
  friction.select('road_impact')
    .reduceRegion({
      reducer: ee.Reducer.minMax(),
      geometry: analysisBox,
      scale: 30,
      maxPixels: 1e9,
      tileScale: 8
    })
);

print(
  'Road impact RAW min/max:',
  friction.select('road_impact_raw')
    .reduceRegion({
      reducer: ee.Reducer.minMax(),
      geometry: analysisBox,
      scale: 30,
      maxPixels: 1e9,
      tileScale: 8
    })
);

print(
  'Impact-confidence min/max:',
  friction.select('impact_confidence')
    .reduceRegion({
      reducer: ee.Reducer.minMax(),
      geometry: analysisBox,
      scale: 30,
      maxPixels: 1e9,
      tileScale: 8
    })
);


// ---- 7. Map -----------------------------------------------------------
Map.centerObject(analysisBox, 11);
Map.setOptions('SATELLITE');


// Main friction surface
Map.addLayer(
  friction.select('friction'),
  {
    min: 1,
    max: 12,
    palette: [
      '1a9850',
      '91cf60',
      'ffffbf',
      'fc8d59',
      'd73027'
    ]
  },
  'Frozen friction_v1',
  true
);


// Road impact excess
Map.addLayer(
  friction.select('road_impact'),
  {
    min: 0,
    max: 0.5,
    palette: [
      '2c7bb6',
      'ffffbf',
      'd7191c'
    ]
  },
  'Road impact excess',
  false
);


// Impact confidence
Map.addLayer(
  friction.select('impact_confidence'),
  {
    min: 0,
    max: 1,
    palette: [
      'ff00ff',
      'ffffff'
    ]
  },
  'Impact confidence',
  false
);


// Tier 1 destinations
Map.addLayer(
  destinations.filter(
    ee.Filter.eq('tier', 1)
  ),
  {
    color: 'ff0000',
    pointSize: 6
  },
  'Tier 1 — hospitals',
  true
);


// Tier 2 destinations
Map.addLayer(
  destinations.filter(
    ee.Filter.eq('tier', 2)
  ),
  {
    color: 'ffff00',
    pointSize: 5
  },
  'Tier 2 — clinics / schools',
  false
);


// Tier 3 destinations
Map.addLayer(
  destinations.filter(
    ee.Filter.eq('tier', 3)
  ),
  {
    color: '00ffff',
    pointSize: 4
  },
  'Tier 3 — community / worship',
  false
);


// ---- 8. Expected final bands -----------------------------------------
print(
  'EXPECTED band order:',
  [
    'friction',
    'base_cost',
    'road_class',
    'road_impact',
    'road_impact_raw',
    'impact_coverage',
    'impact_known',
    'impact_confidence',
    'slope_deg',
    'slope_mult',
    'ash_mult',
    'lc_cost'
  ]
);
