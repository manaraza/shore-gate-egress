# %% [markdown]
# # 15 — Shore-Gate: Egress · landing candidates, least-cost access, MCDA (v2)
# 
# **Inputs (Google Drive → `MyDrive/shoregate/`)**
# - `tongatapu_routing_stack_v2*.tif` — frozen friction stack plus all-surface Model 2B impact-excess/validity bands
# - `tongatapu_destinations_20220115.csv` — cleaned historical destinations (363 records)
# 
# **Key safeguards**
# - Main-island landing candidates are limited to the **open-sea coast**. Fangaʻuta/Fangakakau Lagoon is connected to the sea, so an edge-connectivity test alone treats it as ocean. The notebook closes the lagoon mouth along the lagoon's published northern bound (21.1534° S) and removes **all water connected to the lagoon basin** behind that line (≈ 28 km², including the northern arm and southern lobe that extend beyond the published bounding box).
# - Tree-covered coast remains eligible; mangrove/wetland frontage and steep/cliff shore are hard exclusions.
# - Road distance is **not** a hard filter; it remains an MCDA criterion.
# - Hazard Safety uses **all-surface impact excess above the WorldCover-class reference level**, not the road-only impact band.

# %%
# !pip -q install rasterio

import glob, json, math, os, time
import numpy as np
import pandas as pd
import rasterio
from rasterio.merge import merge
from rasterio.transform import rowcol, xy
from pyproj import Transformer
from scipy import ndimage as ndi
from skimage.graph import MCP_Geometric

# %% [markdown]
# ## 1. Paths and parameters (keep in sync with `params/parameters.md`)

# %%
IN_COLAB = os.path.exists('/content')
if IN_COLAB:
    from google.colab import drive
    drive.mount('/content/drive')
    WORK = '/content/drive/MyDrive/shoregate'
else:
    WORK = os.environ.get('SHOREGATE_WORK', '.')

STACK_GLOB = os.path.join(WORK, 'tongatapu_routing_stack_v2*.tif')
DEST_CSV   = os.path.join(WORK, 'tongatapu_destinations_20220115.csv')
OUT        = os.path.join(WORK, 'routing_v2')
os.makedirs(OUT, exist_ok=True)

PIX = 10.0                      # metres per routing pixel
CAND_SPACING_M   = 500          # candidate thinning distance
MANGROVE_R_M     = 50           # frontage window for mangrove / wetland share
MANGROVE_MAX     = 0.5          # exclude if > 50 % mangrove/wetland within 50 m
CLIFF_R_M        = 100          # look-around window for cliffs
CLIFF_SLOPE_DEG  = 15           # exclude if any slope > 15 deg within 100 m
SNAP_R_M         = 60           # snap a point to nearest passable pixel
LANDING_ZONE_R_M = 250          # landing-zone window for impact/confidence
TOP_N_ROUTES     = 10           # trace route geometries only for top sites
SEED             = 42

# Fangaʻuta/Fangakakau lagoon. The lagoon is connected to the sea, so
# "water touching the map edge" is not enough. We close the lagoon mouth with
# a line along its published northern bound (SPREP: 21.1534 S) and remove all
# water connected to the lagoon basin behind it. A bounding box alone is NOT
# enough: the lagoon's northern arm and southern lobe extend beyond it
# (tested: 20 lagoon-shore candidates survive a box-only screen).
LAGOON_MOUTH_LAT      = -21.1534                 # published northern bound
LAGOON_MOUTH_LON      = (-175.1750, -175.1077)   # mouth line, west -> east
LAGOON_SEED_LONLAT    = (-175.1278, -21.1681)    # a point in the main basin
LAGOON_EXPECT_KM2     = (20, 40)                 # sanity range (tested: 28.2)

WEIGHTS = {
    'hazard_safety':       0.25,
    'corridor_efficiency': 0.25,
    'road_connectivity':   0.20,
    'destination_access':  0.15,
    'data_confidence':     0.15,
}
TIER_NAMES = {1: 'hospital', 2: 'school/clinic', 3: 'community/worship'}


