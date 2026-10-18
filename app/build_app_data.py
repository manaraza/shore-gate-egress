"""
build_app_data.py — prepare ./data for the Shore-Gate Streamlit app
Inputs : tongatapu_routing_stack_v2.tif, tongatapu_destinations_20220115.csv/.geojson,
         routing_v2/ outputs of 15_routing_mcda_v2.ipynb
Outputs: data/routes_all_v2.geojson   least-cost routes for ALL ranked sites, tiers 1-3
         data/lagoon_v2.geojson, data/lagoon_mouth_v2.geojson
         data/friction_overlay.png, data/impact_overlay.png, data/overlay_bounds.json
         data/dest_lookup.csv + copies of the notebook outputs
Usage  : python build_app_data.py STACK.tif DEST.csv DEST.geojson ROUTING_V2_DIR
Routes use the same cost surface, snapping and MCP_Geometric settings as notebook 15 v2.1
(checked: route lengths identical to the notebook, max difference < 1e-9 m).
"""
import json
import shutil
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import LinearSegmentedColormap
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.transform import rowcol, xy
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy import ndimage as ndi
from shapely import transform as shp_transform
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from skimage.graph import MCP_Geometric

STACK, DEST_CSV, DEST_GJ, RV2 = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)
PIX, SNAP_R_M = 10.0, 60
LAGOON_MOUTH_LAT, LAGOON_MOUTH_LON = -21.1534, (-175.1750, -175.1077)
LAGOON_SEED_LONLAT = (-175.1278, -21.1681)
IMPACT_BREAKS = [0.10, 0.25, 0.50]

with rasterio.open(STACK) as s:
    st = s.read().astype("float32")
    T, crs = s.transform, s.crs
fr, rcls, wc, ex, va = st[0], st[3], st[5], st[6], st[7]
H, W = fr.shape
passable = np.isfinite(fr) & (fr > 0)
cost = np.where(passable, fr, np.inf).astype("float64")
to_grid = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

# ---------------------------------------------------------------- routes
snap_dist, (sr, sc) = ndi.distance_transform_edt(~passable, return_indices=True)
dest = pd.read_csv(DEST_CSV)
dest["name"] = dest["name"].replace({"Vainī Hosptial": "Vainī Hospital"})
ux, uy = to_grid.transform(dest.lon.values, dest.lat.values)
r_, c_ = rowcol(T, ux, uy)
dest["row"], dest["col"] = np.clip(r_, 0, H - 1), np.clip(c_, 0, W - 1)
dest["r_snap"], dest["c_snap"] = sr[dest.row, dest.col], sc[dest.row, dest.col]
dest["usable"] = snap_dist[dest.row, dest.col] * PIX <= SNAP_R_M
mcp = {}
for t in (1, 2, 3):
    d = dest[(dest.tier == t) & dest.usable]
    m = MCP_Geometric(cost, fully_connected=True)
    m.find_costs(list(zip(d.r_snap.astype(int), d.c_snap.astype(int))))
    mcp[t] = m
dest_at = {(int(r), int(c)): i for i, (r, c) in enumerate(zip(dest.r_snap, dest.c_snap))}
sites = pd.read_csv(RV2 / "sites_ranked_v2.csv")
TN = {1: "hospital", 2: "school/clinic", 3: "community/worship"}
feats, maxdiff = [], 0.0
for _, s in sites.iterrows():
    for t in (1, 2, 3):
        p = np.asarray(mcp[t].traceback((int(s.r_snap), int(s.c_snap))))
        L = float((np.hypot(np.diff(p[:, 0]), np.diff(p[:, 1])) * PIX).sum())
        maxdiff = max(maxdiff, abs(L - s[f"length_m_t{t}"]))
        di = dest_at.get((int(p[0, 0]), int(p[0, 1])))
        q = p[::3]
        if not np.array_equal(q[-1], p[-1]):
            q = np.vstack([q, p[-1]])
        x, y = xy(T, q[:, 0], q[:, 1])
        lo, la = to_ll.transform(x, y)
        nm = dest.name.iloc[di] if di is not None and isinstance(dest.name.iloc[di], str) else ""
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": [[round(a, 6), round(b, 6)] for a, b in zip(lo, la)]},
                      "properties": {"site_id": s.site_id, "rank": int(s.rank_baseline), "tier": t, "tier_name": TN[t],
                                     "destination": nm, "dest_type": dest.dest_type.iloc[di] if di is not None else "",
                                     "dest_id": dest.dest_id.iloc[di] if di is not None else "",
                                     "cost": round(float(s[f"cost_t{t}"]), 1), "length_m": round(L, 1),
                                     "road_share": round(float(s[f"road_share_t{t}"]), 3)}})
