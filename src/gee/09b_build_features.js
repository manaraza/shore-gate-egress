// =====================================================================
// 09b_build_features
// Shore-Gate: Egress
//
// BUILD + EXPORT FEATURE STACK FOR MODEL 2
//
// Pre-event:
//   Sentinel-2 median, 1 Oct - 19 Dec 2021
//   Stops before late-Dec volcanic activity.
//
// Post-event:
//   Sentinel-2 median, 17 - 24 Jan 2022
//   +2 to +9 days after eruption.
//   Brackets the 22 Jan ALOS-2 DPM label date.
//
// SAR:
//   Sentinel-1 GRD, 27 Jan 2022
//   Track 102, DESCENDING, VV + VH
//   Full Tongatapu coverage.
//
// IMPORTANT:
// Sentinel-1 was acquired AFTER the 22 Jan ALOS-2 label date.
// Therefore S1 is a retrospective predictor.
//
// Later:
//
//   Model 2A = S2 optical/change features only
//   Model 2B = S2 optical/change + S1
//
// Sentinel-2 SCL classes masked:
//   0  No data
//   1  Saturated / defective
//   3  Cloud shadow
//   8  Medium-probability cloud
//   9  High-probability cloud
//   10 Cirrus
//   11 Snow / ice
//
// post_n_obs is QA/confidence only.
// DO NOT use post_n_obs as an RF predictor.
//
// This script exports:
//
// projects/shore-gate-egress/assets/features_v1
// =====================================================================


// =====================================================================
// 1. STUDY AREA — FROZEN
// =====================================================================

var analysisBox = ee.Geometry.Rectangle(
  [
    -175.3661011546799,
    -21.28198284420156,
    -175.02167858181292,
    -21.053702480502235
  ],
  null,
  false
);


// =====================================================================
// 2. LOAD FINAL LABEL ASSET ONLY TO GET TARGET GRID
// =====================================================================

var labels = ee.Image(
  'projects/shore-gate-egress/assets/dpm_labels_v1_c3'
).select('label');

var labProj = labels.projection();

print('Label projection:', labProj);
print(
  'Label nominal scale (m):',
  labProj.nominalScale()
);


// =====================================================================
// 3. BAND DEFINITIONS
// =====================================================================

var BANDS = [
  'B2',
  'B3',
  'B4',
  'B8',
  'B11',
  'B12'
];


function names(prefix, list) {

  return list.map(function(b) {
    return prefix + b;
  });

}


// =====================================================================
// 4. SENTINEL-2 CLOUD MASK + REFLECTANCE SCALING
// =====================================================================

function maskS2(img) {

  var scl = img.select('SCL');

  var clear = scl.neq(0)
    .and(scl.neq(1))
    .and(scl.neq(3))
    .and(scl.neq(8))
    .and(scl.neq(9))
    .and(scl.neq(10))
    .and(scl.neq(11));

  return img
    .select(BANDS)
    .updateMask(clear)
    .divide(10000)
    .copyProperties(
      img,
      img.propertyNames()
    );
}


// =====================================================================
// 5. SENTINEL-2 COLLECTION
// =====================================================================

var s2 = ee.ImageCollection(
  'COPERNICUS/S2_SR_HARMONIZED'
)
  .filterBounds(analysisBox);


// ---------------------------------------------------------------------
// PRE-EVENT COLLECTION
// ---------------------------------------------------------------------

var preCol = s2
  .filterDate(
    '2021-10-01',
    '2021-12-20'
  )
  .filter(
    ee.Filter.lt(
      'CLOUDY_PIXEL_PERCENTAGE',
      70
    )
  )
  .map(maskS2);


// ---------------------------------------------------------------------
// POST-EVENT COLLECTION
//
// End date is exclusive.
// This includes 17, 19, 22 and 24 Jan acquisitions.
// ---------------------------------------------------------------------

var postCol = s2
  .filterDate(
    '2022-01-17',
    '2022-01-25'
  )
  .map(maskS2);


print(
  'Pre-event S2 granules:',
  preCol.size()
);

print(
  'Post-event S2 granules (17-24 Jan):',
  postCol.size()
);


// =====================================================================
// 6. PRE / POST SENTINEL-2 COMPOSITES
// =====================================================================

var pre = preCol
  .median()
  .rename(
    names('pre_', BANDS)
  );


var post = postCol
  .median()
  .rename(
    names('post_', BANDS)
  );


// ---------------------------------------------------------------------
// POST-EVENT OBSERVATION SUPPORT
//
// At native scale this is an integer count.
// After aggregation to ~31 m it can become fractional.
//
// QA ONLY — NOT AN RF FEATURE.
// ---------------------------------------------------------------------

var nObs = postCol
  .select('B4')
  .count()
  .rename('post_n_obs')
  .toFloat();


// =====================================================================
// 7. SENTINEL-1 — 27 JAN 2022
// =====================================================================
//
// Track 102
// Descending
// IW
// VV + VH
//
// GEE S1_GRD values are in dB.
//
// Convert each image to linear power first.
// Average same-acquisition coverage in linear units.
// =====================================================================