# %% [markdown]
# ## 2. Load the routing stack (joins GEE tiles automatically)

# %%
files = sorted(glob.glob(STACK_GLOB))
assert files, f'No stack found at {STACK_GLOB}'
print('Stack files:', [os.path.basename(f) for f in files])

if len(files) == 1:
    with rasterio.open(files[0]) as src:
        stack = src.read().astype('float32')
        transform, crs = src.transform, src.crs
        desc = src.descriptions
else:
    srcs = [rasterio.open(f) for f in files]
    stack, transform = merge(srcs, nodata=-1)
    stack = stack.astype('float32')
    crs, desc = srcs[0].crs, srcs[0].descriptions
    for s in srcs:
        s.close()

BANDS = [
    'friction',
    'impact_confidence',   # road-impact coverage helper (audit)
    'road_impact',         # road impact excess (audit)
    'road_class',
    'slope_deg',
    'worldcover',
    'impact_excess_all',   # all-surface impact excess, valid domain only
    'impact_valid_all'     # 1 where all-surface impact excess is valid
]
assert stack.shape[0] == len(BANDS), (
    f'Expected {len(BANDS)} bands, got {stack.shape[0]}. '
    'Use tongatapu_routing_stack_v2.'
)
if desc and all(desc) and list(desc) != BANDS:
    print('NOTE: band descriptions in file:', desc)

(friction, imp_conf_road, road_imp, road_cls, slope, wc,
 impact_excess_all, impact_valid_all) = stack

wc = np.where(np.isfinite(wc), wc, 0).astype('int16')
road_cls = np.where(np.isfinite(road_cls), road_cls, 0).astype('int8')
impact_valid_all = (np.isfinite(impact_valid_all) & (impact_valid_all > 0.5)
                    & np.isfinite(impact_excess_all) & (impact_excess_all >= 0))
print(f'Valid all-surface impact pixels: {impact_valid_all.mean():.1%} of grid')

H, W = friction.shape
print(f'Grid {H} x {W} px, CRS {crs}, pixel {transform.a:.1f} m')
print('Bands:', BANDS)

passable = np.isfinite(friction) & (friction > 0)
cost = np.where(passable, friction, np.inf).astype('float64')


# %% [markdown]
# ## 3. Open-sea coastline of the main island
# 
# A simple “water connected to the raster edge = ocean” rule is **not sufficient** on Tongatapu: Fangaʻuta/Fangakakau Lagoon is connected to the sea, and in the 10 m WorldCover water mask the connection is more than 1 km wide, so no width threshold separates it either.
# 
# The notebook therefore:
# 1. draws a short barrier line across the lagoon mouth along the lagoon's published northern bound (21.1534° S);
# 2. takes all water connected to a seed point in the main basin behind that line as **lagoon** (checked: must not touch the map edge, area ≈ 28 km²);
# 3. treats the remaining edge-connected water as **open sea**;
# 4. keeps only the shoreline of the main Tongatapu land component next to open sea.
# 
# Tested on the real stack: naive rule 164 candidates (59 on the lagoon shore); published bounding box only 131 (20 still on the lagoon shore); this method 108 (0).

# %%
water = (wc == 80) | (wc == 0)          # 0 = outside the export / no data

# Main Tongatapu land component.
land = ~water
lab_l, n_l = ndi.label(land, structure=np.ones((3, 3)))
sizes = ndi.sum(land, lab_l, index=np.arange(1, n_l + 1))
main_id = int(np.argmax(sizes)) + 1
main = lab_l == main_id

# --- Lagoon: close the mouth, then flood-fill from a seed in the basin ---
to_grid = Transformer.from_crs('EPSG:4326', crs, always_xy=True)

def lonlat_to_rc(lon, lat):
    x, y = to_grid.transform(lon, lat)
    r, c = rowcol(transform, x, y)
    return int(r), int(c)

