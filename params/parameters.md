# Parameters — single source of truth

Every threshold, weight and value the analysis depends on lives here.
If you change one, change it here first and record why.

**Status key:** 🔴 undecided · 🟡 provisional · 🟢 agreed

---

## 1. Study area and sites 🔴

| Parameter | Value | Rationale |
|---|---|---|
| Case study | Hunga Tonga eruption, 15 Jan 2022 | Ash blinded optical imagery at the moment of need — strongest justification for SAR. NZDF deployed. Full Sentinel coverage. |
| AOI | Tongatapu — *bounds TBD* | |
| Candidate sites (5–10) | *TBD — pending partner* | |
| Shoreline segment per site | *TBD* (~500 m–1 km?) | |
| Inland search extent | *TBD* (~5–10 km?) | Must reach real destinations without inflating LCP compute |
| Destination type | *TBD* | Road junction? Settlement? Hospital? Airfield? Defines LCP endpoints |

**Blocking:** everything downstream. Settle first.

---

## 2. Imagery and preprocessing 🔴

| Parameter | Value | Rationale |
|---|---|---|
| S2 pre-event scene | *TBD* — most recent clear scene before 15 Jan 2022 | |
| S2 post-event scene | *TBD* — first usable scene after | Record the gap; it's a finding |
| S1 pre/post scenes | *TBD* | GRD, IW mode |
| S2 bands | B2, B3, B4, B8 (10 m) + B11, B12 (20 m → resampled) | SWIR needed to separate wet/dry sand and bare/built |
| S1 polarisation | VV + VH | VV better for water; VH adds vegetation structure |
| Cloud masking | *TBD* — SCL / s2cloudless / Cloud Score+ | |
| SAR preprocessing | Terrain correction + speckle filter (refined Lee) | |

**Note:** compositing over dates isn't available — need first usable post-event scene,
not a clean median. Masked pixels become data gaps → low confidence → recon priority.

---

## 3. Classification 🟡

| Parameter | Value | Rationale |
|---|---|---|
| Classes | water/inundated, sand/beach, bare ground, vegetation, infrastructure/roads | |
| Model | Random Forest | Suits engineered features + limited labels + 6-week window |
| Baseline | Threshold change detection | Required for "does ML help?" comparison |
| Indices | NDWI, MNDWI, NDVI, BSI, NDBI | MNDWI over NDWI where water is turbid |
| Labels | UNOSAT + Copernicus EMS activations | |
| Validation | Spatially blocked cross-validation | Prevents neighbouring-pixel leakage |
| Metrics | Precision, recall, Macro-F1 (per class) | |
| n_estimators / depth | *TBD* | |

---

## 4. Friction surface and LCP 🔴

**Depends on:** operational movement profile (foot / recon team / light vehicle) —
pending partner. Different profiles produce completely different surfaces.

| Land class | Friction | Rationale |
|---|---|---|
| Road — primary | *TBD* | |
| Road — secondary/tertiary | *TBD* | |
| Road — track/unclassified | *TBD* | |
| Bare ground | *TBD* | |
| Sand | *TBD* | |
| Vegetation | *TBD* | |
| Water/inundated | *TBD* (impassable?) | |

| Parameter | Value | Rationale |
|---|---|---|
| Slope penalty function | *TBD* | |
| OSM impact buffer | 15 m 🟡 | ~1.5× Sentinel pixel — covers geolocation error and mixed edge pixels |
| Impacted-road penalty | *TBD* | |

**Note:** road *width* is not measurable at 10 m resolution. Use OSM class as capacity
proxy. Width and load-bearing capacity → reconnaissance list.

---

## 5. MCDA 🟡

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
| Normalisation | Min-Max | Candidate set is fixed and pre-nominated, so rank-reversal risk is limited |
| Sensitivity method | OAAT, ±20% per criterion | Conventional band; surfaces fragile rankings |

### Data Confidence — how computed 🔴

Currently undefined but worth 15% of the score. Proposed inputs:
- Random Forest class probability (not just predicted class)
- Cloud-mask coverage at the site
- SAR/optical agreement

*Method TBD.*

---

## Open questions with partner

| # | Question | Status |
|---|---|---|
| 1 | Confirm Hunga Tonga as demonstration case | sent / pending |
| 2 | Nominated sites + inland destinations | sent / pending |
| 3 | Operational movement profile | sent / pending |
| 4 | MCDA weights vs operational priorities | sent / pending |
| 5 | Existing Beach Landing Zones criteria | sent / pending |
| 6 | Shareable field observations for validation | sent / pending |
| 7 | Delivery time / update frequency | sent / pending |

---

## Change log

| Date | Change | Who | Why |
|---|---|---|---|
| | | | |
