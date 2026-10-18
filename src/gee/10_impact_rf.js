// =====================================================================
// 10_impact_rf
// Shore-Gate: Egress
//
// MODEL 2 — POST-EVENT IMPACT LIKELIHOOD
//
// Labels  : dpm_labels_v1_c3
// Features: features_v1
//
// MODEL 2A: Random Forest — Sentinel-2 optical/change predictors (27)
// MODEL 2B: Random Forest — Sentinel-2 + Sentinel-1 predictors (30)
// BASELINE: One-split CART decision stump using CHANGE FEATURES ONLY
//           = a learned simple single-threshold change rule
//
// Sampling:
//   - all usable positive proxy labels
//   - negatives sampled to match positives surface-by-surface (1:1)
//
// Validation:
//   5-fold SPATIAL BLOCK cross-validation using ~2 km blocks.
//
// IMPORTANT:
//   post_n_obs is QA only and is NOT a predictor.
//
// NOTE:
//   Precision values are measured on the balanced evaluation sample.
//   They are not prevalence-adjusted positive predictive values for
//   the whole island.
//
//   Sentinel-1 was acquired 27 Jan, after the 22 Jan ALOS-2 label date.
//   Model 2B is therefore a RETROSPECTIVE experiment.
// =====================================================================


// =====================================================================
// 1. STUDY AREA + FROZEN ASSETS
// =====================================================================

var analysisBox = ee.Geometry.Rectangle(
  [-175.3661011546799, -21.28198284420156,
   -175.02167858181292, -21.053702480502235],
  null, false);

var labels   = ee.Image('projects/shore-gate-egress/assets/dpm_labels_v1_c3').select('label');
var features = ee.Image('projects/shore-gate-egress/assets/features_v1');
var labProj  = labels.projection();


// =====================================================================
// 2. PREDICTOR LISTS
// =====================================================================

var ALL = ['B2', 'B3', 'B4', 'B8', 'B11', 'B12', 'NDVI', 'NDWI', 'NDBI'];

function names(prefix) {
  return ALL.map(function (b) { return prefix + b; });
}

var PRE   = names('pre_');
var POST  = names('post_');
var DELTA = names('d_');

var OPTICAL = PRE.concat(POST).concat(DELTA);
var SAR     = ['S1_VV', 'S1_VH', 'S1_VH_minus_VV'];

var BANDS_2A       = OPTICAL;
var BANDS_2B       = OPTICAL.concat(SAR);
var BASELINE_BANDS = DELTA;      // baseline uses ONLY change features

print('Model 2A predictors:', BANDS_2A.length);
print('Model 2B predictors:', BANDS_2B.length);
print('Baseline change predictors:', BASELINE_BANDS.length);


// =====================================================================
// 3. COMPLETE-CASE MASK
// =====================================================================
// Same samples for 2A and 2B: require all pre optical, all post
// optical, VV and VH. Delta and VH-VV are derived from those.

function allValid(bands) {
  return features.select(bands).mask().reduce(ee.Reducer.min()).gt(0);
}

var complete = allValid(PRE)
  .and(allValid(POST))
  .and(allValid(['S1_VV', 'S1_VH']));


// =====================================================================
// 4. WORLDCOVER ON LABEL GRID
// =====================================================================

var wc = ee.ImageCollection('ESA/WorldCover/v200')
  .first()
  .select('Map')
  .reduceResolution({reducer: ee.Reducer.mode(), maxPixels: 64})
  .reproject(labProj)
  .clip(analysisBox);


// =====================================================================
// 5. SURFACE STRATA
// =====================================================================
// stratum = label * 100 + WorldCover
//   30 = negative grassland   130 = positive grassland
//   50 = negative built-up    150 = positive built-up
//   60 = negative bare        160 = positive bare

var stratum = labels.multiply(100).add(wc).rename('stratum').toInt();


// =====================================================================
// 6. SPATIAL BLOCKS
// =====================================================================
// ~2 km blocks (0.02 deg lat ~2.2 km, 0.02 deg lon ~2.1 km here).
// All pixels in a block share one fold. Neighbouring blocks always
// fall in different folds. Adjacent train/test blocks can still share
// a boundary, so this is not a strict spatial buffer.

var BLOCK_DEG = 0.02;
var ll = ee.Image.pixelLonLat();

var bx = ll.select('longitude').add(180).divide(BLOCK_DEG).floor();
var by = ll.select('latitude').add(90).divide(BLOCK_DEG).floor();

var fold = bx.multiply(7).add(by.multiply(3)).mod(5).rename('fold').toInt();


// =====================================================================
// 7. BUILD SAMPLE IMAGE
// =====================================================================
// Uses the Model 2B stack so 2A and 2B see exactly the same pixels.

var sampleImage = features
  .select(BANDS_2B)
  .addBands(labels)
  .addBands(stratum)
  .addBands(fold)
  .updateMask(complete);