(ra, ca) = lonlat_to_rc(LAGOON_MOUTH_LON[0], LAGOON_MOUTH_LAT)
(rb, cb) = lonlat_to_rc(LAGOON_MOUTH_LON[1], LAGOON_MOUTH_LAT)
n_pts = abs(cb - ca) + 1
line_r = np.round(np.linspace(ra, rb, n_pts)).astype(int)
line_c = np.round(np.linspace(ca, cb, n_pts)).astype(int)
barrier = np.zeros_like(water)
for d in (-1, 0, 1):                                  # 3 px thick, no diagonal leaks
    barrier[np.clip(line_r + d, 0, H - 1), np.clip(line_c, 0, W - 1)] = True

lab_cut, _ = ndi.label(water & ~barrier)
seed_rc = lonlat_to_rc(*LAGOON_SEED_LONLAT)
assert water[seed_rc], 'Lagoon seed is not on water - check LAGOON_SEED_LONLAT'
lagoon = lab_cut == lab_cut[seed_rc]

lagoon_km2 = lagoon.sum() * PIX * PIX / 1e6
touches_edge = lagoon[0].any() or lagoon[-1].any() or lagoon[:, 0].any() or lagoon[:, -1].any()
assert not touches_edge, 'Lagoon leaked to the map edge - mouth line does not close it'
assert LAGOON_EXPECT_KM2[0] <= lagoon_km2 <= LAGOON_EXPECT_KM2[1], f'Lagoon area {lagoon_km2:.1f} km2 out of range'

# --- Open sea = water connected to the map edge, excluding the lagoon ---
lab_w, n_w = ndi.label(water & ~lagoon)
edge_labels = np.unique(np.concatenate([lab_w[0], lab_w[-1], lab_w[:, 0], lab_w[:, -1]]))
edge_labels = edge_labels[edge_labels > 0]
ocean = np.isin(lab_w, edge_labels)

coast = main & ndi.binary_dilation(ocean, structure=ndi.generate_binary_structure(2, 1))

print(f'Main island area: {main.sum() * PIX * PIX / 1e6:.1f} km2 (other land parts: {n_l - 1})')
print(f'Lagoon (Fangaʻuta/Fangakakau) excluded: {lagoon_km2:.1f} km2')
print(f'Other enclosed water excluded: {(water & ~ocean & ~lagoon).sum() * PIX * PIX / 1e6:.2f} km2')
print(f'Open-sea coast pixels: {int(coast.sum()):,}')


# %% [markdown]
# ## 4. Screening: mangrove / wetland frontage, cliffs, passability

# %%
def disk(r_px):
    y, x = np.ogrid[-r_px:r_px + 1, -r_px:r_px + 1]
    return (x * x + y * y) <= r_px * r_px

def window_mean(mask, r_m):
    k = disk(int(round(r_m / PIX))).astype('float32')
    num = ndi.convolve(mask.astype('float32'), k, mode='constant')
    den = ndi.convolve(np.ones_like(mask, dtype='float32'), k, mode='constant')
    return num / den

mangrove_share = window_mean(np.isin(wc, [90, 95]), MANGROVE_R_M)
cliff_max = ndi.maximum_filter(np.where(main, slope, 0), footprint=disk(int(CLIFF_R_M / PIX)))

rr, cc = np.nonzero(coast)
reason = np.full(rr.size, '', dtype=object)
reason[mangrove_share[rr, cc] > MANGROVE_MAX] = 'mangrove/wetland frontage'
reason[(reason == '') & (cliff_max[rr, cc] > CLIFF_SLOPE_DEG)] = 'cliff / steep shore'

# snap each coast pixel to the nearest passable pixel (coast pixels can be impassable edges)
snap_dist, (sr, sc) = ndi.distance_transform_edt(~passable, return_indices=True)
too_far = snap_dist[rr, cc] * PIX > SNAP_R_M
reason[(reason == '') & too_far] = 'no passable land within snap distance'
eligible = reason == ''
print(pd.Series(np.where(eligible, 'ELIGIBLE', reason)).value_counts())

# %% [markdown]
# ## 5. Thin to ~500 m spacing (greedy, grid-hashed, reproducible)

