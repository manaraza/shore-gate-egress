// =====================================================================
// 14_export_routing_stack
// Shore-Gate: Egress
//
// Export the frozen routing inputs as ONE GeoTIFF for Python / Colab.
//
// IMPORTANT:
//   friction > 0  = traversable routing cell
//   friction == -1 = impassable / water / no routing cell
//
// Helper bands may contain default values outside traversable land,
// so Python must always use friction > 0 as the master valid mask.
//
// Bands:
//   1. friction
//   2. impact_confidence
//   3. road_impact
//   4. road_class
//   5. slope_deg
//   6. worldcover
//
// Grid:
//   EPSG:32701
//   10 m routing grid, identical to friction_v1
//   (crsTransform [10,0,669500,0,-10,7671040], confirmed in 13b)
// =====================================================================


// ---- 1. Study area ----------------------------------------------------
var analysisBox = ee.Geometry.Rectangle(
  [-175.3661011546799, -21.28198284420156,
   -175.02167858181292, -21.053702480502235],
  null,
  false
);


// ---- 2. Frozen friction asset ----------------------------------------
var fr = ee.Image(
  'projects/shore-gate-egress/assets/friction_v1'
);


// ---- 3. WorldCover ----------------------------------------------------
// Needed in Python for:
//   - water / land structure
//   - wetland / mangrove exclusion
//   - tree-covered coast retention
//   - coastline screening

var wc = ee.ImageCollection('ESA/WorldCover/v200')
  .first()
  .select('Map')
  .rename('worldcover')
  .toByte();


// Put WorldCover explicitly on the 10 m routing grid.
var wc10 = wc.reproject({
  crs: 'EPSG:32701',
  scale: 10
});


// ---- 4. Build compact Python routing stack ----------------------------

// IMPORTANT:
// friction uses -1 outside traversable cells.
// The other bands receive sensible sentinel/default values,
// but must only be interpreted where friction > 0.

var frictionBand = fr
  .select('friction')
  .unmask(-1)
  .rename('friction');

var confidenceBand = fr
  .select('impact_confidence')
  .unmask(0)            // no impact data -> no confidence (conservative)
  .rename('impact_confidence');

var roadImpactBand = fr
  .select('road_impact')
  .unmask(-1)
  .rename('road_impact');

var roadClassBand = fr
  .select('road_class')
  .unmask(0)
  .rename('road_class');

var slopeBand = fr
  .select('slope_deg')
  .unmask(0)
  .rename('slope_deg');

var worldCoverBand = wc10
  .unmask(0)
  .rename('worldcover');


var stack = frictionBand
  .addBands(confidenceBand)
  .addBands(roadImpactBand)
  .addBands(roadClassBand)
  .addBands(slopeBand)
  .addBands(worldCoverBand)
  .toFloat()
  .clip(analysisBox);


// ---- 5. Verification --------------------------------------------------

print(
  'Routing stack bands (expect 6):',
  stack.bandNames()
);

print(
  'Number of bands:',
  stack.bandNames().size()
);

print(
  'Routing projection:',
  stack.select('friction').projection()
);

print(
  'Routing nominal scale:',
  stack.select('friction')
    .projection()
    .nominalScale()
);

print(
  'Friction min / max / mean:',
  stack.select('friction')
    .updateMask(stack.select('friction').gt(0))
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
    })
);

print(
  'WorldCover classes:',
  stack.select('worldcover')
    .reduceRegion({
      reducer: ee.Reducer.frequencyHistogram(),
      geometry: analysisBox,
      scale: 30,
      maxPixels: 1e9,
      tileScale: 8
    })
);


// Passable land where impact confidence was missing in friction_v1.
// These pixels get confidence 0 in the export. Expect a small number
// (mostly outside the impact-model domain).
var noConf = fr.select('friction').unmask(-1).gt(0)
  .and(fr.select('impact_confidence').mask().eq(0));

print(
  'Passable pixels with no impact confidence (30 m count):',
  noConf.reduceRegion({
    reducer: ee.Reducer.sum(),
    geometry: analysisBox,
    scale: 30,
    maxPixels: 1e9,
    tileScale: 8
  })
);


// ---- 6. Map check -----------------------------------------------------

Map.centerObject(analysisBox, 11);
Map.setOptions('SATELLITE');

Map.addLayer(
  stack.select('friction')
    .updateMask(
      stack.select('friction').gt(0)
    ),
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
  'Routing friction'
);

Map.addLayer(
  stack.select('worldcover'),
  {
    min: 10,
    max: 100
  },
  'WorldCover',
  false
);

Map.addLayer(
  stack.select('impact_confidence')
    .updateMask(
      stack.select('friction').gt(0)
    ),
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


// ---- 7. Export to Google Drive ---------------------------------------

Export.image.toDrive({
  image: stack,

  description: 'tongatapu_routing_stack_v1',

  folder: 'shoregate',

  fileNamePrefix: 'tongatapu_routing_stack_v1',

  region: analysisBox,

  crs: 'EPSG:32701',

  // Same pixel grid as friction_v1: no half-pixel shift, so
  // 1-pixel-wide roads stay exactly where they were built.
  crsTransform: [10, 0, 669500, 0, -10, 7671040],

  maxPixels: 1e10,

  fileFormat: 'GeoTIFF',

  formatOptions: {
    cloudOptimized: true
  }
});