// =====================================================================
// 8. COUNT USABLE LABELS BY SURFACE
// =====================================================================

var hist = ee.Dictionary(
  stratum.updateMask(complete).reduceRegion({
    reducer: ee.Reducer.frequencyHistogram(),
    geometry: analysisBox,
    crs: labProj,
    maxPixels: 1e9,
    tileScale: 8
  }).get('stratum')
).getInfo();

print('Usable label pixels by stratum:', hist);


// =====================================================================
// 9. SURFACE-MATCHED SAMPLE COUNTS
// =====================================================================
// For every positive surface class: all positives, plus the same
// number of negatives from that surface.

var counts = {};
Object.keys(hist).forEach(function (k) {
  counts[Math.round(parseFloat(k))] = hist[k];
});

var classValues = [];
var classPoints = [];

Object.keys(counts).forEach(function (k) {
  var value = parseInt(k, 10);
  if (value >= 100) {
    var nPos = counts[value];
    var negativeStratum = value - 100;
    var nNegAvailable = counts[negativeStratum] || 0;

    classValues.push(value);            // all positives
    classPoints.push(nPos);

    classValues.push(negativeStratum);  // surface-matched negatives
    classPoints.push(Math.min(nPos, nNegAvailable));
  }
});

print('Strata sampled:', classValues);
print('Points per stratum:', classPoints);


// =====================================================================
// 10. DRAW FINAL BALANCED SAMPLE
// =====================================================================

var samples = sampleImage.stratifiedSample({
  numPoints: 0,
  classBand: 'stratum',
  classValues: classValues,
  classPoints: classPoints,
  region: analysisBox,
  projection: labProj,
  seed: 42,
  geometries: true,
  tileScale: 8
});

print('Samples per label:', samples.aggregate_histogram('label'));
print('Samples per stratum:', samples.aggregate_histogram('stratum'));
print('Positive samples per fold:',
  samples.filter(ee.Filter.eq('label', 1)).aggregate_histogram('fold'));
print('Negative samples per fold:',
  samples.filter(ee.Filter.eq('label', 0)).aggregate_histogram('fold'));


// =====================================================================
// 11. CLASSIFIER FACTORIES
// =====================================================================

function makeRF() {
  return ee.Classifier.smileRandomForest({
    numberOfTrees: 300,
    minLeafPopulation: 1,
    seed: 42
  });
}

// One split = one threshold on one feature.
function makeStump() {
  return ee.Classifier.smileCart({maxNodes: 2});
}


// =====================================================================
// 12. SPATIAL CROSS-VALIDATION
// =====================================================================
// Normal CLASSIFICATION output for CV metrics.

function crossValidate(bands, classifierFactory) {
  var foldResults = [0, 1, 2, 3, 4].map(function (k) {
    var train = samples.filter(ee.Filter.neq('fold', k));
    var test  = samples.filter(ee.Filter.eq('fold', k));
    var classifier = classifierFactory().train({
      features: train,
      classProperty: 'label',
      inputProperties: bands
    });
    return test.classify(classifier, 'pred');
  });
  return ee.FeatureCollection(foldResults).flatten();
}


// =====================================================================
// 13. METRIC REPORT
// =====================================================================

function report(name, tested) {
  var cm = tested.errorMatrix('label', 'pred', [0, 1]);
  var f1 = ee.Array(cm.fscore());

  print(name + ' — confusion matrix:', cm);
  print(name + ' — overall accuracy:', cm.accuracy());
  print(name + ' — recall / producers accuracy:', cm.producersAccuracy());
  print(name + ' — precision / consumers accuracy:', cm.consumersAccuracy());
  print(name + ' — F1 by class:', f1);
  print(name + ' — Macro-F1:', f1.get([0]).add(f1.get([1])).divide(2));
  print(name + ' — kappa:', cm.kappa());
}


// =====================================================================
// 14. RUN SPATIAL CROSS-VALIDATION
// =====================================================================

var cvBaseline = crossValidate(BASELINE_BANDS, makeStump);
report('BASELINE — one-split change threshold', cvBaseline);

var cv2A = crossValidate(BANDS_2A, makeRF);
report('MODEL 2A — RF optical only', cv2A);

var cv2B = crossValidate(BANDS_2B, makeRF);
report('MODEL 2B — RF optical + Sentinel-1', cv2B);

// ---- MODEL 2C — no pre-event bands (change + post + S1 only) ----
var BANDS_2C = POST.concat(DELTA).concat(SAR);
var cv2C = crossValidate(BANDS_2C, makeRF);
report('MODEL 2C — RF without pre-event bands', cv2C);

// =====================================================================
// 15. FINAL MODELS ON ALL BALANCED SAMPLES
// =====================================================================

var stumpFinal = makeStump().train({
  features: samples,
  classProperty: 'label',
  inputProperties: BASELINE_BANDS
});
print('Baseline learned rule:', stumpFinal.explain());