# %%
def thin(rows, cols, spacing_px, seed=SEED):
    order = np.random.default_rng(seed).permutation(rows.size)
    cell = spacing_px
    grid, keep = {}, []
    for i in order:
        r, c = rows[i], cols[i]
        gr, gc = r // cell, c // cell
        ok = True
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for (r2, c2) in grid.get((gr + dr, gc + dc), ()):
                    if (r - r2) ** 2 + (c - c2) ** 2 < spacing_px ** 2:
                        ok = False; break
                if not ok: break
            if not ok: break
        if ok:
            grid.setdefault((gr, gc), []).append((r, c)); keep.append(i)
    return np.array(sorted(keep))

sp = int(CAND_SPACING_M / PIX)
k_ok = thin(rr[eligible], cc[eligible], sp)
k_no = thin(rr[~eligible], cc[~eligible], sp)       # excluded ones, thinned, for the map

cand = pd.DataFrame({
    'row': rr[eligible][k_ok], 'col': cc[eligible][k_ok], 'eligible': True, 'exclusion': ''})
excl = pd.DataFrame({
    'row': rr[~eligible][k_no], 'col': cc[~eligible][k_no], 'eligible': False,
    'exclusion': reason[~eligible][k_no]})
cand = pd.concat([cand, excl], ignore_index=True)

# snapped routing pixel
cand['r_snap'] = sr[cand.row, cand.col]
cand['c_snap'] = sc[cand.row, cand.col]
print(f"Candidates: {int(cand.eligible.sum())} eligible, {int((~cand.eligible).sum())} excluded (thinned)")

# %% [markdown]
# ## 6. Destinations → grid (snapped to passable pixels)

# %%
dest = pd.read_csv(DEST_CSV)

# Accept either lon/lat or longitude/latitude column names.
dest = dest.rename(columns={'longitude': 'lon', 'latitude': 'lat'})
required = {'dest_id', 'dest_type', 'tier', 'lon', 'lat'}
missing = required - set(dest.columns)
assert not missing, f'Missing destination columns: {sorted(missing)}'

# Display fix for a spelling error in the OSM source name (data otherwise unchanged).
if 'name' in dest.columns:
    dest['name'] = dest['name'].replace({'Vainī Hosptial': 'Vainī Hospital'})

print('Destination rows:', len(dest))
print(dest.groupby(['tier', 'dest_type']).size())

to_utm = Transformer.from_crs('EPSG:4326', crs, always_xy=True)
ux, uy = to_utm.transform(dest.lon.values, dest.lat.values)
dr_, dc_ = rowcol(transform, ux, uy)

dest['row'] = np.clip(dr_, 0, H - 1)
dest['col'] = np.clip(dc_, 0, W - 1)
dest['r_snap'] = sr[dest.row, dest.col]
dest['c_snap'] = sc[dest.row, dest.col]
dest['snap_m'] = snap_dist[dest.row, dest.col] * PIX
dest['usable'] = dest.snap_m <= SNAP_R_M

print('\nDestination snapping by tier:')
print(dest.groupby('tier').usable.agg(['sum', 'count']))


# %% [markdown]
# ## 7. Least-cost access: one cost-distance surface per tier
# Units: **cost-weighted metres** (1 m of sealed, unimpacted road on flat ground = 1).

# %%
mcp, cum = {}, {}
for t in (1, 2, 3):
    d = dest[(dest.tier == t) & dest.usable]
    starts = list(zip(d.r_snap.astype(int), d.c_snap.astype(int)))
    t0 = time.time()
    m = MCP_Geometric(cost, fully_connected=True)
    cum_t, _ = m.find_costs(starts)
    mcp[t], cum[t] = m, cum_t * PIX
    print(f'Tier {t} ({TIER_NAMES[t]}): {len(starts)} sources, {time.time()-t0:.1f} s')

# lookup: snapped destination pixel -> destination row
dest_at = {(int(r), int(c)): i for i, (r, c) in enumerate(zip(dest.r_snap, dest.c_snap))}

