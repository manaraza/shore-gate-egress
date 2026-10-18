// =====================================================================
// 11_validate_impact_emsr558  (v2: training pixels removed,
//                              surface-matched background)
// Shore-Gate: Egress — INDEPENDENT validation of impact_score_v1
//
// Reference: Copernicus EMS EMSR558 AOI01 (Nuku'alofa / Tongatapu)
//   grading product r3 v2, photo-interpreted from 0.5 m Pleiades:
//     source 3 = 17 Jan 2022, 4 = 18 Jan 2022, 5 = 20 Jan 2022
//   NEVER used in training.
//
// "Not Analysed" polygons are SOURCE-SPECIFIC (per image), so the
// analysed area = union over sources 3/4/5 of
//   (that image's footprint − that image's Not Analysed polygon).
// Only features graded from sources 3/4/5 are used (source 997 dropped).
// The 950 RF training pixels are removed (no in-sample predictions).
//
// Roads (main test):
//   positive           = Damaged + Destroyed
//   reference negative = No visible damage (photo-interpreted, not
//                        field-confirmed absence of impact)
//   middle             = Possibly damaged (reported separately)
//   AUC is a descriptive measure; segments are spatially correlated, so
//   any confidence interval needs a spatial block bootstrap.
// Buildings (secondary): EMS maps no undamaged buildings, so this is an
//   ordinal check plus BACKGROUND REFERENCES (all in-domain land, and a
//   surface-matched built-up reference). Neither is a true negative set.
//
// Only in-domain pixels (WorldCover 30/40/50/60) are scored.
// impact_score is a relative score, not a calibrated probability.
// =====================================================================

// ---- 1. Assets -------------------------------------------------------
var analysisBox = ee.Geometry.Rectangle(
  [-175.3661011546799, -21.28198284420156,
   -175.02167858181292, -21.053702480502235], null, false);

var impact  = ee.Image('projects/shore-gate-egress/assets/impact_score_v1');
var labProj = impact.select('impact_score').projection();

var roads = ee.FeatureCollection('projects/shore-gate-egress/assets/emsr558_roads');
var bld   = ee.FeatureCollection('projects/shore-gate-egress/assets/emsr558_buildings');
var fp    = ee.FeatureCollection('projects/shore-gate-egress/assets/emsr558_footprints');

var POST_SRC = [3, 4, 5];

// ---- 2. Score image: in-domain + genuinely analysed EMS area ----------
function analysedForSource(srcId) {
  var footprint = fp
    .filter(ee.Filter.eq('obj_type', 'Image Footprint'))
    .filter(ee.Filter.eq('or_src_id', srcId))
    .geometry();
  var notAnalysed = fp
    .filter(ee.Filter.eq('obj_type', 'Not Analysed'))
    .filter(ee.Filter.eq('or_src_id', srcId))
    .geometry();
  return ee.Feature(footprint.difference(notAnalysed, 1), {src_id: srcId});
}

var analysedAreas = ee.FeatureCollection([
  analysedForSource(3),
  analysedForSource(4),
  analysedForSource(5)
]);
var analysedGeom = analysedAreas.geometry();

var score = impact.select('impact_score')
  .updateMask(impact.select('in_domain').eq(1))
  .clip(analysedGeom);

// ---- 2b. Remove RF training pixels from independent validation -------
// The final Model 2B raster was fitted using these 950 pixels.
var trainSamples = ee.FeatureCollection('projects/shore-gate-egress/assets/impact_samples_v1');
print('Training samples loaded (expect 950):', trainSamples.size());

var trainPix = trainSamples
  .map(function (f) { return f.set('train_flag', 1); })
  .reduceToImage({properties: ['train_flag'], reducer: ee.Reducer.first()})
  .reproject(labProj);

score = score.updateMask(trainPix.mask().not());   // keep NON-training pixels

// ---- 3. Reference pools (post-event sources only) ----------------------
var gradeClass = ee.Dictionary({
  'Destroyed': 1, 'Damaged': 1, 'No visible damage': 0, 'Possibly damaged': 2
});