var s1Col = ee.ImageCollection(
  'COPERNICUS/S1_GRD'
)
  .filterBounds(analysisBox)
  .filterDate(
    '2022-01-27',
    '2022-01-28'
  )
  .filter(
    ee.Filter.eq(
      'instrumentMode',
      'IW'
    )
  )
  .filter(
    ee.Filter.eq(
      'relativeOrbitNumber_start',
      102
    )
  )
  .filter(
    ee.Filter.eq(
      'orbitProperties_pass',
      'DESCENDING'
    )
  )
  .filter(
    ee.Filter.listContains(
      'transmitterReceiverPolarisation',
      'VV'
    )
  )
  .filter(
    ee.Filter.listContains(
      'transmitterReceiverPolarisation',
      'VH'
    )
  )
  .select([
    'VV',
    'VH'
  ]);


print(
  'S1 scenes (27 Jan, track 102 DESC):',
  s1Col.size()
);


// ---------------------------------------------------------------------
// dB -> LINEAR POWER PER IMAGE
// ---------------------------------------------------------------------

var s1LinearCol = s1Col.map(
  function(img) {

    var linear = ee.Image(10)
      .pow(
        img.divide(10)
      )
      .rename([
        'VV',
        'VH'
      ]);

    return linear
      .copyProperties(
        img,
        img.propertyNames()
      );
  }
);


// ---------------------------------------------------------------------
// Mean of same-acquisition coverage in LINEAR units
// ---------------------------------------------------------------------

var s1lin = s1LinearCol
  .mean()
  .rename([
    'VV_lin',
    'VH_lin'
  ]);


// =====================================================================
// 8. COMMON WORKING STACK
// =====================================================================
//
// EPSG:32701 = UTM Zone 1 South
//
// We harmonise the source bands to a common working projection before
// reducing them onto the ~31 m DPM label grid.
//
// NOTE:
// B11/B12 are native 20 m, so this does not create new information.
// =====================================================================

var stackWorking = pre
  .addBands(post)
  .addBands(s1lin)
  .addBands(nObs)
  .setDefaultProjection({
    crs: 'EPSG:32701',
    scale: 10
  });


// =====================================================================
// 9. AGGREGATE TO ~31 m DPM LABEL GRID
// =====================================================================

var agg = stackWorking
  .reduceResolution({
    reducer: ee.Reducer.mean(),
    maxPixels: 128
  })
  .reproject(labProj);


// =====================================================================
// 10. SPECTRAL INDICES
// =====================================================================
//
// NDVI:
// (NIR - Red) / (NIR + Red)
//
// NDWI:
// (Green - NIR) / (Green + NIR)
//
// NDBI:
// (SWIR1 - NIR) / (SWIR1 + NIR)
// =====================================================================

function addIdx(img, prefix) {

  var ndvi = img
    .normalizedDifference([
      prefix + 'B8',
      prefix + 'B4'
    ])
    .rename(
      prefix + 'NDVI'
    );


  var ndwi = img
    .normalizedDifference([
      prefix + 'B3',
      prefix + 'B8'
    ])
    .rename(
      prefix + 'NDWI'
    );


  var ndbi = img
    .normalizedDifference([
      prefix + 'B11',
      prefix + 'B8'
    ])
    .rename(
      prefix + 'NDBI'
    );


  return img
    .addBands(ndvi)
    .addBands(ndwi)
    .addBands(ndbi);
}


// Six spectral bands + three indices

var ALL = BANDS.concat([
  'NDVI',
  'NDWI',
  'NDBI'
]);


// =====================================================================
// 11. PRE / POST FEATURE SETS
// =====================================================================

var pre9 = addIdx(
  agg.select(
    names('pre_', BANDS)
  ),
  'pre_'
);


var post9 = addIdx(
  agg.select(
    names('post_', BANDS)
  ),
  'post_'
);


// =====================================================================
// 12. PRE -> POST DIFFERENCE FEATURES
// =====================================================================
//
// IMPORTANT:
//
// pre9 bands have pre_ names.
// post9 bands have post_ names.
//
// Rename both temporarily to the SAME names before subtraction so:
//
// B2 is compared with B2
// NDVI with NDVI
// etc.
// =====================================================================

var preForDelta = pre9
  .rename(ALL);

var postForDelta = post9
  .rename(ALL);


var delta = postForDelta
  .subtract(preForDelta)
  .rename(
    names('d_', ALL)
  );


// =====================================================================
// 13. SENTINEL-1 BACK TO dB
// =====================================================================

var s1db = agg
  .select([
    'VV_lin',
    'VH_lin'
  ])
  .log10()
  .multiply(10)
  .rename([
    'S1_VV',
    'S1_VH'
  ]);


// VH - VV in dB

var s1ratio = s1db
  .select('S1_VH')
  .subtract(
    s1db.select('S1_VV')
  )
  .rename(
    'S1_VH_minus_VV'
  );


