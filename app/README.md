# Shore-Gate: Egress — partner interface (Streamlit)

Interactive screening of coastal landing sites on Tongatapu after the 2022 Hunga Tonga–Hunga Haʻapai
eruption: ranked sites, least-cost routes to hospitals, schools/clinics and community points, live
re-weighting of the MCDA, a robust-shortlist comparison, sensitivity, and a verify-first reconnaissance list.

> Decision-support prototype. All outputs must be verified by aerial reconnaissance and ground survey
> before operational use. No bathymetry, tide, surf or beach-gradient information is included.

## Run locally

```bash
cd app
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501.

## Deploy (Streamlit Community Cloud, free)

1. Push this repository to GitHub (the `app/` folder must include `data/`).
2. Go to share.streamlit.io → **Create app** → choose the repository and branch.
3. Main file path: `app/app.py`. Click **Deploy**.

## What the app shows

| Tab | Content |
|---|---|
| Map & ranking | Recommendation banner (top site + robust alternatives); candidate sites coloured by rank band (top 5 / 6–15 / 16+), top-N labels, hospital routes, hospitals, lagoon exclusion; optional impact, friction, schools/community and excluded-coast layers; live ranking table with change vs baseline |
| Compare shortlist | The sites that stay in the top five in all 12 sensitivity scenarios, side by side (route, road access, hazard, data confidence, rank range, verify-first flag), with a plain-language "why" sentence per site and a stacked score breakdown |
| Site card | Location (lat/lon, UTM 1S), "why this site" sentence, landing-zone evidence, routes to each tier (length, % on road, cost, slope), score breakdown |
| Route explorer | Up to 3 alternative routes between a landing point (ranked site or map click) and a destination (nearest per tier, list, or map click); post-event roads vs an undamaged-road counterfactual (same terrain, roads restored to undamaged cost); snap distance shown for clicked points; comparative route score; CSV export. Concept adapted from Irene's *Shore Gate Interactive Routing* app |
| Sensitivity | Ranks of the top 10 across 12 scenarios (baseline, ±20 % per weight, conservative unknown impact) |
| Verify first | Sites to check first by aerial reconnaissance and what to check (CSV) |
| Method & limits | Pipeline summary, validation numbers, limitations |

The MCDA engine in `app.py` is identical to notebook `15_routing_mcda_v2.ipynb`; with the proposal
weights it reproduces the notebook scores exactly.

## Files

| File | Purpose |
|---|---|
| `app.py` | The Streamlit app |
| `requirements.txt` | App dependencies only |
| `route_engine.py` | Alternative-route engine used by the Route explorer (MCP_Geometric + penalty method) |
| `data/` | Inputs prepared by `build_app_data.py` (≈5.4 MB, incl. `routing_grid.npz` for live routing) |
| `build_app_data.py` | Rebuilds `data/` from the routing stack, destinations and notebook outputs (needs rasterio, scikit-image, shapely, matplotlib) |
| `make_cards.py` | Printable landing-site cards (PNG + PDF) and the reconnaissance list |
| `cards/` | Generated cards for the top 10 sites |

Rebuild data and cards:

```bash
python build_app_data.py tongatapu_routing_stack_v2.tif \
    ../outputs/destinations/tongatapu_destinations_20220115.csv \
    ../outputs/destinations/tongatapu_destinations_20220115.geojson \
    ../outputs/routing/routing_v2
python make_cards.py tongatapu_routing_stack_v2.tif 10
```

## Data sources

Sentinel-1/2 (Copernicus), ALOS-2 Damage Proxy Map (EOS-RS/ARIA), ESA WorldCover 2021,
OpenStreetMap contributors (15 Jan 2022, ODbL), Copernicus EMS EMSR558. Basemap imagery © Esri, Maxar,
Earthstar Geographics.
