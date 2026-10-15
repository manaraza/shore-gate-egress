# Parameters — single source of truth

Every threshold, weight and value the analysis depends on lives here.
If you change one, change it here first and record why.

**Status key:** 🔴 undecided · 🟡 provisional · 🟢 agreed / frozen

---

## 1. Study area and event 🟢

| Parameter | Value | Rationale |
|---|---|---|
| Case study | Hunga Tonga–Hunga Haʻapai eruption and tsunami, Tongatapu | Ash blinded optical imagery at the moment of need. NZDF deployed. Confirmed with teacher. |
| Event time | 15 Jan 2022, 04:15 UTC | Used to split pre/post scenes |
| AOI | Rectangle `-175.3661011546799, -21.28198284420156` to `-175.02167858181292, -21.053702480502235` | Tongatapu admin boundary (~259.9 km²) + 1 km buffer (~394.4 km²). Teacher: buffer of at least 500 m or 1 km |
| CRS (storage) | EPSG:4326 for DPM-grid products; EPSG:32701 (UTM 1S) as 10 m working grid | DPM is delivered in EPSG:4326 |
| Candidate sites | Shoreline points every ~250 m around the island | Teacher: evaluate every possible landing place rather than pre-picking a few |
| Destinations | OSM `amenity=school / hospital / clinic / community_centre / place_of_worship` | Teacher-specified destination types |
| Movement profile | Off-road / unsealed-road capable logistics | Teacher-specified |

---

## 2. Imagery and preprocessing 🟢

### Sentinel-2

| Parameter | Value | Rationale |
|---|---|---|
| Collection | `COPERNICUS/S2_SR_HARMONIZED` | Harmonised L2A; consistent scale across the 25 Jan 2022 processing-baseline change |
| Pre-event (impact model) | Median, 1 Oct – 19 Dec 2021, `CLOUDY_PIXEL_PERCENTAGE < 70`, SCL-masked (48 granules) | Stops before Hunga Tonga activity began on 20 Dec 2021 |
| Pre-event (land-cover Model 1) | Oct – Dec 2021 clear composite | General land-cover baseline only |
| Post-event | Median, 17 – 24 Jan 2022 (dates 17, 19, 22, 24 Jan; 8 granules) | +2 to +9 days; brackets the 22 Jan ALOS-2 label date. Clear pixels from each date fill the others' cloud gaps |
| Post-event coverage | 79.3% of land; 77.7% of positive labels; 81.2% of negative labels | Remaining gaps = persistent cloud → no optical prediction → low data confidence / recon priority |
| Single-date screening | Best single date 17 Jan (55.7% clear land); 22 Jan 27.8%; 24 Jan 42.9%; 27 Jan 0.2% | 22 Jan too cloudy alone; 24 Jan clear over the western impact zone |
| Baseline offset | Handled by the harmonised collection; post-event window ends 24 Jan, before the 25 Jan baseline change | Teacher approved subtract-and-document approach |
| Cloud mask | SCL classes 0, 1, 3, 8, 9, 10, 11 removed | Visual comparison of RGB and SCL: medium/high cloud classes matched visible cloud; no snow-class confusion over ash-covered ground |
| Ground ash | **Not** masked | Ash on the ground is signal, not noise |
| Bands | B2, B3, B4, B8 (10 m), B11, B12 (20 m) | SWIR separates wet/dry, bare/built, ash |
| Indices | NDVI (B8,B4), NDWI (B3,B8), NDBI (B11,B8) | |

### Sentinel-1

| Parameter | Value | Rationale |
|---|---|---|
| Pre-event S1 | **None available for Tongatapu** | S1B failed 23 Dec 2021. Track 102: 3 Jan RAW covers 5.5% of AOI, 15 Jan RAW 5.4%. Track 95: no RAW on 3 or 15 Jan. Checked in GEE and ASF (`asf_search`). Documented as a data-availability finding |
| Post-event S1 | `COPERNICUS/S1_GRD`, 27 Jan 2022, track 102 descending, IW, VV+VH (1 scene, 100% coverage) | Only full-coverage post-event observation through cloud/ash |
| Processing | dB → linear power → spatial mean onto label grid → dB; VH − VV ratio added | Averaging in linear units; aggregation reduces speckle |
| Timing caveat | Acquired after the 22 Jan label date | Model is a retrospective reconstruction, not a real-time product |

---

## 3. Impact labels (ALOS-2 DPM) 🟢 — frozen as `dpm_labels_v1_c3`

