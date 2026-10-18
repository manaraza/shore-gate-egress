# Data

No raw data is stored in this repository. Inputs live in Google Earth Engine
(project `shore-gate-egress`) and Google Drive (`MyDrive/shoregate/`).
All rasters on the routing grid: EPSG:32701, 10 m, transform
`[10, 0, 669500, 0, -10, 7671040]`.

## Earth Engine assets (`projects/shore-gate-egress/assets/`)

| Asset | Made by | Contents |
|---|---|---|
| `dpm_0122_score` | upload | EOS-RS ALOS-2 Damage Proxy Map, 22 Jan 2022 |
| `dpm_labels_v1_c3` | `08_impact_labels` | Impact training labels (positives DPM ≥ 59, clusters ≥ 3; negatives DPM = 0, ≥ 90 m from change; WorldCover 30/40/50/60 only) |
| `features_v1` | `09b_build_features` | 31 bands on the DPM grid: 27 Sentinel-2 optical (pre 1 Oct–19 Dec 2021, post 17–24 Jan 2022) + 3 Sentinel-1 (27 Jan 2022, track 102 desc) + `post_n_obs` (QA only) |
| `impact_samples_v1` | `10_impact_rf` | 950 training points (475 + 475, surface-matched) |
| `impact_score_v1` | `10_impact_rf` | `impact_score` (RF probability, uncalibrated) + `in_domain` |
| `emsr558_roads`, `emsr558_buildings`, `emsr558_ash`, `emsr558_footprints` | upload | Copernicus EMSR558 AOI01 (Tongatapu) grading, Pleiades 17/18/20 Jan 2022 |
| `friction_v1` | `13_build_friction_surface` (v5) | 12 bands incl. `friction`, `impact_confidence`, `road_impact`, `road_class`, `slope_deg` |
| `destinations_20220115` | upload | 363 OSM destinations (15 Jan 2022), tiered |

## Google Drive (`MyDrive/shoregate/`)

| File | Made by | Used by |
|---|---|---|
| `tongatapu_routing_stack_v1.tif` | `14_export_routing_stack` | `15_routing_mcda` |
| `tongatapu_destinations_20220115.csv` | destination cleaning | `15_routing_mcda` |
| `emsr558_roads_scores_v2.csv`, `emsr558_buildings_scores_v2.csv` | `11_validate_impact_emsr558` | `16_validation_figures` |
| `routing_v1/` | `15_routing_mcda` | app, report |

## Routing stack bands (`tongatapu_routing_stack_v1.tif`)

| # | Band | Values |
|---|---|---|
| 1 | friction | 1–30; −1 = impassable / water / no data |
| 2 | impact_confidence | 0–1; missing → 0 (0 passable pixels affected) |
| 3 | road_impact | 0–1 on roads; −1 = off-road / unknown |
| 4 | road_class | 0 none, 1 sealed, 2 unsealed |
| 5 | slope_deg | degrees |
| 6 | worldcover | ESA WorldCover 2021 (v200) class; 0 = no data |

## Sources

- ESA WorldCover 2021 v200; Copernicus Sentinel-1 GRD and Sentinel-2 SR (harmonized), via Google Earth Engine
- EOS-RS / ARIA ALOS-2 Damage Proxy Map, 22 Jan 2022
- Copernicus Emergency Management Service, EMSR558 (Tonga), AOI01 grading products
- OpenStreetMap contributors (roads and destinations as of 15 Jan 2022), © OpenStreetMap contributors, ODbL