var roadsPost = roads
  .filter(ee.Filter.inList('dmg_src_id', POST_SRC))
  .filter(ee.Filter.inList('damage_gra',
    ['Destroyed', 'Damaged', 'No visible damage', 'Possibly damaged']));

var roadsUse = roadsPost.map(function (f) {
  return f.buffer(20).set('cls', gradeClass.get(f.get('damage_gra')));
});

var bldUse = bld.filter(ee.Filter.inList('dmg_src_id', POST_SRC));

print('Roads used, by EMS grade (expect 169 / 27 / 225 / 4374):',
  roadsPost.aggregate_histogram('damage_gra'));
print('Buildings used, by EMS grade (expect 131 / 87 / 1717):',
  bldUse.aggregate_histogram('damage_gra'));

// ---- 4. Roads: score per segment (20 m buffer) -------------------------
var roadStats = score.reduceRegions({
  collection: roadsUse,
  reducer: ee.Reducer.mean()
    .combine({reducer2: ee.Reducer.max(), sharedInputs: true})
    .combine({reducer2: ee.Reducer.count(), sharedInputs: true}),
  crs: labProj,
  tileScale: 8
});

var valid = roadStats.filter(ee.Filter.notNull(['mean']));
var pos = valid.filter(ee.Filter.eq('cls', 1));
var neg = valid.filter(ee.Filter.eq('cls', 0));
var mid = valid.filter(ee.Filter.eq('cls', 2));

function median(fc) {
  return fc.reduceColumns(ee.Reducer.median(), ['mean']).get('median');
}

print('ROADS — segments with a usable score / total, by class',
  ee.Dictionary({
    'damaged+destroyed': ee.List([pos.size(), roadsUse.filter(ee.Filter.eq('cls', 1)).size()]),
    'no visible damage (reference negative)': ee.List([neg.size(), roadsUse.filter(ee.Filter.eq('cls', 0)).size()]),
    'possibly damaged': ee.List([mid.size(), roadsUse.filter(ee.Filter.eq('cls', 2)).size()])
  }));

print('ROADS — [mean, median] impact score by class',
  ee.Dictionary({
    'damaged+destroyed': ee.List([pos.aggregate_mean('mean'), median(pos)]),
    'possibly damaged':  ee.List([mid.aggregate_mean('mean'), median(mid)]),
    'no visible damage': ee.List([neg.aggregate_mean('mean'), median(neg)])
  }));

var nP = pos.size();
var nN = neg.size();
var nM = mid.size();

var thresholdTable = ee.List([0.4, 0.5, 0.6, 0.7]).map(function (t) {
  t = ee.Number(t);
  return ee.Dictionary({
    threshold: t,
    recall_damaged: pos.filter(ee.Filter.gte('mean', t)).size().divide(nP),
    false_alarm_no_damage: neg.filter(ee.Filter.gte('mean', t)).size().divide(nN),
    flagged_possibly_damaged: mid.filter(ee.Filter.gte('mean', t)).size().divide(nM)
  });
});
print('ROADS — thresholds (segment mean score >= t):', thresholdTable);

// ROC-AUC (trapezoid, thresholds every 0.05)
var ts = ee.List.sequence(0, 1.05, 0.05);
var roc = ts.map(function (t) {
  t = ee.Number(t);
  return ee.List([
    neg.filter(ee.Filter.gte('mean', t)).size().divide(nN),   // FPR
    pos.filter(ee.Filter.gte('mean', t)).size().divide(nP)    // TPR
  ]);
});
var auc = ee.Number(ee.List.sequence(0, ts.length().subtract(2)).iterate(
  function (i, acc) {
    i = ee.Number(i);
    var a = ee.List(roc.get(i));
    var b = ee.List(roc.get(i.add(1)));
    var dx = ee.Number(a.get(0)).subtract(b.get(0));
    var yAvg = ee.Number(a.get(1)).add(b.get(1)).divide(2);
    return ee.Number(acc).add(dx.multiply(yAvg));
  }, 0));
print('ROADS — ROC-AUC (damaged+destroyed vs no visible damage):', auc);

