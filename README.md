# Project Shore-Gate: Egress

Satellite and machine-learning decision support for post-disaster maritime-to-inland logistics.

**Course:** GEOG761 | **Client:** RNZN / GNZ Maritime
**Case study:** 2022 Hunga Tonga–Hunga Haʻapai eruption, Tongatapu

---

## What this does

Screens pre-nominated coastal access sites after a disaster and ranks them by whether
supplies can plausibly move *inland* from them. Outputs a ranked shortlist, per-site
access cards, and a reconnaissance priority list flagging where confidence is lowest.

**Scope boundary:** this does not assess the seaward approach (water depth, obstructions).
It assesses egress — whether cargo can leave the beach. Every site still requires field
verification.

---

## Pipeline

| Stage | Input | Output |
|---|---|---|
| 1. Impact mapping | Sentinel-1 SAR, Sentinel-2 optical (pre/post) | Random Forest classification: water/inundated, sand, bare ground, vegetation, infrastructure |
| 2. Friction surface | Land cover + Copernicus DEM slope + OSM road-impact overlay | Per-pixel relative movement cost |
| 3. Corridor modelling | Friction surface + site/destination points | Least-cost paths, coastal site → inland destination |
| 4. Site ranking | Corridor cost, hazard, connectivity, confidence | MCDA score + OAAT sensitivity results |

---

## Repo structure

```
data/           # gitignored — see "Data" below
notebooks/      # exploratory work, one owner each
src/            # shared functions (importable, reviewable)
params/         # parameter decisions — SINGLE SOURCE OF TRUTH
outputs/        # maps, figures, access cards
docs/           # proposal, write-up, partner correspondence
```

---

## Data

**Nothing in `data/` is committed.** A single Sentinel-2 tile is ~700MB; GitHub's
file cap is 100MB, and large files are painful to remove from history once added.

To reconstruct the dataset, see `data/README.md` for the exact scene IDs, dates and
download sources. Add any new scene you use to that file.

### Sources

| Dataset | Use | Access |
|---|---|---|
| Sentinel-1 GRD (IW, VV+VH) | Impact mapping through cloud/ash | Copernicus / GEE |
| Sentinel-2 L2A | Impact mapping, spectral indices | Copernicus / GEE |
| Copernicus DEM (GLO-30) | Slope for friction surface | Copernicus / GEE |
| OpenStreetMap | Road network baseline | Geofabrik / HOT |
| UNOSAT + Copernicus EMS | Reference labels for training/validation | UNOSAT, Copernicus EMS activations |

---

## Setup

```bash
git clone <repo-url>
cd shore-gate-egress
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## Working agreements

- **Parameters live in `params/parameters.md`.** If you change a threshold, weight or
  friction value, change it there and say why. Do not hardcode it in a notebook.
- **Notebooks have one owner each.** They diff badly; two people editing the same
  notebook produces unresolvable conflicts. Shared logic goes in `src/`.
- **Branch per feature**, PR into `main`. No direct pushes to `main`.
- **Commit messages:** what changed and why, not "update".

---

## Team

Danny Jung · Fuad Fachrudin · Mohd Allif Najmi bin Musa · Samana Raza · Shiyin Lin