assert maxdiff < 1.0, f"Routes differ from the notebook by {maxdiff:.2f} m - check inputs"
json.dump({"type": "FeatureCollection", "features": feats}, open(OUT / "routes_all_v2.geojson", "w"))
dest.set_index("dest_id")[["dest_type", "name"]].to_csv(OUT / "dest_lookup.csv")
print(f"routes: {len(feats)} (max length difference vs notebook {maxdiff:.2e} m)")

# ---------------------------------------------------------------- lagoon (same rule as notebook)
water = (np.where(np.isfinite(wc), wc, 0) == 80) | (np.where(np.isfinite(wc), wc, 0) == 0)
def lonlat_rc(lon, lat):
    x, y = to_grid.transform(lon, lat)
    r, c = rowcol(T, x, y)
    return int(r), int(c)
(ra, ca), (rb, cb) = lonlat_rc(LAGOON_MOUTH_LON[0], LAGOON_MOUTH_LAT), lonlat_rc(LAGOON_MOUTH_LON[1], LAGOON_MOUTH_LAT)
n = abs(cb - ca) + 1
lr, lc = np.round(np.linspace(ra, rb, n)).astype(int), np.round(np.linspace(ca, cb, n)).astype(int)
barrier = np.zeros_like(water)
for d in (-1, 0, 1):
    barrier[np.clip(lr + d, 0, H - 1), np.clip(lc, 0, W - 1)] = True
lab, _ = ndi.label(water & ~barrier)
lagoon = (lab == lab[lonlat_rc(*LAGOON_SEED_LONLAT)]).astype("uint8")
poly = unary_union([shape(g) for g, v in shapes(lagoon, mask=lagoon == 1, transform=T) if v == 1]).simplify(15)
poly_ll = shp_transform(poly, lambda xy_: np.column_stack(to_ll.transform(xy_[:, 0], xy_[:, 1])))
json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": mapping(poly_ll),
           "properties": {"name": "Fangaʻuta / Fangakakau Lagoon (excluded)", "area_km2": round(poly.area / 1e6, 1)}}]},
          open(OUT / "lagoon_v2.geojson", "w"))
json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "LineString",
           "coordinates": [[LAGOON_MOUTH_LON[0], LAGOON_MOUTH_LAT], [LAGOON_MOUTH_LON[1], LAGOON_MOUTH_LAT]]},
           "properties": {"name": "Lagoon mouth line (21.1534 S)"}}]}, open(OUT / "lagoon_mouth_v2.geojson", "w"))
print(f"lagoon: {poly.area / 1e6:.1f} km2")


# ---------------------------------------------------------------- overlays (EPSG:3857, 20 m)
def overlay(arr, path, colorize, resampling, nodata):
    left, top = T.c, T.f
    right, bottom = left + W * T.a, top + H * T.e
    dT, dw, dh = calculate_default_transform(crs, "EPSG:3857", W, H, left, bottom, right, top, resolution=20)
    dst = np.full((dh, dw), nodata, arr.dtype)
    reproject(arr, dst, src_transform=T, src_crs=crs, dst_transform=dT, dst_crs="EPSG:3857",
              resampling=resampling, src_nodata=nodata, dst_nodata=nodata)
    plt.imsave(path, colorize(dst))
    t3 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    lo0, la0 = t3.transform(dT.c, dT.f + dh * dT.e)
    lo1, la1 = t3.transform(dT.c + dw * dT.a, dT.f)
    return [[la0, lo0], [la1, lo1]]