// ---- 5. Buildings: ordinal check ----------------------------------------
var bldStats = score.reduceRegions({
  collection: bldUse,
  reducer: ee.Reducer.mean(),
  crs: labProj,
  tileScale: 8
});
var bldValid = bldStats.filter(ee.Filter.notNull(['mean']));

function bldSummary(grade) {
  var all = bldUse.filter(ee.Filter.eq('damage_gra', grade));
  var v = bldValid.filter(ee.Filter.eq('damage_gra', grade));
  return ee.Dictionary({
    total: all.size(),
    with_score: v.size(),
    mean_score: v.aggregate_mean('mean'),
    median_score: median(v),
    share_ge_0_5: v.filter(ee.Filter.gte('mean', 0.5)).size().divide(v.size().max(1))
  });
}

// ---- 5b. Background references (all land + surface-matched built-up) ---
var wc = ee.ImageCollection('ESA/WorldCover/v200').first().select('Map')
  .reduceResolution({reducer: ee.Reducer.mode(), maxPixels: 64})
  .reproject(labProj);

function bgStats(img) {
  var meanStats = img.addBands(img.gte(0.5).rename('ge05')).reduceRegion({
    reducer: ee.Reducer.mean(), geometry: analysedGeom, crs: labProj,
    maxPixels: 1e9, tileScale: 8
  });
  var medianScore = img.reduceRegion({
    reducer: ee.Reducer.median(), geometry: analysedGeom, crs: labProj,
    maxPixels: 1e9, tileScale: 8
  }).get('impact_score');
  return ee.Dictionary({
    mean_score: meanStats.get('impact_score'),
    median_score: medianScore,
    share_ge_0_5: meanStats.get('ge05')
  });
}

var bgAll   = bgStats(score);
var bgBuilt = bgStats(score.updateMask(wc.eq(50)));

print('BUILDINGS — by EMS grade (independent validation)', ee.Dictionary({
  'Destroyed': bldSummary('Destroyed'),
  'Damaged': bldSummary('Damaged'),
  'Possibly damaged': bldSummary('Possibly damaged'),
  'BACKGROUND all in-domain analysed land': bgAll,
  'BACKGROUND built-up only (surface-matched reference)': bgBuilt
}));

// ---- 6. Map ---------------------------------------------------------------
Map.centerObject(analysisBox, 11);
Map.setOptions('SATELLITE');
Map.addLayer(score, {min: 0, max: 1, palette: ['2c7bb6', 'abd9e9', 'ffffbf', 'fdae61', 'd7191c']},
  'Impact score (in-domain, analysed, non-training)');
Map.addLayer(analysedAreas, {color: '00ff00'}, 'EMS analysed by >=1 post-event image', false);
Map.addLayer(roadsPost.filter(ee.Filter.eq('damage_gra', 'No visible damage')), {color: 'ffffff'},
  'EMS roads: no visible damage', false);
Map.addLayer(roadsPost.filter(ee.Filter.eq('damage_gra', 'Possibly damaged')), {color: 'ffff00'},
  'EMS roads: possibly damaged', false);
Map.addLayer(roadsPost.filter(ee.Filter.inList('damage_gra', ['Damaged', 'Destroyed'])), {color: 'ff00ff'},
  'EMS roads: damaged/destroyed');
Map.addLayer(bldUse.filter(ee.Filter.inList('damage_gra', ['Damaged', 'Destroyed'])), {color: '000000'},
  'EMS buildings: damaged/destroyed', false);

// ---- 7. Export tables for figures (run from Tasks AFTER checking) ---------
Export.table.toDrive({
  collection: roadStats,
  description: 'emsr558_roads_scores_v2',
  folder: 'shoregate',
  fileFormat: 'CSV',
  selectors: ['damage_gra', 'info', 'dmg_src_id', 'cls', 'mean', 'max', 'count']
});
Export.table.toDrive({
  collection: bldStats,
  description: 'emsr558_buildings_scores_v2',
  folder: 'shoregate',
  fileFormat: 'CSV',
  selectors: ['damage_gra', 'obj_type', 'dmg_src_id', 'mean']
});
