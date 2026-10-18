// =====================================================================
// 13_build_friction_surface  (v5: impact excess over class reference,
//                              ash baseline 1.0)
// Shore-Gate: Egress — off-road / unsealed-capable logistics profile
//
// friction = base cost x slope multiplier x ash multiplier
//   base cost (off-road): WorldCover 2021 class costs (teacher table)
//   base cost (roads):    road base cost degraded CONTINUOUSLY:
//     C_road = C_base + S_excess x (C_surface - C_base)
//     S_excess = impact score EXCESS over the class-specific reference
//                level, mean within a 50 m neighbourhood:
//                excess = clamp((score - m_class) / (1 - m_class), 0, 1)
//                m_class = median Model 2B score for that WorldCover class.
//     Rationale: EMSR558 validation showed built-up land scores ~0.50
//     without known structural damage; the damage signal is the excess.
//     (Grass/bare reference levels are model-derived class medians.)
//     Unknown impact -> no penalty, lower impact_confidence.
//   slope: <5 deg x1 | 5-15 x1.5 | 15-30 x3 | >30 impassable (off-road)
//   ash:   EMSR558 ash-fall extent covers ~99% of land and therefore
//          provides little spatial discrimination in the baseline
//          routing surface. Baseline ASH_MULT = 1.0; 1.25 and 1.5 are
//          retained for sensitivity analysis.
//   water: impassable, except where a road crosses it (causeway
//          assumption: road keeps road cost; documented limitation)
//
// Road network: OpenStreetMap snapshot dated 15 Jan 2022, distributed
//   with Copernicus EMSR558. Only geometry + road class are used;
//   damage grades are reserved exclusively for independent validation.
//   "Sealed" for primary/secondary/local roads is an ASSUMPTION.
//
// Grid: EPSG:32701, 10 m ROUTING grid. Input resolutions differ:
//   WorldCover 10 m, Copernicus DEM ~30 m, Model 2B ~31 m.
//
// NOTE for ranking: unknown impact gets no friction penalty, so friction
//   is optimistic there. Low impact_confidence must be penalised in the
//   MCDA (Data Confidence) and tested in a conservative scenario.
// =====================================================================


// ---- 1. Area and grid -------------------------------------------------
var analysisBox = ee.Geometry.Rectangle(
  [-175.3661011546799, -21.28198284420156,
   -175.02167858181292, -21.053702480502235], null, false);

var CRS = 'EPSG:32701';
var SCALE = 10;


// ---- 2. Parameters (keep in sync with params/parameters.md) ----------
var LC_FROM = [10, 20, 30, 40, 50, 60, 90, 95];
var LC_TO   = [ 8,  6,  3,  3, 10,  3,  8, 10];
//            tree shrub grass crop built bare wetl mangrove
//            (shrub 6, wetland 8, mangrove 10 = PROVISIONAL)

var SAND_COST   = 4;     // bare ground within SAND_DIST_M of water (PROVISIONAL)
var SAND_DIST_M = 200;

var ROAD_COST = ee.Dictionary({
  '21120-Primary Road':   1.0,   // sealed (ASSUMED)
  '21121-Secondary Road': 1.0,   // sealed (ASSUMED)
  '21122-Local Road':     1.0,   // sealed (ASSUMED)
  '21124-Cart Track':     1.5    // unsealed
});

var ROAD_CLASS = ee.Dictionary({
  '21120-Primary Road': 1,
  '21121-Secondary Road': 1,
  '21122-Local Road': 1,
  '21124-Cart Track': 2
});

var ROAD_IMPACT_RADIUS_M = 50;   // 50 m neighbourhood (teacher)
var ROAD_RASTER_BUFFER_M = 7.5;  // >= half pixel diagonal (7.07 m): continuous, not over-wide
var ASH_MULT = 1.0;              // baseline; 1.25 / 1.5 for sensitivity only


// ---- 3. Land-cover base cost -----------------------------------------
var wc = ee.ImageCollection('ESA/WorldCover/v200').first().select('Map');

var lcCost = wc.remap(LC_FROM, LC_TO).toFloat();          // water -> masked

var nearWater = wc.eq(80).focal_max({radius: SAND_DIST_M, units: 'meters'});

lcCost = lcCost
  .where(wc.eq(60).and(nearWater), SAND_COST)
  .rename('lc_cost');


