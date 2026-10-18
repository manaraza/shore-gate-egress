// =====================================================================
// 09c_check_features
// Shore-Gate: Egress
//
// QA CHECK FOR FROZEN MODEL 2 FEATURE STACK
//
// Feature asset:
//   projects/shore-gate-egress/assets/features_v1
//
// Labels:
//   projects/shore-gate-egress/assets/dpm_labels_v1_c3
//
// Model 2A:
//   Sentinel-2 pre + post + change features
//
// Model 2B:
//   Model 2A + Sentinel-1 VV/VH/VH-VV
//
// post_n_obs:
//   QA/confidence band only.
//   NOT used as an RF predictor.
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
// 2. LOAD FROZEN ASSETS
// =====================================================================

var labels = ee.Image(
  'projects/shore-gate-egress/assets/dpm_labels_v1_c3'
).select('label');


var features = ee.Image(
  'projects/shore-gate-egress/assets/features_v1'
);


var labProj = labels.projection();


print(
  'Feature asset:',
  features
);

print(
  'Feature projection:',
  features.projection()
);

print(
  'Label projection:',
  labProj
);

print(
  'Label nominal scale (m):',
  labProj.nominalScale()
);


// =====================================================================
// 3. EXPECTED FEATURE BAND NAMES
// =====================================================================

var ALL = [
  'B2',
  'B3',
  'B4',
  'B8',
  'B11',
  'B12',
  'NDVI',
  'NDWI',
  'NDBI'
];


function names(prefix) {

  return ALL.map(function(b) {
    return prefix + b;
  });

}


var preBands = names('pre_');

var postBands = names('post_');

var deltaBands = names('d_');


var sarBands = [
  'S1_VV',
  'S1_VH',
  'S1_VH_minus_VV'
];


var opticalBands = preBands
  .concat(postBands)
  .concat(deltaBands);


var model2BBands = opticalBands
  .concat(sarBands);


// =====================================================================
// 4. CHECK BAND COUNT / BAND NAMES
// =====================================================================

print(
  'Bands in frozen asset:',
  features.bandNames()
);


print(
  'Number of bands in frozen asset (31 expected):',
  features.bandNames().size()
);


print(
  'Model 2A predictor count (27 expected):',
  opticalBands.length
);


print(
  'Model 2B predictor count (30 expected):',
  model2BBands.length
);


// =====================================================================
// 5. MEMORY-EFFICIENT COMPLETE-CASE MASKS
// =====================================================================
//
// We do not need to examine all 27 optical masks simultaneously.
//
// If all PRE features exist
// AND all POST features exist,
// then the derived delta features are also supported.
//
// Likewise, if VV and VH exist,
// VH-VV is also supported.
// =====================================================================


// ---------------------------------------------------------------------
// PRE-EVENT VALIDITY
// ---------------------------------------------------------------------

var preValid = features
  .select(preBands)
  .mask()
  .reduce(
    ee.Reducer.min()
  )
  .gt(0)
  .rename('pre_valid')
  .toByte();


// ---------------------------------------------------------------------
// POST-EVENT VALIDITY
// ---------------------------------------------------------------------

var postValid = features
  .select(postBands)
  .mask()
  .reduce(
    ee.Reducer.min()
  )
  .gt(0)
  .rename('post_valid')
  .toByte();


// ---------------------------------------------------------------------
// MODEL 2A COMPLETE CASE
// ---------------------------------------------------------------------

var complete2A = preValid
  .and(postValid)
  .rename('complete')
  .toByte();


// ---------------------------------------------------------------------
// SENTINEL-1 VALIDITY
// ---------------------------------------------------------------------

var s1Valid = features
  .select([
    'S1_VV',
    'S1_VH'
  ])
  .mask()
  .reduce(
    ee.Reducer.min()
  )
  .gt(0)
  .rename('s1_valid')
  .toByte();


// ---------------------------------------------------------------------
// MODEL 2B COMPLETE CASE
// ---------------------------------------------------------------------

var complete2B = complete2A
  .and(s1Valid)
  .rename('complete')
  .toByte();


// =====================================================================
// 6. COUNT USABLE LABEL PIXELS
// =====================================================================

function usableCount(
  completeMask,
  cls
) {

  return completeMask
    .selfMask()
    .updateMask(
      labels.eq(cls)
    )
    .reduceRegion({

      reducer:
        ee.Reducer.count(),

      geometry:
        analysisBox,

      crs:
        labProj,

      maxPixels:
        1e9,

      tileScale:
        8

    })
    .get('complete');
}


// =====================================================================
// 7. PERCENTAGE OF LABELS USABLE
// =====================================================================

function totalLabelCount(cls) {

  return labels
    .eq(cls)
    .selfMask()
    .reduceRegion({

      reducer:
        ee.Reducer.count(),

      geometry:
        analysisBox,

      crs:
        labProj,

      maxPixels:
        1e9,

      tileScale:
        8

    })
    .get('label');
}


var totalPositive = ee.Number(
  totalLabelCount(1)
);

var totalNegative = ee.Number(
  totalLabelCount(0)
);