**Source:** EOS-RS ALOS-2 Damage Proxy Map, 22 Jan 2022, v0.5. Pre-event images 9 Mar 2019 and
7 Mar 2020; post-event 22 Jan 2022. Whole-island coverage, 30.92 m (1 arc-second), EPSG:4326.
Teacher approved using this map for training labels instead of Sentinel-1.
The 27 Jan DPM (western Tongatapu only; 2019/2020 April pre-images) is a cross-check only.

**Decoding:** original GeoTIFF is RGBA; change is encoded in alpha (A = 138–255).
Score = (A − 137) / 118 × 100 → 0 = no displayed change, 1–100 = change, 255 = nodata.
The score is **ordinal** (position on the published colour ramp), not a physical percentage.
Asset: `projects/shore-gate-egress/assets/dpm_0122_score`.

| Label | Rule |
|---|---|
| 1 = strong-change impact proxy | DPM ≥ 59 ("red or darker"), on trusted surfaces, in a connected cluster (8-connected) of ≥ 3 pixels |
| 0 = low-change reference | DPM = 0, ≥ 90 m from any displayed DPM change, on the same trusted surfaces |
| Excluded | DPM 1–58; trees (10), shrubland (20), water (80), herbaceous wetland (90), mangroves (95) |
| Trusted surfaces | WorldCover 30, 40, 50, 60 (grass, crop, built-up, bare) — same for both classes |

**Why surfaces are matched:** with no surface restriction, 60% of positives were mangroves
(1,073 / 1,786), while negatives were only built-up/bare — the model would have learned land
cover instead of impact. Mangrove DPM change is also sensitive to tide state (L-band double bounce).

**Final counts**

| | Count |
|---|---|
| Positive pixels | 611 (grassland 370, built-up 233, bare 8, cropland 0) |
| Positive clusters | 126 separate places |
| Available negatives | 125,382 (grassland 117,013, built-up 8,075, bare 294) |
| DPM pixels in AOI | 312,926 |

**Cluster threshold comparison**

| MIN_CLUSTER | Pixels | Separate clusters |
|---|---|---|
| **3 (chosen)** | **611** | **126** |
| 5 | 333 | 43 |
| 9 | 148 | 13 |

≥ 3 keeps the most independent places for spatial validation. ≥ 5 is a candidate sensitivity check.

**Caveats:** some grassland positives may be agricultural change between the 2019/2020 reference
images and 2022. These are proxy labels, not field-observed ground truth.
WorldCover maps Tongatapu farmland as grassland (no cropland in either class).

---

## 4. Feature stack 🟢 — frozen as `features_v1`

| Parameter | Value |
|---|---|
| Grid | ~31 m DPM label grid (EPSG:4326, same transform as `dpm_labels_v1_c3`); 10 m working grid averaged onto it |
| Optical predictors (27) | `pre_` / `post_` / `d_` (post − pre) × B2, B3, B4, B8, B11, B12, NDVI, NDWI, NDBI |
| SAR predictors (3) | `S1_VV`, `S1_VH`, `S1_VH_minus_VV` |
| QA band (not a predictor) | `post_n_obs` — mean number of clear post-event observations; used for data confidence only |
| Asset | `projects/shore-gate-egress/assets/features_v1` |

---

## 5. Models 🟡

### Model 2 — impact likelihood (main model)

| Parameter | Value | Rationale |
|---|---|---|
| Name | "Impact likelihood", not "damage classification" | Labels are a change proxy |
| Model | Random Forest | Engineered features, limited labels, short timeline |
| Variants | 2A: optical only (27 predictors) · 2B: optical + S1 (30 predictors) | Ablation: does later SAR improve the classifier? |
| Training sample | All usable positives + equal number of negatives drawn in the same surface proportions | Removes class and surface imbalance |
| Validation | Spatially blocked hold-out | Prevents neighbouring-pixel leakage |
| Baseline | Simple optical change threshold | Answers "does the RF beat a simple rule?" |
| Metrics | Confusion matrix, precision, recall, F1, Macro-F1, feature importance | |
| Independent validation | Copernicus EMS EMSR558 (≈109 destroyed, ≈80 damaged structures) | Validation only, never training |
| EMSR558 road AUC (damaged+destroyed vs none, mean score) | 0.61 pooled (0.57–0.65); 0.58 within source image (0.53–0.62); cart tracks 0.79; local roads 0.51 | CIs from feature bootstrap, optimistic (no spatial blocking) |
| EMSR558 building mean score by grade | Destroyed 0.58, Damaged 0.61, Possibly damaged 0.50 vs built-up background 0.509 | Score detects clear damage; weak in villages |
| Impact coverage of routing land | ≈42% of passable land has valid Model 2 impact | Rest (mainly tree cover) = impact unknown → Data Confidence, never zero hazard |
| n_estimators / depth | *TBD* | |