// ---- 4. Slope ----------------------------------------------------------
var demCol = ee.ImageCollection('COPERNICUS/DEM/GLO30')
  .filterBounds(analysisBox)
  .select('DEM');

var dem = demCol.mosaic().setDefaultProjection(demCol.first().projection());

var slope = ee.Terrain.slope(dem).rename('slope_deg');

var slopeMult = ee.Image(1).toFloat()
  .where(slope.gte(5), 1.5)
  .where(slope.gte(15), 3)
  .rename('slope_mult');

var tooSteep = slope.gt(30);


// ---- 5. Roads: geometry + class only, rasterised on the 10 m grid ------
var roads = ee.FeatureCollection('projects/shore-gate-egress/assets/emsr558_roads')
  .filter(ee.Filter.inList('info', ROAD_COST.keys()))
  .map(function (f) {
    return f.set({
      road_cost:  ROAD_COST.get(f.get('info')),
      road_class: ROAD_CLASS.get(f.get('info'))
    });
  });

print('Road segments by class:', roads.aggregate_histogram('info'));

var roadsRaster = roads.map(function (f) {
  return f.buffer(ROAD_RASTER_BUFFER_M);
});

var roadCost = roadsRaster
  .reduceToImage({properties: ['road_cost'], reducer: ee.Reducer.min()})
  .rename('road_cost')
  .reproject({crs: CRS, scale: SCALE});

var roadClass = roadsRaster
  .reduceToImage({properties: ['road_class'], reducer: ee.Reducer.min()})
  .rename('road_class')
  .toByte()
  .reproject({crs: CRS, scale: SCALE});

var isRoad = roadCost.mask().gt(0);


// ---- 6. Road degradation: impact EXCESS over class reference level -----
var impact  = ee.Image('projects/shore-gate-egress/assets/impact_score_v1');
var impProj = impact.select('impact_score').projection();

var impTrusted = impact.select('impact_score')
  .updateMask(impact.select('in_domain').eq(1));

// WorldCover on the Model 2B grid (modal class per ~31 m pixel)
var wc31 = wc
  .reduceResolution({reducer: ee.Reducer.mode(), maxPixels: 64})
  .reproject(impProj);

// Class-specific median Model 2B score used as a reference level
function classMedian(c) {
  return ee.Number(impTrusted.updateMask(wc31.eq(c)).reduceRegion({
    reducer: ee.Reducer.median(),
    geometry: analysisBox,
    crs: impProj,
    maxPixels: 1e9,
    tileScale: 8
  }).get('impact_score'));
}

var med30 = classMedian(30);   // grassland (cropland 40 uses the same)
var med50 = classMedian(50);   // built-up
var med60 = classMedian(60);   // bare / sparse

print('Class reference levels (median score) [grass, built-up, bare]:',
  ee.List([med30, med50, med60]));

var refLevel = wc31
  .remap([30, 40, 50, 60], ee.List([med30, med30, med50, med60]))
  .rename('ref_level');

// Excess over the class reference level, rescaled to 0-1
var impactExcess = impTrusted
  .subtract(refLevel)
  .divide(ee.Image(1).subtract(refLevel))
  .clamp(0, 1)
  .rename('impact_excess');

// Mean excess within the 50 m neighbourhood (masked pixels ignored)
var roadImpact = impactExcess
  .focal_mean({radius: ROAD_IMPACT_RADIUS_M, units: 'meters'})
  .rename('road_impact');

// Raw score kept for auditing only
var roadImpactRaw = impTrusted
  .focal_mean({radius: ROAD_IMPACT_RADIUS_M, units: 'meters'})
  .rename('road_impact_raw');

// Fraction of the 50 m neighbourhood with a trusted score (0-1)
var impactCoverage = impTrusted.mask().unmask(0).toFloat()
  .focal_mean({radius: ROAD_IMPACT_RADIUS_M, units: 'meters'})
  .rename('impact_coverage');

var impactKnown = impactCoverage.gt(0).rename('impact_known');

var sImpact = roadImpact.unmask(0).clamp(0, 1);            // unknown -> no penalty

// Surface under the road; where WorldCover says water (causeway), keep road cost
var surfaceUnder = lcCost.unmask(roadCost);

var roadEff = roadCost
  .add(sImpact.multiply(surfaceUnder.subtract(roadCost)))
  .rename('base_cost');