# %% [markdown]
# ## 8. Route metrics for every eligible candidate (tiers 1–3)
# 
# Hazard exposure and confidence now use the **all-surface** Model 2B impact-excess layer:
# 
# - landing-zone impact = mean valid impact excess over main-island land within 250 m;
# - landing-zone confidence = fraction of main-island land in that window with a valid impact score;
# - route impact = mean/p90 valid impact excess along the route;
# - route confidence = fraction of route pixels with valid impact evidence.
# 
# This keeps Hazard Safety separate from Road Connectivity and avoids treating “no nearby road” as “unknown landing-zone hazard.”

# %%
is_road = road_cls > 0

# Landing-zone all-surface impact / confidence.
lz_k = disk(int(LANDING_ZONE_R_M / PIX)).astype('float32')
valid_land_impact = impact_valid_all & main

num_imp = ndi.convolve(
    np.where(valid_land_impact, impact_excess_all, 0).astype('float32'),
    lz_k, mode='constant'
)
den_imp = ndi.convolve(valid_land_impact.astype('float32'), lz_k, mode='constant')
lz_impact = np.where(
    den_imp > 0,
    num_imp / np.maximum(den_imp, 1e-6),
    np.nan
)

den_land = ndi.convolve(main.astype('float32'), lz_k, mode='constant')
lz_conf = np.where(
    den_land > 0,
    den_imp / np.maximum(den_land, 1e-6),
    0.0
)

# Distance to the nearest road is an MCDA criterion, NOT a hard filter.
road_dist_px, (rd_r, rd_c) = ndi.distance_transform_edt(
    ~is_road, return_indices=True
)

def route_stats(path):
    p = np.asarray(path)
    pr, pc = p[:, 0], p[:, 1]
    step = np.hypot(np.diff(pr), np.diff(pc)) * PIX
    length = float(step.sum())

    on_road = is_road[pr, pc]
    iv = impact_valid_all[pr, pc]
    imp = impact_excess_all[pr, pc]

    return {
        'length_m': length,
        'road_share': float(on_road.mean()),
        'impact_mean': float(imp[iv].mean()) if iv.any() else np.nan,
        'impact_p90': float(np.percentile(imp[iv], 90)) if iv.any() else np.nan,
        'impact_known_share': float(iv.mean()),
        'confidence_mean': float(iv.mean()),
        'slope_max': float(slope[pr, pc].max()),
        'dest_px': (int(pr[0]), int(pc[0])),
    }

rows = []
elig = cand[cand.eligible].copy()
t0 = time.time()

for _, c in elig.iterrows():
    r0, c0 = int(c.r_snap), int(c.c_snap)
    rec = {'row': c.row, 'col': c.col, 'r_snap': r0, 'c_snap': c0}

    for t in (1, 2, 3):
        cc_ = cum[t][r0, c0]
        rec[f'cost_t{t}'] = cc_

        if np.isfinite(cc_):
            s = route_stats(mcp[t].traceback((r0, c0)))
            di = dest_at.get(s.pop('dest_px'))
            rec[f'dest_t{t}'] = dest.dest_id.iloc[di] if di is not None else ''
            rec[f'dest_t{t}_name'] = (
                dest.name.iloc[di]
                if di is not None and 'name' in dest.columns
                and isinstance(dest.name.iloc[di], str)
                else ''
            )
            for k, v in s.items():
                rec[f'{k}_t{t}'] = v

    rec['road_dist_m'] = float(road_dist_px[r0, c0] * PIX)
    rec['nearest_road_class'] = int(
        road_cls[rd_r[r0, c0], rd_c[r0, c0]]
    )
    rec['lz_impact'] = float(lz_impact[r0, c0])
    rec['lz_confidence'] = float(lz_conf[r0, c0])
    rows.append(rec)

print(f'Traced {len(rows) * 3} routes in {time.time() - t0:.1f} s')

m = pd.DataFrame(rows)
reach = np.isfinite(m.cost_t1) & np.isfinite(m.cost_t2)
print(
    f'Candidates reaching a hospital and a school/clinic: '
    f'{int(reach.sum())} / {len(m)}'
)
m = m[reach].reset_index(drop=True)


