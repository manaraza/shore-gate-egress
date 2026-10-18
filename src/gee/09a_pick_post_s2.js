// =====================================================================
// 09a_pick_post_s2
// Shore-Gate: Egress
//
// Rank post-event Sentinel-2 dates by apparent clear-land coverage
// over Tongatapu, then visually inspect RGB + SCL.
//
// IMPORTANT:
// - Ash is NOT treated as noise.
// - Sentinel-2 SCL may sometimes classify fresh ash as cloud/snow.
// - Therefore "clear_land_pct" is only a screening metric.
// - Final date choice must use visual inspection too.
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
// 2. LAND MASK
// =====================================================================
//
// WorldCover permanent water = 80
//
// We keep only land so the clear-percentage metric is not diluted by sea.
// =====================================================================

var worldCover = ee.ImageCollection('ESA/WorldCover/v200')
  .first()
  .select('Map')
  .clip(analysisBox);

var land = worldCover
  .neq(80)
  .selfMask();


// =====================================================================
// 3. POST-EVENT SENTINEL-2 COLLECTION
// =====================================================================
//
// Eruption date: 15 Jan 2022
//
// Search through the end of February.
// =====================================================================

var col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(analysisBox)
  .filterDate('2022-01-15', '2022-03-01');

print(
  'Total post-event Sentinel-2 granules:',
  col.size()
);


// =====================================================================
// 4. UNIQUE ACQUISITION DATES
// =====================================================================

var dates = col
  .aggregate_array('system:time_start')
  .map(function(t) {
    return ee.Date(t).format('YYYY-MM-dd');
  })
  .distinct();

print(
  'Unique post-event acquisition dates:',
  dates
);


// =====================================================================
// 5. CLEAR-LAND SCREENING METRIC
// =====================================================================
//
// SCL classes:
//
// 0  No data
// 1  Saturated / defective
// 2  Dark area pixels
// 3  Cloud shadow
// 4  Vegetation
// 5  Bare soils
// 6  Water
// 7  Unclassified
// 8  Cloud medium probability
// 9  Cloud high probability
// 10 Thin cirrus
// 11 Snow / ice
//
// For the screening metric we reject:
//
// 0, 1, 3, 8, 9, 10, 11
//
// We deliberately KEEP:
//
// 2, 4, 5, 6, 7
//
// because dark / bare / unclassified post-eruption surfaces may contain
// real ash / impact signal.
//
// IMPORTANT:
// SCL can still misclassify ash as cloud or snow.
// That is why we later inspect RGB + SCL manually.
// =====================================================================

var table = ee.FeatureCollection(
  dates.map(function(d) {

    d = ee.String(d);

    var start = ee.Date(d);
    var end = start.advance(1, 'day');

    var dayCol = col.filterDate(start, end);

    var dayMosaic = dayCol.mosaic();

    var scl = dayMosaic.select('SCL');


    // Apparent clear pixels according to SCL

    var clear = scl.neq(0)
      .and(scl.neq(1))
      .and(scl.neq(3))
      .and(scl.neq(8))
      .and(scl.neq(9))
      .and(scl.neq(10))
      .and(scl.neq(11));


    // Mean of 0/1 mask over land = clear fraction

    var clearFraction = clear
      .unmask(0)
      .updateMask(land)
      .reduceRegion({
        reducer: ee.Reducer.mean(),
        geometry: analysisBox,
        scale: 60,
        maxPixels: 1e9
      })
      .get('SCL');


    // Number of Sentinel-2 granules contributing on that date

    var granuleCount = dayCol.size();


    return ee.Feature(null, {

      date: d,

      clear_land_pct:
        ee.Number(clearFraction)
          .multiply(1000)
          .round()
          .divide(10),

      granules: granuleCount

    });

  })
);


// =====================================================================
// 6. PRINT DATE TABLES
// =====================================================================


// Ranked from highest apparent clear coverage to lowest

print(
  'Post-event dates ranked by apparent clear-land coverage:',
  table
    .sort('clear_land_pct', false)
    .reduceColumns(
      ee.Reducer.toList(3),
      [
        'date',
        'clear_land_pct',
        'granules'
      ]
    )
    .get('list')
);


// Chronological view

print(
  'Post-event dates chronologically:',
  table
    .sort('date')
    .reduceColumns(
      ee.Reducer.toList(3),
      [
        'date',
        'clear_land_pct',
        'granules'
      ]
    )
    .get('list')
);


// =====================================================================
// 7. DATE INSPECTION FUNCTION
// =====================================================================
//
// For a chosen date this displays:
//
// 1. RGB
// 2. Full SCL classification
// 3. SCL rejected pixels
// 4. High-confidence cloud/cirrus only
// 5. SCL snow pixels separately
//
// This helps identify where ash may be mistaken for cloud/snow.
// =====================================================================

