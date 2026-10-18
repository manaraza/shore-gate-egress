"""
make_slide_figures.py — Shore-Gate: Egress (Samana, Tongatapu) slide figures
Usage: python make_slide_figures.py STACK_v2.tif APP_DATA_DIR OUT_DIR
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch, Rectangle
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

STACK, AD, OUT = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)

INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8984", "#d9d8d4", "#ffffff"
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"
SEA, LAND = "#dce9f5", "#efefec"
plt.rcParams.update({"font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.titlecolor": INK,
                     "axes.titlesize": 14, "axes.titleweight": "bold", "axes.titlelocation": "left",
                     "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "axes.spines.top": False, "axes.spines.right": False})

with rasterio.open(STACK) as s:
    st = s.read().astype("float32")
    T, crs = s.transform, s.crs
fr, rcls, slope, wc, ex, va = st[0], np.nan_to_num(st[3]), st[4], np.nan_to_num(st[5]), st[6], st[7]
H, W = fr.shape
land = np.isfinite(fr) & (fr > 0)
water = ~land
valid = land & (va > 0.5) & (ex >= 0)
road = land & (rcls > 0)
to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

sites = pd.read_csv(AD / "sites_ranked_v2.csv").sort_values("rank_baseline").reset_index(drop=True)
sens = pd.read_csv(AD / "sensitivity_ranks_v2.csv")
routes = json.loads((AD / "routes_all_v2.geojson").read_text())["features"]
dests = json.loads((AD / "tongatapu_destinations_20220115.geojson").read_text())["features"]
lagoon = json.loads((AD / "lagoon_v2.geojson").read_text())["features"][0]["geometry"]
cands = json.loads((AD / "candidates_all_v2.geojson").read_text())["features"]


def px(lon, lat):
    x, y = to_utm.transform(lon, lat)
    return (np.asarray(x) - T.c) / T.a, (np.asarray(y) - T.f) / T.e


def lagoon_rings():
    g = lagoon
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    for poly in polys:
        for ring in poly:
            a = np.array(ring)
            yield px(a[:, 0], a[:, 1])


# crop to the island
rows, cols = np.where(land)
R0, R1 = max(rows.min() - 40, 0), min(rows.max() + 40, H)
C0, C1 = max(cols.min() - 40, 0), min(cols.max() + 40, W)
# main island only for limits
from scipy import ndimage as ndi
lab, n = ndi.label(land, structure=np.ones((3, 3)))
main = lab == (np.argmax(ndi.sum(land, lab, range(1, n + 1))) + 1)
mr, mc = np.where(main)
R0, R1, C0, C1 = mr.min() - 60, mr.max() + 60, mc.min() - 60, mc.max() + 60


def base_axes(figsize=(12, 7.2), title=None):
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(C0, C1); ax.set_ylim(R1, R0)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    if title:
        ax.set_title(title, pad=10)
    return fig, ax


def scalebar(ax, km=5):
    x0, y0 = C0 + 0.04 * (C1 - C0), R1 - 0.05 * (R1 - R0)
    ax.plot([x0, x0 + km * 100], [y0, y0], color=INK, lw=3, solid_capstyle="butt")
    ax.text(x0 + km * 50, y0 - 0.015 * (R1 - R0), f"{km} km", ha="center", va="bottom", fontsize=9, color=INK)
    ax.text(C1 - 0.03 * (C1 - C0), R1 - 0.06 * (R1 - R0), "↑\nN", ha="center", fontsize=11, weight="bold", color=INK)


def rgb(mask_colors, bg=SEA):
    img = np.ones((H, W, 3))
    img[:] = matplotlib.colors.to_rgb(bg)
    for m, c in mask_colors:
        img[m] = matplotlib.colors.to_rgb(c)
    return img[R0:R1, C0:C1]


def show(ax, img):
    ax.imshow(img, extent=(C0, C1, R1, R0), interpolation="nearest")


def save(fig, name):
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", facecolor=SURF)
    plt.close(fig)
    print("saved", name)


lag_mask = None

# ---------------------------------------------------------------- 01 study area
fig, ax = base_axes(title="Study area — Tongatapu, Kingdom of Tonga")
show(ax, rgb([(land, LAND), (road, "#b9b8b3")]))
for x, y in lagoon_rings():
    ax.fill(x, y, color="#a9cfee", zorder=2)
    ax.plot(x, y, color="#5f9fd1", lw=0.8, zorder=2)
tiers = {1: [], 2: [], 3: []}
for f in dests:
    p = f["properties"]
    tiers[int(p["tier"])].append((f["geometry"]["coordinates"][:2], p.get("name") or ""))
for t, c, sz, lab_ in [(3, "#9a9994", 6, "Community / worship (270)"), (2, "#eda100", 14, "School / clinic (90)"),
                       (1, RED, 120, "Hospital (3)")]:
    xy = np.array([px(*c_) for c_, _ in tiers[t]])
    ax.scatter(xy[:, 0], xy[:, 1], s=sz, color=c, edgecolor="white" if t == 1 else "none",
               lw=1.2, zorder=5 if t == 1 else 4, marker="P" if t == 1 else "o", label=lab_)
HOFF = {"Vaiola": (8, -16), "Vain": (-120, -22), "Mu'a": (10, -18)}
for (c_, nm) in tiers[1]:
    x, y = px(*c_)
    off = next((v for k, v in HOFF.items() if nm.startswith(k)), (8, -14))
    ax.annotate(nm.replace("Hosptial", "Hospital"), (x, y), xytext=off, textcoords="offset points",
                fontsize=9.5, weight="bold", color=INK,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
x, y = px(-175.204, -21.136)
ax.annotate("Nukuʻalofa", (x, y), xytext=(-30, 28), textcoords="offset points", fontsize=11, style="italic", color=INK2)
x, y = px(-175.17, -21.172)
ax.text(x, y, "Fangaʻuta\nLagoon", fontsize=9.5, color="#2f6f9f", ha="center", va="center", style="italic", zorder=6)
ax.annotate("Hunga Tonga–Hunga Haʻapai\nvolcano ≈ 65 km NNW", xy=(C0 + 0.30 * (C1 - C0), R0 + 0.02 * (R1 - R0)),
            xytext=(C0 + 0.30 * (C1 - C0), R0 + 0.16 * (R1 - R0)), ha="center", fontsize=9.5, color=INK2,
            arrowprops=dict(arrowstyle="->", color=INK2, lw=1.2))
ax.legend(handles=[Line2D([0], [0], marker="P", color="w", markerfacecolor=RED, markersize=12, label="Hospital (3)"),
                   Line2D([0], [0], marker="o", color="w", markerfacecolor="#eda100", markersize=7, label="School / clinic (90)"),
                   Line2D([0], [0], marker="o", color="w", markerfacecolor="#9a9994", markersize=5, label="Community / worship (270)"),
                   Patch(fc="#b9b8b3", label="Road network (OSM, 15 Jan 2022)"),
                   Patch(fc="#a9cfee", ec="#5f9fd1", label="Lagoon (excluded from landing)")],
          loc="upper right", fontsize=9, frameon=True, framealpha=0.95, edgecolor=GRID, title="Destinations (OSM, pre-event)",
          title_fontsize=9)
scalebar(ax)
ax.text(C0, R1 + 0.035 * (R1 - R0), "Main island ≈ 265 km². Eruption and tsunami 15 Jan 2022; ashfall over the whole island. "
        "Grid: UTM 1S, 10 m.", fontsize=9, color=MUTED, va="top")
save(fig, "fig01_study_area.png")

# ---------------------------------------------------------------- 02 workflow
fig, ax = plt.subplots(figsize=(14, 7.6))
ax.set_xlim(0, 14); ax.set_ylim(0, 7.6); ax.axis("off")
ax.set_title("Workflow — from satellite evidence to a landing-site shortlist", pad=8)
stages = [
    ("1  Impact labels", "ALOS-2 Damage Proxy Map\n(22 Jan 2022) → change /\nno-change on grass, crop,\nbuilt-up, bare", "#e8f0fb"),
    ("2  Features", "Sentinel-2 pre vs post\n(Oct–Dec 2021 / 17–24 Jan)\n+ Sentinel-1 (27 Jan)\n31 bands, ≈31 m", "#e8f0fb"),
    ("3  Impact model", "Random Forest (Model 2B)\nspatial-block CV\nMacro-F1 0.695\n(simple rule 0.526)", "#e8f0fb"),
    ("4  Independent check", "Copernicus EMSR558\nroads AUC 0.61\ncart tracks 0.79,\nvillages 0.51", "#fdeee6"),
    ("5  Friction surface", "WorldCover + slope +\nOSM roads degraded by\nimpact excess above\nsurface baseline", "#e9f6f0"),
    ("6  Landing candidates", "Open-sea coast, ≈500 m\nno cliffs / mangroves\nlagoon closed at mouth\n→ 112 sites", "#e9f6f0"),
    ("7  Least-cost routes", "To nearest hospital,\nschool/clinic and\ncommunity point\n→ 336 routes", "#e9f6f0"),
    ("8  MCDA + sensitivity", "5 weighted criteria\n±20% per weight +\nconservative scenario\n→ robust top 5", "#fff6e0"),
    ("9  Outputs", "Ranked sites, landing\ncards, reconnaissance\nlist, Streamlit app", "#fff6e0"),
]
BW, BH = 2.35, 2.25
pos = [(0.3 + i * 2.75, 4.35) for i in range(5)] + [(0.3 + (8 - i) * 2.75 - 0.0, 1.0) for i in range(5, 9)]
pos = pos[:5] + [(0.3 + 2.75 * k, 1.0) for k in (4, 3, 2, 1)]
for (head, body, col), (x, y) in zip(stages, pos):
    ax.add_patch(FancyBboxPatch((x, y), BW, BH, boxstyle="round,pad=0.03,rounding_size=0.1", fc=col, ec=GRID, lw=1))
    ax.text(x + BW / 2, y + BH - 0.32, head, ha="center", va="center", fontsize=11, weight="bold", color=INK)
    ax.text(x + BW / 2, y + BH / 2 - 0.25, body, ha="center", va="center", fontsize=9.5, color=INK2, linespacing=1.35)
arrow = dict(arrowstyle="-|>", color=MUTED, lw=1.5, mutation_scale=16)
for i in range(4):
    (x0, y0), (x1, y1) = pos[i], pos[i + 1]
    ax.annotate("", xy=(x1 - 0.05, y1 + BH / 2), xytext=(x0 + BW + 0.05, y0 + BH / 2), arrowprops=arrow)
ax.annotate("", xy=(pos[5][0] + BW / 2, pos[5][1] + BH + 0.05), xytext=(pos[4][0] + BW / 2, pos[4][1] - 0.05), arrowprops=arrow)
for i in range(5, 8):
    (x0, y0), (x1, y1) = pos[i], pos[i + 1]
    ax.annotate("", xy=(x1 + BW + 0.05, y1 + BH / 2), xytext=(x0 - 0.05, y0 + BH / 2), arrowprops=arrow)
for x0, x1, y, lab_, col in [(0.3, 7.95, 6.95, "Impact evidence  (Google Earth Engine)", "#2a78d6"),
                             (8.55, 10.9, 6.95, "Validation", "#eb6834"),
                             (11.3, 13.65, 6.95, "Access modelling", "#1baf7a")]:
    ax.plot([x0, x1], [y, y], color=col, lw=3, solid_capstyle="round")
    ax.text((x0 + x1) / 2, y + 0.12, lab_, ha="center", va="bottom", fontsize=10, color=col, weight="bold")
for x0, x1, y, lab_, col in [(8.55, 13.65, 0.6, "Access modelling  (GEE + Python)", "#1baf7a"),
                             (3.05, 8.15, 0.6, "Decision support  (Python + Streamlit)", "#c98500")]:
    ax.plot([x0, x1], [y, y], color=col, lw=3, solid_capstyle="round")
    ax.text((x0 + x1) / 2, y - 0.12, lab_, ha="center", va="top", fontsize=10, color=col, weight="bold")
ax.add_patch(FancyBboxPatch((0.3, 1.0), BW, BH, boxstyle="round,pad=0.03,rounding_size=0.1", fc="#f4f4f2", ec=GRID, lw=1, ls="--"))
ax.text(0.3 + BW / 2, 1.0 + BH - 0.32, "Key safeguard", ha="center", va="center", fontsize=11, weight="bold", color=INK)
ax.text(0.3 + BW / 2, 1.0 + BH / 2 - 0.25, "Unknown impact\n(tree cover, outside model\ndomain) is never treated\nas safe → lowers confidence,\nraises recon priority",
        ha="center", va="center", fontsize=9.3, color=INK2, linespacing=1.35)
save(fig, "fig02_workflow.png")

# ---------------------------------------------------------------- 03 model comparison
fig, ax = plt.subplots(figsize=(8.5, 4.6))
m = pd.DataFrame({"model": ["Baseline\n(1-rule stump)", "2A\noptical only", "2C\nvariant*", "2B\noptical + S1"],
                  "f1": [0.526, 0.679, 0.682, 0.695]})
cols = [GRID, "#8bb7ea", "#8bb7ea", BLUE]
b = ax.bar(m.model, m.f1, color=cols, width=0.62)
for r, v in zip(b, m.f1):
    ax.text(r.get_x() + r.get_width() / 2, v + 0.012, f"{v:.3f}", ha="center", fontsize=11, color=INK,
            weight="bold" if v == 0.695 else "normal")
ax.set_ylim(0, 0.8); ax.set_ylabel("Macro-F1 (5-fold spatial-block CV)")
ax.set_title("Impact model: Random Forest beats a simple change rule")
ax.grid(axis="y", color=GRID, lw=0.6, alpha=0.7); ax.set_axisbelow(True)
fig.subplots_adjust(bottom=0.2)
fig.text(0.01, -0.06, "Model 2B chosen (kappa 0.39). 950 surface-matched samples (475 + 475), 300 trees. "
         "*2C: check definition in parameters.md before presenting.", fontsize=8.5, color=MUTED)
save(fig, "fig03_model_comparison.png")

# ---------------------------------------------------------------- 04 impact map
BR = [0.10, 0.25, 0.50]
fig, ax = base_axes(title="Post-event impact evidence (Model 2B, surface-relative excess)")
cls_cols = [(land, "#8f8f8b"), (valid & (ex < BR[0]), "#f6f1e3"), (valid & (ex >= BR[0]) & (ex < BR[1]), "#fdd49e"),
            (valid & (ex >= BR[1]) & (ex < BR[2]), "#f08c3a"), (valid & (ex >= BR[2]), "#b8261d")]
show(ax, rgb(cls_cols))
for x, y in lagoon_rings():
    ax.fill(x, y, color=SEA, zorder=2)
pct = lambda mk: f"{mk.sum() / land.sum():.0%}"
ax.legend(handles=[Patch(fc="#b8261d", label=f"≥ 0.50  high  ({pct(valid & (ex >= .5))})"),
                   Patch(fc="#f08c3a", label=f"0.25–0.50  ({pct(valid & (ex >= .25) & (ex < .5))})"),
                   Patch(fc="#fdd49e", label=f"0.10–0.25  ({pct(valid & (ex >= .1) & (ex < .25))})"),
                   Patch(fc="#f6f1e3", ec=GRID, label=f"< 0.10  typical for its surface  ({pct(valid & (ex < .1))})"),
                   Patch(fc="#8f8f8b", label=f"Unknown — outside model domain, mainly tree cover  ({pct(land & ~valid)})")],
          loc="upper right", fontsize=9, title="Impact excess (share of passable land)", title_fontsize=9,
          frameon=True, framealpha=0.95, edgecolor=GRID)
scalebar(ax)
ax.text(C0, R1 + 0.035 * (R1 - R0), "Excess = how much higher the impact score is than typical for the same land-cover class "
        "(0 = typical, 1 = maximal). Native resolution ≈ 31 m.", fontsize=9, color=MUTED, va="top")
save(fig, "fig04_impact_map.png")

# ---------------------------------------------------------------- 05 friction map
fig, ax = base_axes(title="Friction surface — how hard it is to move across each 10 m cell")
img = np.ones((H, W, 4)); img[..., :3] = matplotlib.colors.to_rgb(SEA)
cm = matplotlib.colors.LinearSegmentedColormap.from_list("fr", ["#1a9850", "#91cf60", "#ffffbf", "#fc8d59", "#d73027"])
norm = matplotlib.colors.LogNorm(1, 30)
img[land] = cm(norm(np.clip(fr[land], 1, 30)))
show(ax, img[R0:R1, C0:C1, :3])
sm = plt.cm.ScalarMappable(norm=norm, cmap=cm)
cb = fig.colorbar(sm, ax=ax, fraction=0.025, pad=0.01, ticks=[1, 2, 5, 10, 20, 30])
cb.ax.set_yticklabels(["1  sealed road", "2", "5", "10", "20", "30"]); cb.outline.set_visible(False)
cb.set_label("Relative cost per metre (log scale)")
scalebar(ax)
ax.text(C0, R1 + 0.035 * (R1 - R0), "Land cover (ESA WorldCover 2021) × slope (×1 / ×1.5 / ×3; > 30° impassable); "
        "roads degraded by impact excess. 1 = 1 m of flat, sealed, unimpacted road.", fontsize=9, color=MUTED, va="top")
save(fig, "fig05_friction_map.png")

# ---------------------------------------------------------------- 06 ranked sites map
fig, ax = base_axes(figsize=(12, 7.4), title="Ranked landing sites and hospital routes (top 10)")
show(ax, rgb([(land, LAND), (road, "#cfcec9")]))
for x, y in lagoon_rings():
    ax.fill(x, y, color="#a9cfee", zorder=2)
for f in dests:
    if int(f["properties"]["tier"]) == 1:
        x, y = px(*f["geometry"]["coordinates"][:2])
        ax.scatter(x, y, s=150, marker="P", color=RED, edgecolor="white", lw=1.2, zorder=7)
top10 = set(sites.site_id.head(10))
for f in routes:
    p = f["properties"]
    if p["tier"] == 1 and p["site_id"] in top10:
        a = np.array(f["geometry"]["coordinates"]); x, y = px(a[:, 0], a[:, 1])
        ax.plot(x, y, color="#1f2937", lw=1.6, alpha=0.85, zorder=4)
ex_ = np.array([px(*f["geometry"]["coordinates"]) for f in cands if not f["properties"]["eligible"]])
ax.scatter(ex_[:, 0], ex_[:, 1], s=8, color="#b5b4af", zorder=3, label="Excluded (cliff / mangrove)")
x, y = px(sites.lon.values, sites.lat.values)
sc = ax.scatter(x, y, c=sites.score, cmap=matplotlib.colors.LinearSegmentedColormap.from_list("b", ["#c5dbf5", "#163f75"]),
                s=np.where(sites.rank_baseline <= 10, 110, 30), edgecolor="white", lw=0.8, zorder=5)
hi = sites.recon_priority == "HIGH"
ax.scatter(x[hi], y[hi], s=260, facecolor="none", edgecolor=RED, lw=2.2, zorder=6)
LOFF = {"S001": (-38, 14), "S004": (8, -16), "S003": (6, 10), "S005": (-75, 30), "S006": (10, -10),
        "S010": (12, 2), "S002": (12, -10), "S007": (12, -20), "S008": (12, -12), "S009": (10, -14)}
for i in range(10):
    s_ = sites.iloc[i]
    dx, dy = LOFF.get(s_.site_id, (10, -12))
    ax.annotate(f"{s_.site_id}", (x[i], y[i]), xytext=(dx, dy), textcoords="offset points", fontsize=9.5, weight="bold",
                color=INK, zorder=8, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85),
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8, shrinkA=0, shrinkB=4) if s_.site_id == "S005" else None)
cb = fig.colorbar(sc, ax=ax, fraction=0.025, pad=0.01); cb.set_label("MCDA score (0–100)"); cb.outline.set_visible(False)
ax.legend(handles=[Line2D([0], [0], marker="o", color="w", markerfacecolor=BLUE, markersize=10, label="Candidate site (112)"),
                   Line2D([0], [0], marker="o", color="w", markerfacecolor="none", markeredgecolor=RED, markeredgewidth=2,
                          markersize=13, label="Reconnaissance priority HIGH"),
                   Line2D([0], [0], color="#1f2937", lw=1.6, label="Least-cost route to nearest hospital"),
                   Line2D([0], [0], marker="P", color="w", markerfacecolor=RED, markersize=12, label="Hospital"),
                   Line2D([0], [0], marker="o", color="w", markerfacecolor="#b5b4af", markersize=5, label="Excluded coast (thinned)")],
          loc="upper right", fontsize=9, frameon=True, framealpha=0.95, edgecolor=GRID)
scalebar(ax)
save(fig, "fig06_ranked_sites_map.png")

# ---------------------------------------------------------------- 07 sensitivity heatmap
top = sites.site_id.head(10).tolist()
nice = {"baseline": "Baseline", "conservative_unknown_impact": "Conservative\nunknown"}
for k, v in {"hazard_safety": "Hazard", "corridor_efficiency": "Corridor", "road_connectivity": "Road",
             "destination_access": "Access", "data_confidence": "Confidence"}.items():
    nice[f"{k}_-20%"], nice[f"{k}_+20%"] = f"{v}\n−20%", f"{v}\n+20%"
S = sens.set_index("site_id").loc[top]
fig, ax = plt.subplots(figsize=(12, 5.6))
cmap = matplotlib.colors.LinearSegmentedColormap.from_list("r", ["#163f75", "#4a8fdd", "#c5dbf5", "#f4f4f2"])
ax.imshow(np.clip(S.values, 1, 15), cmap=cmap, vmin=1, vmax=15, aspect="auto")
for i in range(S.shape[0]):
    for j in range(S.shape[1]):
        v = S.values[i, j]
        ax.text(j, i, v, ha="center", va="center", fontsize=10, color="white" if v <= 6 else INK,
                weight="bold" if v <= 5 else "normal")
ax.set_xticks(range(S.shape[1]), [nice[c] for c in S.columns], fontsize=8.8)
ax.set_yticks(range(len(top)), top)
ax.add_patch(Rectangle((-0.5, -0.5), S.shape[1], 5, fill=False, ec=ORANGE, lw=2.5))
ax.set_title("Sensitivity — rank of the top 10 in 12 scenarios (top-5 box in orange)")
for sp in ax.spines.values():
    sp.set_visible(False)
ax.tick_params(length=0)
fig.text(0.01, 0.01, "Each weight changed by ±20% (others rescaled) + conservative scenario (unknown impact = 90th percentile). "
         "S001–S005 stay in the top 5 in all 12.", fontsize=9, color=MUTED)
save(fig, "fig07_sensitivity_heatmap.png")

# ---------------------------------------------------------------- 08 score breakdown
Wt = {"hazard_safety": 0.25, "corridor_efficiency": 0.25, "road_connectivity": 0.20,
      "destination_access": 0.15, "data_confidence": 0.15}
lab = {"hazard_safety": "Hazard safety", "corridor_efficiency": "Corridor efficiency (hospital)",
       "road_connectivity": "Road connectivity", "destination_access": "Destination access", "data_confidence": "Data confidence"}
colsC = {"hazard_safety": BLUE, "corridor_efficiency": AQUA, "road_connectivity": "#eda100",
         "destination_access": "#e87ba4", "data_confidence": "#6250d6"}
t10 = sites.head(10).iloc[::-1]
fig, ax = plt.subplots(figsize=(11, 5.6))
left = np.zeros(len(t10))
for k in Wt:
    v = t10[f"crit_{k}"].values * Wt[k] * 100
    ax.barh(t10.site_id, v, left=left, color=colsC[k], edgecolor="white", lw=1.5, height=0.66, label=lab[k])
    left += v
for yi, (sc_, rp) in enumerate(zip(t10.score, t10.recon_priority)):
    ax.text(sc_ + 0.8, yi, f"{sc_:.1f}" + ("   ⚑ recon HIGH" if rp == "HIGH" else ""), va="center", fontsize=9.5,
            color=RED if rp == "HIGH" else INK)
ax.set_xlim(0, 112); ax.set_xlabel("Score points (max 100)")
ax.set_title("Why the top 10 score as they do")
ax.legend(ncol=3, loc="lower center", bbox_to_anchor=(0.45, -0.32), fontsize=9, frameon=False)
ax.grid(axis="x", color=GRID, lw=0.6, alpha=0.7); ax.set_axisbelow(True)
save(fig, "fig08_score_breakdown_top10.png")