cm = LinearSegmentedColormap.from_list("fr", ["#1a9850", "#91cf60", "#ffffbf", "#fc8d59", "#d73027"])
def col_fric(a):
    rgba = cm(np.clip((a - 1) / 11, 0, 1))
    rgba[..., 3] = np.where(np.isfinite(a), 0.75, 0)
    return rgba
b_fr = overlay(np.where(passable, fr, np.nan).astype("float32"), OUT / "friction_overlay.png", col_fric, Resampling.nearest, np.nan)

valid = passable & (va > 0.5) & (ex >= 0)
cls = np.zeros(fr.shape, "uint8")
cls[passable] = 1
cls[valid] = 2 + np.digitize(ex[valid], IMPACT_BREAKS)
PAL = {1: (0.55, 0.55, 0.55, 0.45), 2: (1, 1, 1, 0), 3: (0.99, 0.80, 0.36, 0.75), 4: (0.94, 0.48, 0.15, 0.85), 5: (0.70, 0.10, 0.10, 0.9)}
def col_imp(a):
    rgba = np.zeros(a.shape + (4,))
    for k, c in PAL.items():
        rgba[a == k] = c
    return rgba
b_im = overlay(cls, OUT / "impact_overlay.png", col_imp, Resampling.mode, 0)
json.dump({"friction": b_fr, "impact": b_im, "impact_classes": {"breaks": IMPACT_BREAKS}},
          open(OUT / "overlay_bounds.json", "w"), indent=1)
print(f"valid impact on passable land: {valid.sum() / passable.sum():.1%}")

# ---------------------------------------------------------------- copies
for f in ["sites_ranked_v2.csv", "sensitivity_ranks_v2.csv", "candidates_all_v2.geojson", "run_params_v2.json"]:
    shutil.copy(RV2 / f, OUT / f)
shutil.copy(DEST_GJ, OUT / "tongatapu_destinations_20220115.geojson")

# ---------------------------------------------------------------- routing grid for the Route explorer
# Post-event cost = friction_v1 as exported. Pre-event baseline = same surface, but every road cell at its
# undamaged cost (sealed 1.0, unsealed 1.5) x slope multiplier (x1 <5 deg, x1.5 5-15, x3 15-30).
# Check on the v2 stack: this reproduces friction_v1 exactly on 99.6% of impacted road cells.
slope = st[4]
rc_u8 = np.nan_to_num(rcls).astype("uint8")
smult = np.where(slope < 5, 1.0, np.where(slope < 15, 1.5, 3.0))
fr_imp = np.where(passable, fr, np.nan)
fr_base = np.where(passable & (rc_u8 > 0), np.where(rc_u8 == 1, 1.0, 1.5) * smult, fr_imp)
ex_valid = np.where(passable & (va > 0.5) & (ex >= 0), ex, np.nan)
rows_, cols_ = np.where(passable)
r0_, r1_ = max(rows_.min() - 20, 0), rows_.max() + 21
c0_, c1_ = max(cols_.min() - 20, 0), cols_.max() + 21
cut = lambda a: a[r0_:r1_, c0_:c1_]
np.savez_compressed(OUT / "routing_grid.npz",
                    friction_impact=cut(fr_imp).astype("float16"), friction_baseline=cut(fr_base).astype("float16"),
                    impact_excess=cut(ex_valid).astype("float16"), road_class=cut(rc_u8),
                    slope_deg=cut(np.where(passable, slope, np.nan)).astype("float16"),
                    transform=np.array([T.a, T.b, T.c + c0_ * T.a, T.d, T.e, T.f + r0_ * T.e]),
                    crs=np.array(crs.to_string()))
print("routing grid written")
print("data ready in", OUT)