# %% [markdown]
# ## 9. Five MCDA criteria (raw values; documented definitions)
# 
# | Criterion | Raw value (lower = better unless noted) |
# |---|---|
# | Hazard Safety | 0.5 × mean all-surface impact excess in the 250 m landing zone + 0.5 × mean all-surface impact excess along the hospital route (unknown → median, flagged) |
# | Corridor Efficiency | cost-weighted distance to the nearest hospital (Tier 1) |
# | Road Connectivity | distance from landing to nearest road; ×1.5 if that road is unsealed |
# | Destination Access | 0.6 × cost to nearest school/clinic (Tier 2) + 0.4 × cost to nearest community point (Tier 3) |
# | Data Confidence (higher = better) | mean of landing-zone valid-impact fraction and valid-impact fraction along the hospital route |
# 
# All-surface impact excess is relative to the WorldCover-class reference level used in the final friction model, avoiding systematic penalisation of built-up surfaces.

# %%
def raw_criteria(df, unknown_fill='median'):
    out = pd.DataFrame(index=df.index)
    lz = df.lz_impact.copy(); rt = df.impact_mean_t1.copy()
    unknown = lz.isna() & rt.isna()
    fill_lz = lz.median() if unknown_fill == 'median' else lz.quantile(0.9)
    fill_rt = rt.median() if unknown_fill == 'median' else rt.quantile(0.9)
    out['hazard_exposure'] = 0.5 * lz.fillna(fill_lz) + 0.5 * rt.fillna(fill_rt)
    out['hazard_unknown'] = unknown
    out['corridor_cost'] = df.cost_t1
    out['road_access_m'] = df.road_dist_m * np.where(df.nearest_road_class == 2, 1.5, 1.0)
    t3 = df.cost_t3.fillna(df.cost_t3.max())
    out['access_cost'] = 0.6 * df.cost_t2 + 0.4 * t3
    out['confidence'] = 0.5 * df.lz_confidence + 0.5 * df.confidence_mean_t1
    return out

def minmax(x):
    lo, hi = np.nanmin(x), np.nanmax(x)
    return np.zeros_like(x) if hi == lo else (x - lo) / (hi - lo)

def score(raw, w):
    crit = pd.DataFrame(index=raw.index)
    crit['hazard_safety']       = 1 - minmax(raw.hazard_exposure.values)
    crit['corridor_efficiency'] = 1 - minmax(raw.corridor_cost.values)
    crit['road_connectivity']   = 1 - minmax(raw.road_access_m.values)
    crit['destination_access']  = 1 - minmax(raw.access_cost.values)
    crit['data_confidence']     = minmax(raw.confidence.values)
    s = sum(w[k] * crit[k] for k in w) * 100
    return crit, s

raw = raw_criteria(m)
crit, base_score = score(raw, WEIGHTS)

# %% [markdown]
# ## 10. Ranking + OAAT ±20 % sensitivity + conservative scenario

# %%
def ranks(s):
    return s.rank(ascending=False, method='min').astype(int)

base_rank = ranks(base_score)
scen = {'baseline': base_rank}
for k in WEIGHTS:
    for f in (0.8, 1.2):
        w = dict(WEIGHTS); w[k] = WEIGHTS[k] * f
        rest = 1 - w[k]; other = 1 - WEIGHTS[k]
        for j in w:
            if j != k: w[j] = WEIGHTS[j] * rest / other      # keep weights summing to 1
        scen[f'{k}_{"-" if f < 1 else "+"}20%'] = ranks(score(raw, w)[1])

# conservative: unknown impact assumed high (90th percentile) instead of median
scen['conservative_unknown_impact'] = ranks(score(raw_criteria(m, 'p90'), WEIGHTS)[1])

S = pd.DataFrame(scen)
TOP_K = 5
stab = pd.DataFrame({
    'rank_baseline': S.baseline,
    'rank_best': S.min(axis=1),
    'rank_worst': S.max(axis=1),
    'rank_mean': S.mean(axis=1).round(1),
    f'scenarios_in_top{TOP_K}': (S <= TOP_K).sum(axis=1),
    'n_scenarios': S.shape[1],
})