### Model 1 — land cover (optional)

Trained on WorldCover-derived labels; its metrics measure **agreement with WorldCover**, not
accuracy. The friction surface uses WorldCover 2021 directly unless Model 1 clearly improves on it.

---

## 6. Friction surface and corridors 🟢 — frozen as `friction_v1`

**Profile:** off-road / unsealed-road capable logistics (teacher). Values are relative costs.
**Grid:** EPSG:32701, 10 m routing grid (WorldCover 10 m, Copernicus DEM ~30 m, Model 2B ~31 m).

`friction = base cost × slope multiplier × ash multiplier`

### Off-road base cost (WorldCover 2021)

| Surface | WorldCover | Friction | Status |
|---|---|---|---|
| Grassland / cropland | 30 / 40 | 3 | teacher |
| Bare / sparse | 60 | 3 | teacher |
| Sand (bare ground within 200 m of water) | 60 + rule | 4 | provisional |
| Shrubland | 20 | 6 | provisional |
| Tree cover (dense vegetation) | 10 | 8 | teacher |
| Herbaceous wetland | 90 | 8 | provisional |
| Built-up (non-road) | 50 | 10 | teacher |
| Mangroves | 95 | 10 | provisional |
| Water | 80 | Impassable | teacher |

### Roads

**Network:** OpenStreetMap snapshot dated 15 Jan 2022, distributed with Copernicus EMSR558.
Only geometry + road class used; EMS damage grades reserved for validation.

| Road class | Assumed surface | Base cost |
|---|---|---|
| Primary / Secondary / Local | Sealed (assumed) | 1.0 |
| Cart track | Unsealed | 1.5 |

- Rasterised with a 7.5 m buffer (≥ half pixel diagonal, keeps roads continuous); at overlaps the lowest cost wins.
- Roads crossing water keep road cost (causeway assumption — documented limitation).

### Impact on roads (continuous)

`C_road = C_base + S_excess × (C_surface − C_base)`

`S_excess = clamp((score − m_class) / (1 − m_class), 0, 1)`, mean within 50 m of the road

| WorldCover class | Reference level m_class (median Model 2B score) |
|---|---|
| Grassland (and cropland) | 0.311 |
| Built-up | 0.498 (matches EMSR558 built-up reference) |
| Bare / sparse | 0.599 |

- Rationale: built-up land scores ≈ 0.50 regardless of damage; raw scores would penalise all urban roads.
- Unknown impact (cloud gap / out-of-domain) → no penalty; `impact_confidence` lowered instead.

### Multipliers

| Modifier | Value |
|---|---|
| Slope < 5° | × 1 |
| Slope 5–15° | × 1.5 |
| Slope 15–30° | × 3 |
| Slope > 30° | Impassable off-road (0.009% of land) |
| Ash fall (EMSR558 extent) | × 1.0 baseline (extent covers 99.3% of land); 1.25 / 1.5 sensitivity only |

### Check results (v1)

| Check | Value |
|---|---|
| Road friction p5 / p50 / p95 | 1.01 / 1.52 / 3.81 |
| Island friction p5 / p50 / p95 | 1.52 / 3.0 / 12 |
| Road pixels with any impact evidence | 78.8% |
| Mean Model 2B coverage around roads | 0.534 |

| Parameter | Value |
|---|---|
| Corridor method | One cost-distance from all destinations, sampled at shoreline candidates; route lines traced for top sites only |
| Exported audit bands | friction, base_cost, road_class, road_impact, road_impact_raw, impact_coverage, impact_known, impact_confidence, slope_deg, slope_mult, ash_mult, lc_cost |

**Note:** road width is not measurable at 10 m. OSM class is used as a capacity proxy; width and
load capacity go on the reconnaissance list.

---

## 7. Buffers 🟢

Teacher: minimum 1 pixel, 5 pixels is safe, depending on sensor.

| Buffer | Value |
|---|---|
| AOI | 1 km |
| Road-impact overlay | 50 m (5 px at 10 m) |
| Training-sample edge | 2 px (20 m) inward |
| EMS polygon rasterisation | 1 px inward |
| DEM-based | In DEM pixels (5 px = 150 m) |
| Low-change reference distance from DPM change | 90 m (~3 DPM pixels) |

