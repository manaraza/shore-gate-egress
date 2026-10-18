"""
make_cards.py — Shore-Gate: Egress landing-site cards + reconnaissance priority list
Inputs : data/sites_ranked_v2.csv, data/routes_all_v2.geojson, data/dest_lookup.csv,
         tongatapu_routing_stack_v2.tif (path as 1st argument)
Outputs: cards/card_S001.png ... (top N), cards/shoregate_landing_cards_top10.pdf,
         cards/recon_priority_list.csv
Usage  : python make_cards.py /path/to/tongatapu_routing_stack_v2.tif [N]
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Patch
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

HERE = Path(__file__).parent
D, OUT = HERE / "data", HERE / "cards"
OUT.mkdir(exist_ok=True)
STACK = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "tongatapu_routing_stack_v2.tif")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10

INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#d9d8d4"
BLUE, RED, AMBER = "#2a78d6", "#e34948", "#eda100"
W = {"hazard_safety": 0.25, "corridor_efficiency": 0.25, "road_connectivity": 0.20,
     "destination_access": 0.15, "data_confidence": 0.15}
SHORT = {"hazard_safety": "Hazard safety", "corridor_efficiency": "Corridor (hospital)",
         "road_connectivity": "Road connectivity", "destination_access": "Destination access",
         "data_confidence": "Data confidence"}
TIER = {1: "Hospital", 2: "School / clinic", 3: "Community / worship"}
ROUTE = {1: dict(c="#0b0b0b", lw=2.6, ls="-"), 2: dict(c="#c97a00", lw=2.0, ls=(0, (5, 3))),
         3: dict(c="#1f8fbf", lw=1.6, ls=(0, (1, 2)))}

sites = pd.read_csv(D / "sites_ranked_v2.csv").sort_values("rank_baseline").reset_index(drop=True)
dl = pd.read_csv(D / "dest_lookup.csv").set_index("dest_id")
routes = json.loads((D / "routes_all_v2.geojson").read_text(encoding="utf-8"))["features"]
for t in (1, 2, 3):
    typ = sites[f"dest_t{t}"].map(dl["dest_type"]).fillna("").str.replace("_", " ")
    nm = sites[f"dest_t{t}_name"].fillna("").str.replace("Hosptial", "Hospital")
    sites[f"dest_t{t}_label"] = np.where(nm != "", nm, "Unnamed " + typ)

with rasterio.open(STACK) as src:
    st = src.read().astype("float32")
    T, crs = src.transform, src.crs
fr, rcls, wc, ex, va = st[0], st[3], st[5], st[6], st[7]
land = np.isfinite(fr) & (fr > 0)
valid = land & (va > 0.5) & (ex >= 0)
to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

# background RGB: water pale blue, land light grey, roads dark grey, impact >= 0.25 orange/red,
# impact unknown slightly darker grey
bg = np.ones(fr.shape + (3,))
bg[:] = (0.86, 0.92, 0.97)
bg[land] = (0.93, 0.93, 0.91)
bg[land & ~valid] = (0.86, 0.86, 0.84)
bg[valid & (ex >= 0.25)] = (0.98, 0.72, 0.45)
bg[valid & (ex >= 0.50)] = (0.86, 0.33, 0.25)
bg[land & (np.nan_to_num(rcls) > 0)] = (0.45, 0.45, 0.45)


def to_px(lon, lat):
    x, y = to_utm.transform(lon, lat)
    return (x - T.c) / T.a, (y - T.f) / T.e      # col, row (float)


def card(s, path=None, pdf=None):
    fig = plt.figure(figsize=(11.69, 8.27), dpi=150)       # A4 landscape
    fig.patch.set_facecolor("white")
    flag = s.recon_priority == "HIGH"

    # ---- header
    fig.text(0.035, 0.945, f"Landing site {s.site_id}", fontsize=22, weight="bold", color=INK)
    fig.text(0.035, 0.912, f"Rank {int(s.rank_baseline)} of {len(sites)}  ·  score {s.score:.1f} / 100  ·  "
             f"Tongatapu, post-eruption (Jan 2022)", fontsize=11, color=INK2)
    if flag:
        fig.patches.append(FancyBboxPatch((0.66, 0.915), 0.305, 0.05, boxstyle="round,pad=0.006",
                                          transform=fig.transFigure, fc="#fde8e8", ec=RED, lw=1.2))
        fig.text(0.672, 0.948, "RECONNAISSANCE PRIORITY: HIGH", fontsize=10.5, weight="bold", color=RED)
        fig.text(0.672, 0.925, s.recon_reason, fontsize=8.5, color=INK2)

    # ---- map
    ax = fig.add_axes([0.035, 0.11, 0.50, 0.77])
    feats = [f for f in routes if f["properties"]["site_id"] == s.site_id]
    pts = np.vstack([np.array([to_px(*c) for c in f["geometry"]["coordinates"]]) for f in feats])
    c0, r0 = to_px(s.lon, s.lat)
    pts = np.vstack([pts, [[c0, r0]]])
    cmin, rmin = pts.min(0)
    cmax, rmax = pts.max(0)
    pad = max(40, 0.12 * max(cmax - cmin, rmax - rmin))
    cmin, cmax, rmin, rmax = cmin - pad, cmax + pad, rmin - pad, rmax + pad
    # square-ish extent matching the axes aspect
    w, h = cmax - cmin, rmax - rmin
    target = 0.50 * 11.69 / (0.77 * 8.27)
    if w / h < target:
        d = (h * target - w) / 2; cmin -= d; cmax += d
    else:
        d = (w / target - h) / 2; rmin -= d; rmax += d
    ci0, ci1 = int(max(cmin, 0)), int(min(cmax, fr.shape[1]))
    ri0, ri1 = int(max(rmin, 0)), int(min(rmax, fr.shape[0]))
    ax.imshow(bg[ri0:ri1, ci0:ci1], extent=(ci0, ci1, ri1, ri0), interpolation="nearest")
    for f in sorted(feats, key=lambda f: -f["properties"]["tier"]):
        t = f["properties"]["tier"]
        xy = np.array([to_px(*c) for c in f["geometry"]["coordinates"]])
        ax.plot(xy[:, 0], xy[:, 1], color=ROUTE[t]["c"], lw=ROUTE[t]["lw"], ls=ROUTE[t]["ls"],
                solid_capstyle="round", zorder=3)
        ax.scatter(xy[0, 0], xy[0, 1], s=70, marker="s", color=ROUTE[t]["c"], edgecolor="white", lw=1.2, zorder=4)
    ax.scatter([c0], [r0], s=260, marker="v", color=BLUE, edgecolor="white", lw=1.8, zorder=5)
    ax.annotate(s.site_id, (c0, r0), xytext=(8, 10), textcoords="offset points", fontsize=10,
                weight="bold", color=INK, zorder=6,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
    ax.set_xlim(cmin, cmax); ax.set_ylim(rmax, rmin)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color(GRID)
    # scale bar 1 km
    sb_x, sb_y = cmin + 0.05 * (cmax - cmin), rmax - 0.05 * (rmax - rmin)
    ax.plot([sb_x, sb_x + 100], [sb_y, sb_y], color=INK, lw=3)
    ax.text(sb_x + 50, sb_y - 0.015 * (rmax - rmin), "1 km", ha="center", va="bottom", fontsize=8, color=INK)
    ax.text(cmax - 0.03 * (cmax - cmin), rmin + 0.05 * (rmax - rmin), "N ↑", ha="right", fontsize=10, weight="bold", color=INK)
    leg = [Line2D([0], [0], color=ROUTE[t]["c"], lw=ROUTE[t]["lw"], ls=ROUTE[t]["ls"], label=f"Route to {TIER[t].lower()}")
           for t in (1, 2, 3)]
    leg += [Line2D([0], [0], marker="v", color="w", markerfacecolor=BLUE, markersize=11, label="Landing site"),
            Patch(fc=(0.45, 0.45, 0.45), label="Road (OSM, 15 Jan 2022)"),
            Patch(fc=(0.98, 0.72, 0.45), label="Impact excess 0.25–0.50"),
            Patch(fc=(0.86, 0.33, 0.25), label="Impact excess ≥ 0.50"),
            Patch(fc=(0.86, 0.86, 0.84), label="Impact unknown (tree cover etc.)")]
    ax.legend(handles=leg, loc="upper left", fontsize=7.2, frameon=True, framealpha=0.92, edgecolor=GRID)

    # ---- right panel
    x0 = 0.565
    y = 0.865

    def head(txt):
        nonlocal y
        fig.text(x0, y, txt.upper(), fontsize=8.5, weight="bold", color=MUTED)
        y -= 0.027

    def row(k, v, bold=False):
        nonlocal y
        fig.text(x0, y, k, fontsize=9.5, color=INK2)
        fig.text(x0 + 0.17, y, v, fontsize=9.5, color=INK, weight="bold" if bold else "normal")
        y -= 0.025

    utm_e, utm_n = 669500 + s["col"] * 10 + 5, 7671040 - s["row"] * 10 - 5
    head("Location")
    row("Lat / Lon", f"{s.lat:.5f}°, {s.lon:.5f}°")
    row("UTM zone 1S", f"E {utm_e:.0f}  N {utm_n:.0f}")
    row("Lagoon mouth", f"{s.dist_lagoon_mouth_km:.1f} km")
    y -= 0.008
    head("Landing zone (250 m)")
    row("Road access", ("on road" if s.road_dist_m == 0 else f"{s.road_dist_m:.0f} m to road") +
        (" (sealed)" if s.nearest_road_class == 1 else " (unsealed)"))
    row("Impact excess", "unknown" if pd.isna(s.lz_impact) else f"{s.lz_impact:.2f}  (0 = typical, 1 = max)")
    row("Impact evidence", f"{s.lz_confidence:.0%} of landing zone")
    row("Data confidence", f"{s.confidence:.2f}", bold=True)
    y -= 0.008
    head("Nearest destination per tier — least-cost route")
    cols = [x0, x0 + 0.115, x0 + 0.315, x0 + 0.365]
    for cx, t in zip(cols, ["Tier", "Destination", "km", "on road"]):
        fig.text(cx, y, t, fontsize=8, color=MUTED)
    y -= 0.024
    for t in (1, 2, 3):
        name = s[f"dest_t{t}_label"]
        name = name if len(name) <= 30 else name[:29] + "…"
        for cx, v in zip(cols, [TIER[t], name, f"{s[f'length_m_t{t}'] / 1000:.1f}", f"{s[f'road_share_t{t}']:.0%}"]):
            fig.text(cx, y, v, fontsize=9, color=INK, weight="bold" if t == 1 and cx == cols[2] else "normal")
        y -= 0.024
    fig.text(x0, y, f"Hospital route: max slope {s.slope_max_t1:.0f}°, mean impact excess "
             f"{s.impact_mean_t1:.2f}, impact evidence {s.impact_known_share_t1:.0%} of route.",
             fontsize=8, color=INK2)
    y -= 0.032
    head("Robustness")
    row("Rank range", f"{int(s.rank_best)}–{int(s.rank_worst)} across 12 scenarios", bold=True)
    row("In top 5", f"{int(s.scenarios_in_top5)} of 12 scenarios")
    y -= 0.008
    head("Score breakdown (points)")
    bx = fig.add_axes([x0 + 0.105, y - 0.115, 0.285, 0.125])
    vals = [W[k] * s[f"crit_{k}"] * 100 for k in W]
    mx = [W[k] * 100 for k in W]
    yy = np.arange(len(W))[::-1]
    bx.barh(yy, mx, color="#ececea", height=0.62)
    bx.barh(yy, vals, color=BLUE, height=0.62)
    for yi, v, m in zip(yy, vals, mx):
        bx.text(m + 0.4, yi, f"{v:.1f} / {m:.0f}", va="center", fontsize=7.5, color=INK2)
    bx.set_yticks(yy, [SHORT[k] for k in W], fontsize=8, color=INK2)
    bx.set_xlim(0, 32); bx.set_xticks([])
    for sp in bx.spines.values():
        sp.set_visible(False)
    bx.tick_params(length=0)
    y -= 0.14

    # ---- verify box
    fig.patches.append(FancyBboxPatch((x0 - 0.006, 0.105), 0.405, max(y - 0.105, 0.06), boxstyle="round,pad=0.006",
                                      transform=fig.transFigure, fc="#f6f6f4", ec=GRID, lw=0.8))
    vy = y - 0.018
    fig.text(x0, vy, "NOT ASSESSED — VERIFY BEFORE USE", fontsize=8.5, weight="bold", color=INK)
    lines = ["Water depth, approach and reef; beach gradient, surf and tide; obstacles;",
             "ground bearing capacity; current road and bridge condition."]
    if "lagoon" in str(s.recon_reason):
        lines.append("Approach is in the sheltered channel near the Fangaʻuta lagoon entrance.")
    if "weak evidence" in str(s.recon_reason):
        lines.append("Under half of landing zone + route has impact evidence (mostly tree cover).")
    for i, l in enumerate(lines):
        fig.text(x0, vy - 0.022 * (i + 1), l, fontsize=8, color=INK2)

    # ---- footer
    fig.text(0.035, 0.055, "Shore-Gate: Egress · screening prototype (GEOG761, University of Auckland). "
             "Data: Sentinel-1/2, ALOS-2 DPM, ESA WorldCover 2021, OSM (15 Jan 2022), Copernicus EMSR558. "
             "Score = weighted sum of five normalised criteria.", fontsize=7, color=MUTED)
    fig.text(0.035, 0.035, "Decision support only. Results come from open satellite data and models; they must be verified "
             "by aerial reconnaissance and ground survey before operational use.", fontsize=7, color=MUTED)
    if path:
        fig.savefig(path, dpi=150, facecolor="white")
    if pdf:
        pdf.savefig(fig, facecolor="white")
    plt.close(fig)


with PdfPages(OUT / f"shoregate_landing_cards_top{N}.pdf") as pdf:
    for _, s in sites.head(N).iterrows():
        card(s, OUT / f"card_{s.site_id}.png", pdf)
        print("card", s.site_id)

# Reconnaissance priority target list
verify = {"approach near lagoon mouth": "Approach depth, reef and channel at lagoon entrance",
          "top-ranked, weak evidence": "Ground conditions and damage on landing zone and route"}
rc = sites[sites.recon_priority == "HIGH"].copy()
rc["what_to_verify"] = rc.recon_reason.apply(lambda x: " · ".join(verify.get(k, k) for k in str(x).split("; ")))
rc = rc[["rank_baseline", "site_id", "score", "confidence", "dist_lagoon_mouth_km", "recon_reason",
         "what_to_verify", "dest_t1_label", "length_m_t1", "lat", "lon"]]
rc["confidence"] = rc.confidence.round(2)
rc["length_m_t1"] = rc.length_m_t1.round(0)
rc.to_csv(OUT / "recon_priority_list.csv", index=False)
print(rc.to_string(index=False))