// Confidence in the IMPACT component only (1 off-road)
var impactConfidence = ee.Image(1).toFloat()
  .where(isRoad, impactCoverage.unmask(0))
  .rename('impact_confidence');


// ---- 7. Combine --------------------------------------------------------
var baseCost = lcCost.rename('base_cost').blend(roadEff);   // roads on top

var ash = ee.FeatureCollection('projects/shore-gate-egress/assets/emsr558_ash');

var ashMult = ee.Image(1).toFloat()
  .paint(ash, ASH_MULT)
  .rename('ash_mult');

var impassable = tooSteep.and(isRoad.not());

var friction = baseCost
  .multiply(slopeMult)
  .multiply(ashMult)
  .updateMask(impassable.not())
  .rename('friction');

var out = friction
  .addBands(baseCost.rename('base_cost'))
  .addBands(roadClass.unmask(0))
  .addBands(roadImpact.unmask(-1).updateMask(isRoad))
  .addBands(roadImpactRaw.unmask(-1).updateMask(isRoad))
  .addBands(impactCoverage.unmask(0).updateMask(isRoad))
  .addBands(impactKnown.unmask(0).updateMask(isRoad))
  .addBands(impactConfidence)
  .addBands(slope)
  .addBands(slopeMult)
  .addBands(ashMult)
  .addBands(lcCost)
  .clip(analysisBox);

print('Exported bands (12 expected):', out.bandNames());


// ---- 8. Checks ------------------------------------------------------------
var islandCheck = {geometry: analysisBox, scale: 30, maxPixels: 1e9,  tileScale: 8};
var roadCheck   = {geometry: analysisBox, scale: 10, maxPixels: 1e10, tileScale: 8};

print('Friction percentiles (5/25/50/75/95):',
  friction.reduceRegion(Object.assign({
    reducer: ee.Reducer.percentile([5, 25, 50, 75, 95])}, islandCheck)));

print('Mean Model 2B coverage on road pixels:',
  impactCoverage.updateMask(isRoad).reduceRegion(Object.assign({
    reducer: ee.Reducer.mean()}, roadCheck)));

print('Share of road pixels with any known impact:',
  impactKnown.updateMask(isRoad).reduceRegion(Object.assign({
    reducer: ee.Reducer.mean()}, roadCheck)));

print('Road impact EXCESS on roads (mean / 90th pct):',
  roadImpact.updateMask(isRoad).reduceRegion(Object.assign({
    reducer: ee.Reducer.mean().combine({
      reducer2: ee.Reducer.percentile([90]), sharedInputs: true})}, roadCheck)));

print('Road friction percentiles (5/50/95):',
  friction.updateMask(isRoad).reduceRegion(Object.assign({
    reducer: ee.Reducer.percentile([5, 50, 95])}, roadCheck)));


// ---- 9. Map ---------------------------------------------------------------
Map.setOptions('SATELLITE');

Map.addLayer(friction, {min: 1, max: 10, palette: ['1a9850', 'fee08b', 'd73027']},
  'Friction (green = easy, red = hard)');

Map.addLayer(roadImpact.updateMask(isRoad), {min: 0, max: 0.5,
  palette: ['2c7bb6', 'ffffbf', 'd7191c']}, 'Road impact EXCESS', false);

Map.addLayer(roadImpactRaw.updateMask(isRoad), {min: 0.3, max: 0.7,
  palette: ['2c7bb6', 'ffffbf', 'd7191c']}, 'Road impact RAW (audit)', false);

Map.addLayer(impactConfidence.updateMask(isRoad), {min: 0, max: 1,
  palette: ['ff00ff', 'ffffff']}, 'Road impact-data confidence (magenta = low)', false);

Map.addLayer(slope, {min: 0, max: 30}, 'Slope (deg)', false);

Map.addLayer(ash, {color: 'aaaaaa'}, 'EMSR558 ash-fall extent', false);

Map.setCenter(-175.2018, -21.1394, 15);   // Nuku'alofa, street level


// ---- 10. Export (run from Tasks ONLY after checking the map) -------------
Export.image.toAsset({
  image: out,
  description: 'friction_v1',
  assetId: 'projects/shore-gate-egress/assets/friction_v1',
  region: analysisBox,
  crs: CRS,
  scale: SCALE,
  maxPixels: 1e10,
  pyramidingPolicy: {
    'road_class': 'mode',
    'impact_known': 'mode',
    '.default': 'mean'
  }
});