---

## 8. MCDA 🟡

All criteria Min-Max normalised to 0–1 benefit scale. Hazard and corridor cost are
reverse-scaled: `Hazard Safety = 1 − Normalised Hazard Exposure`.

`Score = 100 × [0.25(Hazard Safety) + 0.25(Corridor Efficiency) + 0.20(Road Connectivity) + 0.15(Destination Access) + 0.15(Data Confidence)]`

| Criterion | Weight | Status |
|---|---|---|
| Hazard Safety | 0.25 | 🟡 demonstrator — pending partner |
| Corridor Efficiency | 0.25 | 🟡 |
| Road Connectivity | 0.20 | 🟡 |
| Destination Access | 0.15 | 🟡 |
| Data Confidence | 0.15 | 🟡 |

| Parameter | Value | Rationale |
|---|---|---|
| Normalisation | Min-Max | Fixed candidate set limits rank-reversal risk |
| Sensitivity method | OAAT, ±20% per criterion | Conventional band; surfaces fragile rankings |

### Data Confidence — how computed 🟡

Proposed inputs:
- RF impact probability margin (distance from 0.5)
- Post-event optical availability around the site (`post_n_obs`; no optical = low confidence)
- DPM coverage at the site

*Exact formula TBD.*

---

## Open questions

| # | Question | Status |
|---|---|---|
| 1 | Confirm Hunga Tonga as demonstration case | ✅ confirmed |
| 2 | Candidate sites + inland destinations | ✅ teacher: evaluate all landing places; destinations = schools, hospitals/clinics, community centres, churches |
| 3 | Operational movement profile | ✅ teacher: off-road / unsealed road |
| 4 | MCDA weights vs operational priorities | pending partner |
| 5 | Existing Beach Landing Zones criteria | pending partner |
| 6 | Shareable field observations for validation | pending partner |
| 7 | Delivery time / update frequency | pending partner |
| 8 | "Impact likelihood" vs "damage" naming | pending teacher |

---

## Change log

| Date | Change | Who | Why |
|---|---|---|---|
| 2026-10-08 | AOI replaced with Tongatapu admin boundary + 1 km buffer rectangle | Samana | Earlier AOI covered the wrong island; teacher advised ≥ 500 m–1 km buffer |
| 2026-10-08 | Pre-event S1 declared unavailable | Samana | RAW coverage of AOI 5.5% (3 Jan) and 5.4% (15 Jan) on track 102; none on track 95 |
| 2026-10-08 | Impact labels switched from S1 change to ALOS-2 DPM | Samana | No pre-event S1; teacher approved the DPM for training labels |
| 2026-10-08 | Road-impact buffer 15 m → 50 m | Samana | Teacher: minimum 1 px, 5 px safe |
| 2026-10-12 | Friction table and slope multipliers added | Samana | Teacher: define own friction assumptions for off-road / unsealed profile |
| 2026-10-13 | Impact labels frozen (`dpm_labels_v1_c3`) | Samana | Surfaces matched between classes after 60% of positives were mangroves; MIN_CLUSTER = 3 keeps 126 clusters |
| 2026-10-13 | Post-event S2 = median 17–24 Jan 2022 | Samana | No single date usable (best 55.7% clear); composite covers 77.7% of positives |
| 2026-10-13 | Pre-event S2 for impact model ends 19 Dec 2021 | Samana | Avoid Hunga Tonga activity from 20 Dec 2021 |
| 2026-10-13 | Feature stack frozen (`features_v1`, 31 bands on label grid) | Samana | Includes 27 Jan S1 for Model 2A vs 2B comparison |
| 2026-10-14 | Impact model frozen: Model 2B (optical + S1), `impact_score_v1`. Spatial-block CV Macro-F1 0.695, kappa 0.39 (2A 0.679, 2C 0.682, baseline 0.526) | Samana | Best on all metrics; 2C shows most signal comes from change, post-event and S1 |
| 2026-10-15 | Friction surface frozen (`friction_v1`, 10 m, EPSG:32701). Roads degraded by impact EXCESS over WorldCover-class median reference (grass 0.311, built-up 0.498, bare 0.599); ash baseline ×1.0 (extent covers 99.3% of land; 1.25/1.5 for sensitivity); 7.5 m road rasterisation; road network = OSM snapshot 15 Jan 2022 from EMSR558 (geometry + class only) | Samana | Raw score penalised all urban roads (built-up reference ≈ 0.50, matching EMSR558 validation) |
