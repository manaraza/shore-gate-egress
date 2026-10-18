// =====================================================================
// 08_impact_labels
// Shore-Gate: Egress
//
// FINAL conservative proxy labels for the post-event impact model.
//
// LABEL 1 = strong-change impact proxy
//   - ALOS-2 DPM score >= 59 ("red or darker")
//   - on trusted surfaces only: 30 Grassland, 40 Cropland,
//     50 Built-up, 60 Bare / sparse vegetation
//   - belongs to a connected cluster of >= 3 pixels
//
// LABEL 0 = low-change reference
//   - DPM score = 0
//   - at least 90 m away from ANY displayed DPM change
//   - on the SAME trusted surface classes
//
// EXCLUDED / UNKNOWN
//   - DPM score 1-58
//   - Trees (10), Shrubland (20), Water (80), Herbaceous wetland (90),
//     Mangroves (95), and all other uncertain pixels
//
// IMPORTANT:
// DPM score is an ORDINAL encoding of the published colour scale.
// It is NOT a physical percentage of damage/change.
//
// FINAL LABEL DESIGN (MIN_CLUSTER = 3):
//   Positive labels: 611 pixels in 126 separate spatial clusters
//     Grassland (30): 370 | Built-up (50): 233 | Bare (60): 8
//     Cropland (40): 0 (WorldCover maps Tongatapu farmland as grassland)
//   Available low-change reference pixels: 125,382
//     Grassland: 117,013 | Built-up: 8,075 | Bare: 294
//
// TRAINING NOTE:
// Do NOT randomly sample all negatives. For Model 2, sample negatives
// to match the positive surface distribution:
//     Grassland 370 | Built-up 233 | Bare 8  ->  611 pos : 611 neg
//
// Some grassland positives may represent agricultural / land-cover
// change between the 2019/2020 ALOS-2 reference acquisitions and
// January 2022, rather than eruption impact.
// These are PROXY labels, not field-observed ground truth.
// =====================================================================


// ---- 1. Study area (frozen) ----------------------------------------
var analysisBox = ee.Geometry.Rectangle(
  [-175.3661011546799, -21.28198284420156,
   -175.02167858181292, -21.053702480502235],
  null, false);


// ---- 2. ALOS-2 DPM ordinal score -----------------------------------
var dpm = ee.Image('projects/shore-gate-egress/assets/dpm_0122_score').select('b1');
var dpmProj = dpm.projection();

print('DPM projection:', dpmProj);
print('DPM nominal scale (m):', dpmProj.nominalScale());

var anyChange    = dpm.gt(0);
var strongChange = dpm.gte(59);          // "red or darker"


// ---- 3. ESA WorldCover 2021 on the ~31 m DPM grid (modal class) -----
var wc = ee.ImageCollection('ESA/WorldCover/v200')
  .first()
  .select('Map')
  .reduceResolution({reducer: ee.Reducer.mode(), maxPixels: 64})
  .reproject(dpmProj)
  .clip(analysisBox);


// ---- 4. Trusted training surfaces (same for both classes) -----------
var trustedSurface = wc.eq(30)
  .or(wc.eq(40))
  .or(wc.eq(50))
  .or(wc.eq(60));


// ---- 5. Positive class: strong-change impact proxy ------------------
var MIN_CLUSTER = 3;

var strongTrusted = strongChange.and(trustedSurface);

var clusterSize = strongTrusted
  .selfMask()
  .connectedPixelCount({maxSize: 100, eightConnected: true})
  .reproject(dpmProj);

var impacted = clusterSize.gte(MIN_CLUSTER);


// ---- 6. Negative class: low-change reference ------------------------
var nearChange = anyChange
  .focal_max({radius: 90, units: 'meters'})
  .reproject(dpmProj);

var lowChange = dpm.eq(0)
  .and(nearChange.eq(0))
  .and(trustedSurface);


// ---- 7. Final label image (everything else stays masked) ------------
var labels = ee.Image(0)
  .updateMask(lowChange)
  .blend(ee.Image(1).updateMask(impacted.unmask(0)))
  .rename('label')
  .reproject(dpmProj)
  .clip(analysisBox);


// ---- 8. Diagnostics -------------------------------------------------
var stats = {geometry: analysisBox, crs: dpmProj, maxPixels: 1e9};
var hist = ee.Reducer.frequencyHistogram().unweighted();

print('1. Final label counts (0 = low-change ref, 1 = strong-change proxy):',
  labels.reduceRegion(Object.assign({reducer: hist}, stats)));

print('2. Positive labels by WorldCover class:',
  wc.updateMask(impacted.unmask(0)).rename('wc')
    .reduceRegion(Object.assign({reducer: hist}, stats)));

print('3. Available negative labels by WorldCover class:',
  wc.updateMask(lowChange).rename('wc')
    .reduceRegion(Object.assign({reducer: hist}, stats)));

print('4. Final number of separate positive clusters:',
  impacted.selfMask().rename('impact').reduceToVectors({
    geometry: analysisBox, crs: dpmProj, eightConnected: true,
    geometryType: 'polygon', maxPixels: 1e9
  }).size());

print('5. DPM pixels inside analysis box:',
  dpm.rename('n').reduceRegion(Object.assign({reducer: ee.Reducer.count()}, stats)));


// ---- 9. Map ---------------------------------------------------------
Map.centerObject(analysisBox, 11);
Map.setOptions('SATELLITE');

Map.addLayer(dpm.selfMask(),
  {min: 1, max: 100, palette: ['yellow', 'orange', 'red', 'purple']},
  'DPM ordinal score', false);
Map.addLayer(trustedSurface.selfMask(), {palette: ['ffffff']},
  'Trusted training surfaces', false);
Map.addLayer(strongTrusted.selfMask(), {palette: ['ff9900']},
  'Strong change on trusted surfaces (before cluster filter)', false);
Map.addLayer(impacted.selfMask(), {palette: ['ff0000']},
  'Final strong-change positives', false);
Map.addLayer(labels, {min: 0, max: 1, palette: ['00a0ff', 'ff0000']},
  'FINAL labels (blue 0 / red 1)', true);
Map.addLayer(analysisBox, {color: 'white'}, 'Analysis box', false);


// ---- 10. Export final labels to a GEE asset -------------------------
// After clicking Run: Tasks tab -> dpm_labels_v1_c3 -> RUN ->
// leave settings unchanged -> RUN -> wait for COMPLETED.
// pyramidingPolicy 'mode' keeps 0/1 labels clean when zoomed out
// (the default 'mean' would blur them into in-between values).

Export.image.toAsset({
  image: labels.toByte(),
  description: 'dpm_labels_v1_c3',
  assetId: 'projects/shore-gate-egress/assets/dpm_labels_v1_c3',
  region: analysisBox,
  crs: dpmProj.crs().getInfo(),
  crsTransform: dpmProj.getInfo().transform,
  maxPixels: 1e10,
  pyramidingPolicy: {'label': 'mode'}
});
// =====================================================================
// FINAL EXPORT VERIFICATION
// =====================================================================

var exportedLabels = ee.Image(
  'projects/shore-gate-egress/assets/dpm_labels_v1_c3'
);

print('Exported label asset:', exportedLabels);

print(
  'Exported label counts:',
  exportedLabels.reduceRegion({
    reducer: ee.Reducer.frequencyHistogram().unweighted(),
    geometry: analysisBox,
    crs: dpmProj,
    maxPixels: 1e9
  })
);

Map.addLayer(
  exportedLabels,
  {
    min: 0,
    max: 1,
    palette: ['00a0ff', 'ff0000']
  },
  'EXPORTED labels verification',
  false
);