# %% [markdown]
# ## 11. Assemble the ranked table

# %%
to_ll = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
xs, ys = xy(transform, m.row.values, m.col.values)
lon, lat = to_ll.transform(xs, ys)

table = pd.concat([m, raw, crit.add_prefix('crit_')], axis=1)
table['m_idx'] = m.index
table['score'] = base_score.round(2)
table = pd.concat([table, stab], axis=1)
table['lon'], table['lat'] = lon, lat
table = table.sort_values('rank_baseline').reset_index(drop=True)
table.insert(0, 'site_id', [f'S{i+1:03d}' for i in range(len(table))])
# --- Reconnaissance priority --------------------------------------------
# HIGH when a site ranks well on paper but the evidence behind it is weak,
# or when its sea approach is uncertain (sheltered channel near the lagoon mouth;
# bathymetry is out of scope). These are the sites aerial recon should check first.
from scipy.spatial import cKDTree
RECON_TOP_N      = 15     # sites a planner would actually look at
CONF_LOW         = 0.5    # < half of the landing zone + route has valid impact evidence
MOUTH_FLAG_KM    = 1.0    # within 1 km of the lagoon mouth line

d_mouth_px, _ = cKDTree(np.c_[line_r, line_c]).query(np.c_[table.row, table.col])
table['dist_lagoon_mouth_km'] = (d_mouth_px * PIX / 1000).round(2)

top_n = table.rank_baseline <= RECON_TOP_N
reasons = pd.DataFrame({
    'impact unknown':                 table.hazard_unknown,
    'top-ranked, weak evidence':      top_n & (table.confidence < CONF_LOW),
    'approach near lagoon mouth':     top_n & (table.dist_lagoon_mouth_km < MOUTH_FLAG_KM),
})
table['recon_reason'] = reasons.apply(lambda r: '; '.join(k for k, v in r.items() if v), axis=1)
table['recon_priority'] = np.where(table.recon_reason != '', 'HIGH', 'normal')
print('Recon priority HIGH:', int((table.recon_priority == 'HIGH').sum()), 'sites;',
      reasons.sum().to_dict())

show = ['site_id', 'score', 'rank_baseline', 'rank_best', 'rank_worst', f'scenarios_in_top{TOP_K}',
        'cost_t1', 'dest_t1_name', 'cost_t2', 'road_dist_m', 'hazard_exposure', 'confidence',
        'recon_priority', 'recon_reason', 'dist_lagoon_mouth_km', 'lon', 'lat']
print(table[show].head(15).to_string(index=False))

# %% [markdown]
# ## 12. Route geometries for the top N sites (tiers 1 and 2)

# %%
def path_to_lonlat(path, simplify_every=3):
    p = np.asarray(path)[::simplify_every]
    if not np.array_equal(p[-1], np.asarray(path)[-1]):
        p = np.vstack([p, np.asarray(path)[-1]])
    x, y = xy(transform, p[:, 0], p[:, 1])
    lo, la = to_ll.transform(x, y)
    return [[float(a), float(b)] for a, b in zip(lo, la)]

features = []
for _, s in table.head(TOP_N_ROUTES).iterrows():
    for t in (1, 2):
        path = mcp[t].traceback((int(s.r_snap), int(s.c_snap)))
        features.append({'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': path_to_lonlat(path)},
            'properties': {'site_id': s.site_id, 'rank': int(s.rank_baseline), 'tier': t,
                           'tier_name': TIER_NAMES[t],
                           'destination': s[f'dest_t{t}_name'] or s[f'dest_t{t}'],
                           'cost_weighted_m': round(float(s[f'cost_t{t}']), 1),
                           'length_m': round(float(s[f'length_m_t{t}']), 1),
                           'road_share': round(float(s[f'road_share_t{t}']), 3),
                           'impact_mean': None if pd.isna(s[f'impact_mean_t{t}']) else round(float(s[f'impact_mean_t{t}']), 3)}})

# %% [markdown]
# ## 13. Export

