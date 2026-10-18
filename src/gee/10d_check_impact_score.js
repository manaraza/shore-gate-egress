// =====================================================================
// 10d_check_impact_score
// Verify final Model 2B impact-score asset
// =====================================================================

var analysisBox = ee.Geometry.Rectangle(
  [-175.3661011546799, -21.28198284420156,
   -175.02167858181292, -21.053702480502235],
  null, false
);

var impact = ee.Image(
  'projects/shore-gate-egress/assets/impact_score_v1'
);

print('Impact asset:', impact);
print('Bands:', impact.bandNames());
print('Projection:', impact.projection());

var score = impact.select('impact_score');
var domain = impact.select('in_domain');

print(
  'Impact-score min / max / mean (in-domain only):',
  score.updateMask(domain.eq(1)).reduceRegion({
    reducer: ee.Reducer.minMax()
      .combine({
        reducer2: ee.Reducer.mean(),
        sharedInputs: true
      }),
    geometry: analysisBox,
    scale: 31,
    maxPixels: 1e9,
    tileScale: 4
  })
);

print(
  'In-domain pixel counts:',
  domain.reduceRegion({
    reducer: ee.Reducer.frequencyHistogram(),
    geometry: analysisBox,
    scale: 31,
    maxPixels: 1e9,
    tileScale: 4
  })
);

Map.centerObject(analysisBox, 11);
Map.setOptions('SATELLITE');

Map.addLayer(
  score.updateMask(domain.eq(1)),
  {
    min: 0,
    max: 1,
    palette: [
      '2c7bb6',
      'abd9e9',
      'ffffbf',
      'fdae61',
      'd7191c'
    ]
  },
  'FINAL Model 2B impact score',
  true
);

Map.addLayer(
  domain.eq(0).selfMask(),
  {palette: ['808080']},
  'Out-of-domain / impact unknown',
  false
);
