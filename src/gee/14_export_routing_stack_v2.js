// =====================================================================
// 14_export_routing_stack_v2
// Shore-Gate: Egress
//
// Routing stack for 15_routing_mcda_v2: the 6 frozen routing bands plus
// two area-wide impact bands, so Hazard Safety and Data Confidence do
// not depend on how close a site is to a road.
//
// impact_excess_all = surface-relative impact excess across all
// VALID MODEL-2 DOMAIN surfaces (grass/crop/built/bare). Tree, mangrove,
// wetland etc. stay invalid (impact_valid_all = 0, excess = -1), which
// means IMPACT UNKNOWN, never zero hazard.
//
// Bands:
//   1 friction            1-30; -1 = impassable / water / no data
//   2 impact_confidence   road-impact coverage helper (audit); missing -> 0
//   3 road_impact         surface-relative impact excess on roads (audit)
//   4 road_class          0 none, 1 sealed, 2 unsealed
//   5 slope_deg
//   6 worldcover          ESA WorldCover v200; 0 = no data
//   7 impact_excess_all   surface-relative impact excess, valid Model-2 domain
//                         (grass/crop/built/bare); -1 = unknown
//   8 impact_valid_all    1 where band 7 is valid, else 0
//
// Grid: EPSG:32701, 10 m, crsTransform [10,0,669500,0,-10,7671040]
// (identical to friction_v1). Impact information is ~31 m (Model 2B grid).
// =====================================================================

var analysisBox = ee.Geometry.Rectangle(
  [-175.3661011546799, -21.28198284420156,
   -175.02167858181292, -21.053702480502235],
  null, false
);

var fr     = ee.Image('projects/shore-gate-egress/assets/friction_v1');
var impact = ee.Image('projects/shore-gate-egress/assets/impact_score_v1');
var wc     = ee.ImageCollection('ESA/WorldCover/v200').first().select('Map');


// ---- 1. Impact score inside the model domain -------------------------
var impTrusted = impact.select('impact_score')
  .updateMask(impact.select('in_domain').eq(1));
var impProj = impTrusted.projection();

// WorldCover on the Model 2B grid (majority class per ~31 m cell).
var wc31 = wc
  .reduceResolution({reducer: ee.Reducer.mode(), maxPixels: 64})
  .reproject(impProj);


// ---- 2. Class reference levels: FROZEN values from friction_v1 -------
// Exact values from the final friction_v1 run (not rounded), so the excess
// uses exactly the same reference as the friction surface.
// Cropland uses the grassland reference.
var MED_GRASS = 0.3106075467141432;
var MED_BUILT = 0.49821893932068184;
var MED_BARE  = 0.5988611777623495;

// Recompute only as a QA check.
function classMedian(c) {
  return impTrusted
    .updateMask(wc31.eq(c))
    .reduceRegion({
      reducer: ee.Reducer.median(),
      geometry: analysisBox,
      crs: impProj,
      maxPixels: 1e9,
      tileScale: 8
    })
    .get('impact_score');
}
print('CHECK class medians [grass, built, bare] (expect 0.3106, 0.4982, 0.5989):',
  ee.List([classMedian(30), classMedian(50), classMedian(60)]));

var bgMedian = wc31.remap(
  [30, 40, 50, 60],
  [MED_GRASS, MED_GRASS, MED_BUILT, MED_BARE]
).rename('bg_median');


// ---- 3. Impact excess over the valid Model-2 domain + validity --------------------------
// excess = clamp((score - class_ref) / (1 - class_ref), 0, 1)
// Masked where the score is outside the domain OR the 31 m cell is not
// grass/crop/built/bare (no reference level).
var impactExcessAll = impTrusted.subtract(bgMedian)
  .divide(ee.Image(1).subtract(bgMedian))
  .clamp(0, 1)
  .rename('impact_excess_all');

// Validity comes from the excess band itself, so a pixel can never be
// "valid" while carrying the -1 fill value.
var impactValidAll = impactExcessAll.mask().gt(0)
  .unmask(0)
  .rename('impact_valid_all');