var usable2APos = ee.Number(
  usableCount(
    complete2A,
    1
  )
);

var usable2ANeg = ee.Number(
  usableCount(
    complete2A,
    0
  )
);


var usable2BPos = ee.Number(
  usableCount(
    complete2B,
    1
  )
);

var usable2BNeg = ee.Number(
  usableCount(
    complete2B,
    0
  )
);


// =====================================================================
// 8. PRINT TOTAL LABEL COUNTS
// =====================================================================

print(
  'Total positive proxy labels:',
  totalPositive
);

print(
  'Total available negative labels:',
  totalNegative
);


// =====================================================================
// 9. MODEL 2A RESULTS
// =====================================================================

print(
  'Model 2A usable positives:',
  usable2APos
);


print(
  'Model 2A usable positive %:',
  usable2APos
    .divide(totalPositive)
    .multiply(1000)
    .round()
    .divide(10)
);


print(
  'Model 2A usable negatives:',
  usable2ANeg
);


print(
  'Model 2A usable negative %:',
  usable2ANeg
    .divide(totalNegative)
    .multiply(1000)
    .round()
    .divide(10)
);


// =====================================================================
// 10. MODEL 2B RESULTS
// =====================================================================

print(
  'Model 2B usable positives:',
  usable2BPos
);


print(
  'Model 2B usable positive %:',
  usable2BPos
    .divide(totalPositive)
    .multiply(1000)
    .round()
    .divide(10)
);


print(
  'Model 2B usable negatives:',
  usable2BNeg
);


print(
  'Model 2B usable negative %:',
  usable2BNeg
    .divide(totalNegative)
    .multiply(1000)
    .round()
    .divide(10)
);


// =====================================================================
// 11. POST-EVENT OBSERVATION SUPPORT OVER POSITIVE LABELS
// =====================================================================
//
// post_n_obs is fractional after aggregation to ~31 m.
//
// We want to know whether positive pixels are mostly supported by:
//   ~1 clear observation
//   ~2 clear observations
//   or more.
// =====================================================================

var positiveNObsStats = features
  .select('post_n_obs')
  .updateMask(
    labels.eq(1)
  )
  .reduceRegion({

    reducer:
      ee.Reducer.minMax()
        .combine({

          reducer2:
            ee.Reducer.mean(),

          sharedInputs:
            true

        }),

    geometry:
      analysisBox,

    crs:
      labProj,

    maxPixels:
      1e9,

    tileScale:
      8

  });


print(
  'post_n_obs over positive labels (min / max / mean):',
  positiveNObsStats
);


// =====================================================================
// 12. OPTIONAL POST-OBSERVATION QUALITY COUNTS
// =====================================================================
//
// These are QA diagnostics.
//
// They do NOT remove anything yet.
// =====================================================================

function positiveObsCount(threshold) {

  var goodObs = features
    .select('post_n_obs')
    .gte(threshold)
    .selfMask()
    .updateMask(
      labels.eq(1)
    );


  return goodObs.reduceRegion({

    reducer:
      ee.Reducer.count(),

    geometry:
      analysisBox,

    crs:
      labProj,

    maxPixels:
      1e9,

    tileScale:
      8

  })
  .get('post_n_obs');
}


print(
  'Positive labels with post_n_obs >= 1:',
  positiveObsCount(1)
);


print(
  'Positive labels with post_n_obs >= 2:',
  positiveObsCount(2)
);


print(
  'Positive labels with post_n_obs >= 3:',
  positiveObsCount(3)
);


// =====================================================================
// 13. MAP
// =====================================================================

Map.centerObject(
  analysisBox,
  11
);

Map.setOptions(
  'SATELLITE'
);


// ---------------------------------------------------------------------
// FROZEN POST-EVENT RGB
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
  'Post-event S2 — frozen feature asset',
  true
);


// ---------------------------------------------------------------------
// MODEL 2A COMPLETE COVERAGE
// ---------------------------------------------------------------------

Map.addLayer(
  complete2A
    .selfMask(),
  {
    palette: [
      '00ff00'
    ]
  },
  'Usable for Model 2A',
  false
);


// ---------------------------------------------------------------------
// MODEL 2B COMPLETE COVERAGE
// ---------------------------------------------------------------------

Map.addLayer(
  complete2B
    .selfMask(),
  {
    palette: [
      '00ffff'
    ]
  },
  'Usable for Model 2B',
  false
);


// ---------------------------------------------------------------------
// POSITIVE LABELS
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
  'Post-event observation support',
  false
);


// =====================================================================
// END
//
// No export is performed from this script.
//
// After running, send:
//
//   Number of bands
//
//   Total positives / negatives
//
//   Model 2A:
//     usable positives
//     usable positive %
//     usable negatives
//     usable negative %
//
//   Model 2B:
//     usable positives
//     usable positive %
//     usable negatives
//     usable negative %
//
//   post_n_obs:
//     min
//     max
//     mean
//
//   positive counts with:
//     >= 1 observation
//     >= 2 observations
//     >= 3 observations
//
// =====================================================================
