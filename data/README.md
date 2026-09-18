# Data provenance

Nothing in this folder is committed. This file is the record of what to download
so anyone can reconstruct the dataset.

**Add every scene you use.** If it isn't listed here, the pipeline isn't reproducible.

---

## Local structure (gitignored)

```
data/
  raw/           # untouched downloads
    s1/
    s2/
    dem/
    osm/
    reference/   # UNOSAT / Copernicus EMS
  interim/       # preprocessed — masked, corrected, indices computed
  processed/     # analysis-ready stacks
```

---

## Sentinel-2

| Role | Scene ID | Date | Tile | Cloud % | Source |
|---|---|---|---|---|---|
| Pre-event | | | | | |
| Post-event | | | | | |

Event date: **15 January 2022**. Pre-event = most recent usable scene before this.
Post-event = first usable scene after. **Record the gap** — time-to-usable-optical
is a reportable finding and motivates the SAR component.

## Sentinel-1

| Role | Scene ID | Date | Orbit | Mode/Pol | Source |
|---|---|---|---|---|---|
| Pre-event | | | | IW, VV+VH | |
| Post-event | | | | IW, VV+VH | |

Pre/post pairs should share orbit direction and relative orbit number — otherwise
backscatter differences reflect geometry, not change.

## Elevation

| Dataset | Version | Tiles | Source |
|---|---|---|---|
| Copernicus DEM GLO-30 | | | |

## Roads

| Dataset | Extract date | Region | Source |
|---|---|---|---|
| OpenStreetMap | | Tonga | Geofabrik / HOT |

OSM is live — record the extract date. Coverage changes, and post-disaster HOT
mapping may have improved Tonga coverage after Jan 2022. Check whether your extract
reflects pre- or post-event mapping effort.

## Reference labels

| Product | Activation ID | Date | Source |
|---|---|---|---|
| UNOSAT | | | |
| Copernicus EMS | | | |

---

## Notes

- Nothing here is behind a paywall — all sources are free/open. No commercial tasking.
- Google Maps data is **not** usable (licensing). Google Earth Engine is fine — it's a
  processing platform, not Maps data.