function showDate(dateString) {

  var start = ee.Date(dateString);
  var end = start.advance(1, 'day');


  var dayCol = col.filterDate(start, end);


  print(
    'Granules on ' + dateString + ':',
    dayCol.size()
  );


  var dayImage = dayCol
    .mosaic()
    .clip(analysisBox);


  var scl = dayImage.select('SCL');


  // -------------------------------------------------------------------
  // RGB
  // -------------------------------------------------------------------

  Map.addLayer(
    dayImage,
    {
      bands: ['B4', 'B3', 'B2'],
      min: 0,
      max: 3000
    },
    'RGB ' + dateString,
    true
  );


  // -------------------------------------------------------------------
  // FULL SCL
  // -------------------------------------------------------------------

  Map.addLayer(
    scl,
    {
      min: 0,
      max: 11,
      palette: [
        '000000',  // 0 No data
        'ff0000',  // 1 Saturated / defective
        '2f2f2f',  // 2 Dark area pixels
        '643200',  // 3 Cloud shadow
        '00a000',  // 4 Vegetation
        'ffe65a',  // 5 Bare soils
        '0000ff',  // 6 Water
        '808080',  // 7 Unclassified
        'c0c0c0',  // 8 Medium-prob cloud
        'ffffff',  // 9 High-prob cloud
        'a0e0ff',  // 10 Cirrus
        'ff96ff'   // 11 Snow / ice
      ]
    },
    'SCL ' + dateString,
    false
  );


  // -------------------------------------------------------------------
  // ALL PIXELS REJECTED BY THE SCREENING MASK
  // -------------------------------------------------------------------
  //
  // Includes:
  // 1  defective
  // 3  shadow
  // 8  medium cloud
  // 9  high cloud
  // 10 cirrus
  // 11 snow
  //
  // If this magenta layer overlaps obvious grey ash-covered ground in
  // RGB, then SCL is probably underestimating the true usability.
  // -------------------------------------------------------------------

  var rejected = scl.eq(1)
    .or(scl.eq(3))
    .or(scl.eq(8))
    .or(scl.eq(9))
    .or(scl.eq(10))
    .or(scl.eq(11));

  Map.addLayer(
    rejected.selfMask(),
    {
      palette: ['ff00ff']
    },
    'SCL rejected pixels ' + dateString,
    false
  );


  // -------------------------------------------------------------------
  // HIGH-CONFIDENCE CLOUD / CIRRUS ONLY
  // -------------------------------------------------------------------
  //
  // This is useful because high-probability cloud and cirrus are usually
  // more trustworthy than medium-probability cloud.
  // -------------------------------------------------------------------

  var highCloud = scl.eq(9)
    .or(scl.eq(10));

  Map.addLayer(
    highCloud.selfMask(),
    {
      palette: ['ffffff']
    },
    'High-confidence cloud/cirrus ' + dateString,
    false
  );


  // -------------------------------------------------------------------
  // MEDIUM-PROBABILITY CLOUD
  // -------------------------------------------------------------------
  //
  // These pixels deserve particular visual checking because unusual
  // post-eruption surface conditions may be confused with cloud.
  // -------------------------------------------------------------------

  var mediumCloud = scl.eq(8);

  Map.addLayer(
    mediumCloud.selfMask(),
    {
      palette: ['ff8800']
    },
    'Medium-prob cloud ' + dateString,
    false
  );


  // -------------------------------------------------------------------
  // SNOW / ICE CLASS
  // -------------------------------------------------------------------
  //
  // Snow is extremely unlikely on Tongatapu.
  //
  // If SCL = 11 appears over land here, it is particularly suspicious
  // and may represent ash / unusual bright surface conditions.
  // -------------------------------------------------------------------

  var snow = scl.eq(11);

  Map.addLayer(
    snow.selfMask(),
    {
      palette: ['ff00ff']
    },
    'SCL snow class ' + dateString,
    false
  );


  // -------------------------------------------------------------------
  // APPARENTLY CLEAR MASK
  // -------------------------------------------------------------------

  var clear = scl.neq(0)
    .and(scl.neq(1))
    .and(scl.neq(3))
    .and(scl.neq(8))
    .and(scl.neq(9))
    .and(scl.neq(10))
    .and(scl.neq(11));

  Map.addLayer(
    clear.selfMask().updateMask(land),
    {
      palette: ['00ff00']
    },
    'Apparently clear land ' + dateString,
    false
  );

}


// =====================================================================
// 8. MAP SETUP
// =====================================================================

Map.centerObject(
  analysisBox,
  11
);

Map.setOptions(
  'SATELLITE'
);

Map.addLayer(
  analysisBox,
  {
    color: 'white'
  },
  'Analysis box',
  false
);


// =====================================================================
// 9. INSPECT A CANDIDATE DATE
// =====================================================================
//
// Start with 17 Jan.
//
// After running this script:
//
// 1. Look at the ranked date table.
// 2. Identify the best EARLY dates.
// 3. Change this date and re-run.
// 4. Compare:
//      RGB
//      SCL
//      SCL rejected pixels
//      medium cloud
//      snow class
//
// Do NOT choose a date based only on clear_land_pct.
//
// =====================================================================

showDate('2022-01-17');


// =====================================================================
// OPTIONAL:
// To compare multiple dates at once, uncomment these one by one.
//
// showDate('2022-01-22');
// showDate('2022-01-27');
// showDate('2022-02-01');
//
// Too many dates at once will clutter the Layers panel.
// =====================================================================
showDate('2022-01-17');
showDate('2022-01-19');
showDate('2022-01-22');
showDate('2022-01-24');