// ---- 4. Stack ----------------------------------------------------------
var stack = ee.Image.cat([
  fr.select('friction').unmask(-1),
  fr.select('impact_confidence').unmask(0),
  fr.select('road_impact').unmask(-1),
  fr.select('road_class').unmask(0),
  fr.select('slope_deg').unmask(0),
  wc.rename('worldcover').unmask(0),
  impactExcessAll.unmask(-1),
  impactValidAll
]).toFloat().clip(analysisBox);


// ---- 5. Checks -----------------------------------------------------------
print('Routing stack v2 bands (expect 8):', stack.bandNames());

print('impact_excess_all min/max/mean (valid only):',
  stack.select('impact_excess_all')
    .updateMask(stack.select('impact_valid_all').eq(1))
    .reduceRegion({
      reducer: ee.Reducer.minMax().combine({reducer2: ee.Reducer.mean(), sharedInputs: true}),
      geometry: analysisBox, scale: 30, maxPixels: 1e9, tileScale: 8
    }));

var passableLand = stack.select('friction').gt(0);
print('Share of passable land with valid impact (0-1):',
  stack.select('impact_valid_all').updateMask(passableLand)
    .reduceRegion({reducer: ee.Reducer.mean(), geometry: analysisBox,
                   scale: 30, maxPixels: 1e9, tileScale: 8}));

// Road consistency check (QA only; does not change the export).
// friction_v1's road_impact uses a 50 m neighbourhood mean, so compare
// like with like. Two orders of operation are printed; the one closer to 0
// shows which order friction_v1 used. Expect one of them to be very small.
var roadMask = stack.select('road_class').gt(0)
  .and(stack.select('road_impact').gte(0));

// (a) 50 m mean of the per-pixel excess
var excessThenMean = impactExcessAll
  .focal_mean({radius: 50, units: 'meters'});

// (b) excess of the 50 m mean score
var meanThenExcess = impTrusted
  .focal_mean({radius: 50, units: 'meters'})
  .subtract(bgMedian)
  .divide(ee.Image(1).subtract(bgMedian))
  .clamp(0, 1);

function roadDiff(img, label) {
  print(label,
    img.subtract(stack.select('road_impact')).abs()
      .updateMask(roadMask.and(img.mask()))
      .reduceRegion({
        reducer: ee.Reducer.mean().combine({
          reducer2: ee.Reducer.percentile([95]), sharedInputs: true}),
        geometry: analysisBox, scale: 10, maxPixels: 1e9, tileScale: 8
      }));
}
roadDiff(excessThenMean, 'CHECK (a) |50 m mean of excess - road_impact| on roads:');
roadDiff(meanThenExcess, 'CHECK (b) |excess of 50 m mean - road_impact| on roads:');


// ---- 6. Map ------------------------------------------------------------
Map.centerObject(analysisBox, 11);
Map.setOptions('SATELLITE');
Map.addLayer(stack.select('friction').updateMask(passableLand),
  {min: 1, max: 12, palette: ['1a9850', '91cf60', 'ffffbf', 'fc8d59', 'd73027']}, 'Friction');
Map.addLayer(stack.select('impact_excess_all')
    .updateMask(stack.select('impact_valid_all').eq(1)),
  {min: 0, max: 0.6, palette: ['2c7bb6', 'ffffbf', 'd7191c']}, 'All-surface impact excess', false);
Map.addLayer(stack.select('impact_valid_all').updateMask(passableLand),
  {min: 0, max: 1, palette: ['ff00ff', 'ffffff']}, 'Impact valid (white) / none (magenta)', false);


// ---- 7. Export (same grid as friction_v1) --------------------------------
Export.image.toDrive({
  image: stack,
  description: 'tongatapu_routing_stack_v2',
  folder: 'shoregate',
  fileNamePrefix: 'tongatapu_routing_stack_v2',
  region: analysisBox,
  crs: 'EPSG:32701',
  crsTransform: [10, 0, 669500, 0, -10, 7671040],
  maxPixels: 1e10,
  fileFormat: 'GeoTIFF',
  formatOptions: {cloudOptimized: true}
});