// =====================================================================
// 14. FINAL 31-BAND FEATURE STACK
// =====================================================================
//
// 9  pre-event optical
// 9  post-event optical
// 9  pre->post change
// 2  S1 backscatter
// 1  S1 VH-VV feature
// 1  post_n_obs QA band
//
// TOTAL = 31
// =====================================================================

var features = pre9
  .addBands(post9)
  .addBands(delta)
  .addBands(s1db)
  .addBands(s1ratio)
  .addBands(
    agg.select('post_n_obs')
  )
  .clip(analysisBox)
  .toFloat();


print(
  'Feature bands:',
  features.bandNames()
);

print(
  'Number of feature bands (31 expected):',
  features.bandNames().size()
);


// =====================================================================
// 15. LIGHTWEIGHT COVERAGE CHECKS
// =====================================================================
//
// These already ran successfully before and are cheap enough to keep.
//
// More expensive complete-case checks will be done in:
//
// 09c_check_features
//
// AFTER features_v1 has been exported.
// =====================================================================

var land = ee.ImageCollection(
  'ESA/WorldCover/v200'
)
  .first()
  .select('Map')
  .neq(80)
  .selfMask()
  .clip(analysisBox);


function pctCovered(
  band,
  maskImg
) {

  return features
    .select(band)
    .mask()
    .gt(0)
    .rename('v')
    .unmask(0)
    .updateMask(maskImg)
    .reduceRegion({

      reducer:
        ee.Reducer.mean(),

      geometry:
        analysisBox,

      crs:
        labProj,

      maxPixels:
        1e9,

      tileScale:
        4

    })
    .getNumber('v')
    .multiply(1000)
    .round()
    .divide(10);
}


print(
  '% land with post-event optical:',
  pctCovered(
    'post_B4',
    land
  )
);


print(
  '% POSITIVE labels with post-event optical:',
  pctCovered(
    'post_B4',
    labels.eq(1)
  )
);


print(
  '% negative labels with post-event optical:',
  pctCovered(
    'post_B4',
    labels.eq(0)
  )
);


print(
  '% POSITIVE labels with S1:',
  pctCovered(
    'S1_VV',
    labels.eq(1)
  )
);


// =====================================================================
// 16. MAP
// =====================================================================

Map.centerObject(
  analysisBox,
  11
);

Map.setOptions(
  'SATELLITE'
);


// ---------------------------------------------------------------------
// PRE-EVENT S2
// ---------------------------------------------------------------------

Map.addLayer(
  features,
  {
    bands: [
      'pre_B4',
      'pre_B3',
      'pre_B2'
    ],
    min: 0,
    max: 0.3
  },
  'Pre-event S2',
  false
);


// ---------------------------------------------------------------------
// POST-EVENT S2
// ---------------------------------------------------------------------

Map.addLayer(
  features,
  {
    bands: [
      'post_B4',
      'post_B3',
      'post_B2'
    ],
    min: 0,
    max: 0.3
  },
  'Post-event S2 (17-24 Jan)',
  true
);


// ---------------------------------------------------------------------
// POST OBSERVATION SUPPORT
// ---------------------------------------------------------------------

Map.addLayer(
  features.select(
    'post_n_obs'
  ),
  {
    min: 1,
    max: 4,
    palette: [
      'ff0000',
      'ffff00',
      '00ff00'
    ]
  },
  'Post optical observation support',
  false
);


// ---------------------------------------------------------------------
// NDVI CHANGE
// ---------------------------------------------------------------------

Map.addLayer(
  features.select(
    'd_NDVI'
  ),
  {
    min: -0.4,
    max: 0.4,
    palette: [
      'ff0000',
      'ffffff',
      '00aa00'
    ]
  },
  'NDVI change (red = loss)',
  false
);


// ---------------------------------------------------------------------
// SENTINEL-1 VV
// ---------------------------------------------------------------------

Map.addLayer(
  features.select(
    'S1_VV'
  ),
  {
    min: -20,
    max: 0
  },
  'S1 VV — 27 Jan (dB)',
  false
);


// ---------------------------------------------------------------------
// POSITIVE IMPACT-PROXY LABELS
// ---------------------------------------------------------------------

Map.addLayer(
  labels
    .eq(1)
    .selfMask(),
  {
    palette: [
      'ff00ff'
    ]
  },
  'Positive impact-proxy labels',
  false
);


// =====================================================================
// 17. EXPORT FROZEN FEATURE STACK
// =====================================================================
//
// Click:
//   Run
//   -> Tasks
//   -> features_v1
//   -> RUN
//   -> confirm
//
// Wait until COMPLETED.
//
// Then create:
//
//   09c_check_features
//
// =====================================================================

Export.image.toAsset({

  image:
    features,

  description:
    'features_v1',

  assetId:
    'projects/shore-gate-egress/assets/features_v1',

  region:
    analysisBox,

  crs:
    labProj.crs().getInfo(),

  crsTransform:
    labProj.getInfo().transform,

  maxPixels:
    1e10

});