var rf2AClass = makeRF().train({
  features: samples,
  classProperty: 'label',
  inputProperties: BANDS_2A
});

var rf2BClass = makeRF().train({
  features: samples,
  classProperty: 'label',
  inputProperties: BANDS_2B
});


// =====================================================================
// 16. FEATURE IMPORTANCE
// =====================================================================

print('Model 2A feature importance:', ee.Dictionary(rf2AClass.explain()).get('importance'));
print('Model 2B feature importance:', ee.Dictionary(rf2BClass.explain()).get('importance'));


// =====================================================================
// 17. PROBABILITY MODELS
// =====================================================================
// MULTIPROBABILITY returns one probability per class, in class order:
//   element 0 = P(class 0), element 1 = P(class 1 = impacted)

var rf2AProb = makeRF().setOutputMode('MULTIPROBABILITY').train({
  features: samples,
  classProperty: 'label',
  inputProperties: BANDS_2A
});

var rf2BProb = makeRF().setOutputMode('MULTIPROBABILITY').train({
  features: samples,
  classProperty: 'label',
  inputProperties: BANDS_2B
});


// =====================================================================
// 18. PROBABILITY MAPS
// =====================================================================

var prob2A = features.select(BANDS_2A).classify(rf2AProb)
  .arrayGet([1]).rename('impact_prob');

var prob2B = features.select(BANDS_2B).classify(rf2BProb)
  .arrayGet([1]).rename('impact_prob');


// =====================================================================
// 19. DOMAIN / LAND MASK
// =====================================================================

var land = wc.neq(80);

var inDomain = wc.eq(30).or(wc.eq(40)).or(wc.eq(50)).or(wc.eq(60))
  .rename('in_domain');

prob2A = prob2A.updateMask(complete.and(land)).clip(analysisBox);
prob2B = prob2B.updateMask(complete.and(land)).clip(analysisBox);


// =====================================================================
// 20. MAP
// =====================================================================

var probPalette = ['2c7bb6', 'abd9e9', 'ffffbf', 'fdae61', 'd7191c'];

Map.centerObject(analysisBox, 11);
Map.setOptions('SATELLITE');

Map.addLayer(features, {bands: ['post_B4', 'post_B3', 'post_B2'], min: 0, max: 0.3},
  'Post-event S2', false);
Map.addLayer(prob2A, {min: 0, max: 1, palette: probPalette},
  'Impact likelihood — Model 2A', false);
Map.addLayer(prob2B, {min: 0, max: 1, palette: probPalette},
  'Impact likelihood — Model 2B', true);
Map.addLayer(inDomain.selfMask(), {palette: ['ffffff']},
  'Training-domain surfaces', false);
Map.addLayer(labels.eq(1).selfMask(), {palette: ['ff00ff']},
  'Positive proxy labels', false);
Map.addLayer(samples.filter(ee.Filter.eq('label', 1)), {color: 'ff00ff'},
  'Sampled positives', false);


// =====================================================================
// 21. EXPORT FINAL IMPACT SCORE — MODEL 2B
// =====================================================================
//
// impact_score:
//   Model 2B RF score for the impact class, 0–1.
//
//   IMPORTANT:
//   The model was trained using a deliberately balanced 50:50 sample.
//   Therefore this is a RELATIVE IMPACT-LIKELIHOOD SCORE,
//   NOT a calibrated probability of impact.
//
// in_domain:
//   1 = WorldCover 30/40/50/60
//       surfaces represented in model training
//
//   0 = other land-cover types such as trees, mangroves and wetlands.
//       These should be treated as "impact unknown" downstream.
//
// We preserve these areas in the exported asset and use the in_domain
// flag to mask them when displaying / routing.
// =====================================================================

var impactScore = prob2B
  .rename('impact_score')
  .toFloat();

var domainFlag = inDomain
  .unmask(0)
  .updateMask(prob2B.mask())
  .rename('in_domain')
  .toByte();

var finalImpact = impactScore
  .addBands(domainFlag);


Export.image.toAsset({

  image:
    finalImpact,

  description:
    'impact_score_v1',

  assetId:
    'projects/shore-gate-egress/assets/impact_score_v1',

  region:
    analysisBox,

  crs:
    labProj.crs().getInfo(),

  crsTransform:
    labProj.getInfo().transform,

  maxPixels:
    1e10,

  pyramidingPolicy: {
    'impact_score': 'mean',
    'in_domain': 'mode'
  }

});

/*

// =====================================================================
// 22. FREEZE THE TRAINING SAMPLE
// =====================================================================
// Run this from the Tasks tab so the exact training points are saved.

Export.table.toAsset({
  collection: samples,
  description: 'impact_samples_v1',
  assetId: 'projects/shore-gate-egress/assets/impact_samples_v1'
});
*/