# %%
def to_geojson_points(df, cols):
    feats = []
    for _, r in df.iterrows():
        props = {c: (None if (isinstance(r[c], float) and not np.isfinite(r[c])) else
                     (r[c].item() if hasattr(r[c], 'item') else r[c])) for c in cols}
        feats.append({'type': 'Feature', 'geometry': {'type': 'Point',
                      'coordinates': [float(r.lon), float(r.lat)]}, 'properties': props})
    return {'type': 'FeatureCollection', 'features': feats}

# all candidates incl. excluded ones (for the map)
cx, cy = xy(transform, cand.row.values, cand.col.values)
cand['lon'], cand['lat'] = to_ll.transform(cx, cy)

table.to_csv(os.path.join(OUT, 'sites_ranked_v2.csv'), index=False)
S.loc[table.m_idx].assign(site_id=table.site_id.values).to_csv(
    os.path.join(OUT, 'sensitivity_ranks_v2.csv'), index=False)
json.dump(to_geojson_points(table, [c for c in show if c not in ('lon', 'lat')]),
          open(os.path.join(OUT, 'sites_ranked_v2.geojson'), 'w'))
json.dump(to_geojson_points(cand, ['eligible', 'exclusion']),
          open(os.path.join(OUT, 'candidates_all_v2.geojson'), 'w'))
json.dump({'type': 'FeatureCollection', 'features': features},
          open(os.path.join(OUT, f'routes_top{TOP_N_ROUTES}_v2.geojson'), 'w'))
json.dump({'weights': WEIGHTS, 'spacing_m': CAND_SPACING_M, 'mangrove_max': MANGROVE_MAX,
           'cliff_slope_deg': CLIFF_SLOPE_DEG, 'landing_zone_r_m': LANDING_ZONE_R_M,
           'n_eligible': int(cand.eligible.sum()), 'n_ranked': len(table),
           'lagoon_mouth_lat': LAGOON_MOUTH_LAT, 'lagoon_mouth_lon': LAGOON_MOUTH_LON,
           'lagoon_seed_lonlat': LAGOON_SEED_LONLAT, 'lagoon_km2': round(float(lagoon_km2), 2),
           'recon_top_n': RECON_TOP_N, 'recon_conf_low': CONF_LOW, 'recon_mouth_km': MOUTH_FLAG_KM},
          open(os.path.join(OUT, 'run_params_v2.json'), 'w'), indent=2)
print('Saved to', OUT, os.listdir(OUT))

# %% [markdown]
# ## 14. Quick-look map

# %%
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(11, 8))
ax.imshow(np.where(passable, np.minimum(friction, 10), np.nan), cmap='RdYlGn_r', vmin=1, vmax=10)
ax.imshow(np.where(lagoon, 1.0, np.nan), cmap='winter', alpha=0.5)   # excluded lagoon
e = cand[~cand.eligible]
ax.scatter(e.col, e.row, s=6, c='grey', label='excluded')
ax.scatter(table.col, table.row, s=12, c='royalblue', label='eligible')
top = table.head(TOP_N_ROUTES)
for f in features:
    p = mcp[f['properties']['tier']].traceback(
        (int(top[top.site_id == f['properties']['site_id']].r_snap.iloc[0]),
         int(top[top.site_id == f['properties']['site_id']].c_snap.iloc[0])))
    p = np.asarray(p)
    ax.plot(p[:, 1], p[:, 0], lw=1.2, c='black' if f['properties']['tier'] == 1 else 'purple')
ax.scatter(top.col, top.row, s=60, c='red', marker='*', label=f'top {TOP_N_ROUTES}')
for _, s in top.iterrows():
    ax.annotate(s.site_id, (s.col, s.row), fontsize=8, color='red')
ax.legend(loc='lower left'); ax.set_axis_off()
ax.set_title('Shore-Gate v2 — ranked landing sites and routes (black = hospital, purple = school/clinic)')
plt.tight_layout(); plt.savefig(os.path.join(OUT, 'quicklook_v2.png'), dpi=150); plt.show()
