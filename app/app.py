"""
Shore-Gate: Egress — Tongatapu landing-site screening (partner interface)
Run:  streamlit run app.py
Data: ./data (exported by 15_routing_mcda_v2.ipynb and the app data builder)

Decision-support prototype. All outputs require reconnaissance and field verification.
"""
import json
from pathlib import Path

import altair as alt
import folium
import numpy as np
import pandas as pd
import streamlit as st
from folium.plugins import PolyLineOffset
from streamlit_folium import st_folium

from route_engine import RoutingGrid, path_overlap

D = Path(__file__).parent / "data"
_icon = D / "shoregate_icon.png"
st.set_page_config(page_title="Shore-Gate: Egress", page_icon=str(_icon) if _icon.exists() else "⚓", layout="wide")
st.markdown("""<style>
.block-container {padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1500px;}
h1, h2, h3 {letter-spacing: -0.02em;}
[data-testid="stMetric"] {background: #F7F9FC; border: 1px solid #E6EAF0; border-radius: 12px; padding: 10px 14px;}
[data-testid="stMetricValue"] {font-weight: 700;}
button[data-baseweb="tab"] p {font-weight: 600; font-size: 0.98rem;}
[data-testid="stDataFrame"] {border: 1px solid #E6EAF0; border-radius: 10px;}
/* Sidebar in the presentation's dark navy */
[data-testid="stSidebar"] {background-color: #081B27;}
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label,
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
[data-testid="stSidebar"] strong, [data-testid="stSidebar"] li {color: #F7FAFC;}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {color: #B9CAD3;}
[data-testid="stSidebar"] svg {color: #B9CAD3;}
[data-testid="stSidebar"] [data-testid="stTooltipIcon"], [data-testid="stSidebar"] [data-testid="stTooltipHoverTarget"],
[data-testid="stSidebar"] [data-testid="stTooltipIcon"] *, [data-testid="stSidebar"] [data-testid="stTooltipHoverTarget"] * {
  color: #B9CAD3 !important; stroke: #B9CAD3 !important; opacity: 1 !important;}
[data-testid="stSidebar"] hr {border-color: #31515E;}
[data-testid="stSidebar"] button[kind="secondary"] {background-color: #102B38; border: 1px solid #31515E;}
[data-testid="stSidebar"] button[kind="secondary"]:hover {border-color: #20B8B0;}
[data-testid="stSidebar"] [data-testid="stSliderTickBarMin"], [data-testid="stSidebar"] [data-testid="stSliderTickBarMax"] {color: #B9CAD3;}
[data-testid="stSidebarHeader"] {padding-bottom: 0;}
</style>""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Constants (keep in sync with params/parameters.md and notebook 15 v2.1)
# ---------------------------------------------------------------------------
DEFAULT_W = {
    "hazard_safety": 0.25,
    "corridor_efficiency": 0.25,
    "road_connectivity": 0.20,
    "destination_access": 0.15,
    "data_confidence": 0.15,
}
LABEL = {
    "hazard_safety": "Hazard safety",
    "corridor_efficiency": "Corridor efficiency (hospital)",
    "road_connectivity": "Road connectivity",
    "destination_access": "Destination access (school/clinic, community)",
    "data_confidence": "Data confidence",
}
HELP = {
    "hazard_safety": "Lower post-event impact in the 250 m landing zone and along the hospital route.",
    "corridor_efficiency": "Lower accumulated least-cost route cost to the nearest hospital.",
    "road_connectivity": "Shorter distance from landing to the nearest road (×1.5 if unsealed).",
    "destination_access": "Lower route cost to the nearest school/clinic (60%) and community point (40%).",
    "data_confidence": "Share of landing zone and route with valid impact evidence.",
}
RECON_TOP_N, CONF_LOW, MOUTH_FLAG_KM = 15, 0.5, 1.0
TIER_NAME = {1: "Hospital", 2: "School / clinic", 3: "Community / worship"}
# Selected-site routes: solid colours, dark casing, drawn side by side (pixel offset)
# so they stay visible where they share the same road.
ROUTE_STYLE = {1: dict(color="#ffffff", weight=5, offset=0),
               2: dict(color="#ffd166", weight=4, offset=7),
               3: dict(color="#22d3ee", weight=4, offset=-7)}
NAVY, AMBER, RED, TEAL, MUTED = "#173B57", "#F2A93B", "#D9534F", "#1BAF7A", "#667085"
DEST_COLOR = {1: NAVY, 2: "#eda100", 3: "#b8b8b8"}   # red is reserved for "verify first"


def coverage_label(v):
    return "high coverage" if v >= 0.8 else ("moderate coverage" if v >= 0.5 else "low coverage")
SCORE_RAMP = ["#c5dbf5", "#8bb7ea", "#4a8fdd", "#2a78d6", "#1f5fae", "#163f75"]
# Candidate colour = stable rank band (not a rescaled score), so colours stay comparable between scenarios
RANK_BANDS = [(5, "#163f75", "Top 5"), (15, "#4a8fdd", "Ranks 6–15"), (10**6, "#c5dbf5", "Rank 16+")]
VERIFY = "Verify first"
CONF_HELP = ("Share of the landing zone and hospital route with valid impact evidence. "
             "Confidence describes coverage of impact evidence; it does not mean the site is safe.")
WHY = {  # criterion -> (strong ≥ 0.9, moderate 0.7–0.9, weak < 0.7), on the 0–1 normalised criterion
    "hazard_safety": ("low modelled hazard", "moderate modelled hazard", "higher modelled hazard"),
    "corridor_efficiency": ("a very efficient route to hospital", "an efficient route to hospital",
                            "a costly route to hospital"),
    "road_connectivity": ("right next to a road", "close to a road", "far from the road network"),
    "destination_access": ("excellent access to schools/clinics and communities",
                           "good access to schools/clinics and communities",
                           "weaker access to schools/clinics and communities"),
    "data_confidence": ("strong impact-evidence coverage", "partial impact-evidence coverage",
                        "weak impact-evidence coverage"),
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
@st.cache_data
def load():
    sites = pd.read_csv(D / "sites_ranked_v2.csv")
    sens = pd.read_csv(D / "sensitivity_ranks_v2.csv")
    dl = pd.read_csv(D / "dest_lookup.csv").set_index("dest_id")
    gj = lambda f: json.loads((D / f).read_text(encoding="utf-8"))
    routes = gj("routes_all_v2.geojson")
    cands = gj("candidates_all_v2.geojson")
    dests = gj("tongatapu_destinations_20220115.geojson")
    lagoon = gj("lagoon_v2.geojson")
    mouth = gj("lagoon_mouth_v2.geojson")
    bounds = gj("overlay_bounds.json")
    params = gj("run_params_v2.json")
    # names for tier 2/3 destinations (often unnamed in OSM -> use type)
    for t in (1, 2, 3):
        ids = sites[f"dest_t{t}"]
        typ = ids.map(dl["dest_type"]).fillna("")
        nm = sites[f"dest_t{t}_name"].fillna("")
        sites[f"dest_t{t}_label"] = np.where(nm != "", nm, "Unnamed " + typ.str.replace("_", " "))
        sites[f"dest_t{t}_type"] = typ.str.replace("_", " ")
    sites["utm_e"] = 669500 + sites["col"] * 10 + 5
    sites["utm_n"] = 7671040 - sites["row"] * 10 - 5
    return sites, sens, routes, cands, dests, lagoon, mouth, bounds, params


# ---------------------------------------------------------------------------
# MCDA engine — identical to notebook 15 v2.1 (raw_criteria / minmax / score)
# ---------------------------------------------------------------------------
def raw_criteria(df, unknown_fill="median"):
    out = pd.DataFrame(index=df.index)
    lz, rt = df.lz_impact.copy(), df.impact_mean_t1.copy()
    unknown = lz.isna() & rt.isna()
    q = (lambda s: s.median()) if unknown_fill == "median" else (lambda s: s.quantile(0.9))
    out["hazard_exposure"] = 0.5 * lz.fillna(q(lz)) + 0.5 * rt.fillna(q(rt))
    out["hazard_unknown"] = unknown
    out["corridor_cost"] = df.cost_t1
    out["road_access_m"] = df.road_dist_m * np.where(df.nearest_road_class == 2, 1.5, 1.0)
    t3 = df.cost_t3.fillna(df.cost_t3.max())
    out["access_cost"] = 0.6 * df.cost_t2 + 0.4 * t3
    out["confidence"] = 0.5 * df.lz_confidence + 0.5 * df.confidence_mean_t1
    return out


def minmax(x):
    lo, hi = np.nanmin(x), np.nanmax(x)
    return np.zeros_like(x) if hi == lo else (x - lo) / (hi - lo)


def score(raw, w):
    c = pd.DataFrame(index=raw.index)
    c["hazard_safety"] = 1 - minmax(raw.hazard_exposure.values)
    c["corridor_efficiency"] = 1 - minmax(raw.corridor_cost.values)
    c["road_connectivity"] = 1 - minmax(raw.road_access_m.values)
    c["destination_access"] = 1 - minmax(raw.access_cost.values)
    c["data_confidence"] = minmax(raw.confidence.values)
    return c, sum(w[k] * c[k] for k in w) * 100


def rank_sites(sites, w, scenario):
    raw = raw_criteria(sites, "median" if scenario == "baseline" else "p90")
    crit, s = score(raw, w)
    out = sites.copy()
    for k in crit:
        out[f"live_{k}"] = crit[k]
    out["live_hazard_exposure"] = raw.hazard_exposure
    out["live_score"] = s.round(2)
    out["live_rank"] = s.rank(ascending=False, method="min").astype(int)
    out["rank_change"] = out["rank_baseline"] - out["live_rank"]
    top = out.live_rank <= RECON_TOP_N
    reasons = pd.DataFrame({
        "impact unknown": raw.hazard_unknown,
        "top-ranked, weak evidence": top & (out.confidence < CONF_LOW),
        "approach near lagoon mouth": top & (out.dist_lagoon_mouth_km < MOUTH_FLAG_KM),
    })
    out["live_recon_reason"] = reasons.apply(lambda r: "; ".join(k for k, v in r.items() if v), axis=1)
    out["live_recon"] = np.where(out.live_recon_reason != "", "HIGH", "normal")
    return out.sort_values("live_rank").reset_index(drop=True)


def band_color(rank):
    return next(c for lim, c, _ in RANK_BANDS if rank <= lim)


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _join(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def why_sentence(r, w):
    """Plain-language reading of one ranked site: criteria in a fixed order, strong/moderate/weak bands on the
    0–1 normalised criterion; data confidence uses the raw coverage (same 0.5 threshold as the verify-first flag)."""
    pos, neg = [], []
    for k in ["corridor_efficiency", "road_connectivity", "destination_access", "hazard_safety", "data_confidence"]:
        if k not in w:
            continue
        v = r.confidence if k == "data_confidence" else r[f"live_{k}"]
        hi_, mid_ = (0.8, CONF_LOW) if k == "data_confidence" else (0.9, 0.7)
        strong, mid, weak = WHY[k]
        phrase = strong if v >= hi_ else (mid if v >= mid_ else weak)
        if k == "hazard_safety" and r.confidence < CONF_LOW and v >= mid_:
            phrase += " (on limited evidence)"
        (pos if v >= mid_ else neg).append(phrase)
    flag = r.live_recon == "HIGH"
    head = f"**Why {r.site_id} ranks {ordinal(int(r.live_rank))}" + (" but needs verification" if flag else "") + ":** "
    body = (_join(pos) if pos else "no criterion stands out")
    body += (f", but {_join(neg)}" if neg else "") + "."
    if flag:
        body += f" Verify first: {r.live_recon_reason}."
    return head + body[0].upper() + body[1:]


sites, sens, routes, cands, dests, lagoon, mouth, bounds, params = load()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    _logo = D / "shoregate_logo.png"
    if _logo.exists():
        _l, _m, _r = st.columns([0.4, 5, 0.4])
        _m.image(str(_logo), width="stretch")
    st.markdown("### Shore-Gate: Egress")
    st.caption("Tongatapu · 2022 Hunga Tonga–Hunga Haʻapai eruption · coastal landing-site screening")

    st.markdown("**Scenario**")
    scenario = st.radio(
        "Unknown impact treated as", ["baseline", "conservative"], horizontal=True,
        format_func=lambda s: "Median (baseline)" if s == "baseline" else "90th percentile (conservative)",
        label_visibility="collapsed")

    st.markdown("**Criterion weights**")
    if st.button("Reset to proposal weights", width="stretch"):
        for k, v in DEFAULT_W.items():
            st.session_state[f"w_{k}"] = v
    raw_w = {k: st.slider(LABEL[k], 0.0, 0.5, DEFAULT_W[k], 0.05, key=f"w_{k}", help=HELP[k]) for k in DEFAULT_W}
    tot = sum(raw_w.values())
    if tot == 0:
        st.error("At least one weight must be above zero.")
        st.stop()
    W = {k: v / tot for k, v in raw_w.items()}
    if any(abs(W[k] - DEFAULT_W[k]) > 1e-9 for k in W):
        st.caption("Weights renormalised to sum to 1: " + " · ".join(f"{LABEL[k].split(' (')[0]} {W[k]:.2f}" for k in W))

    st.markdown("**Map**")
    top_n = st.slider("Highlight top N sites", 3, 30, 5)
    zoom_sel = st.checkbox("Zoom to selected site", value=False,
                           help="Centre the map on the selected site and its three routes")
    show_imp = st.checkbox("Post-event impact (classes)", value=False,
                           help="Surface-relative impact excess from Model 2B; grey = impact unknown (outside model domain, mainly tree cover)")
    show_fric = st.checkbox("Friction surface", value=False)
    show_dest = st.checkbox("Hospitals", value=True)
    show_dest23 = st.checkbox("Schools / clinics and community points", value=False)
    show_excl = st.checkbox("Excluded coast (cliff / mangrove)", value=False)
    show_routes = st.checkbox("Routes of top N (hospital)", value=True)
    basemap = st.radio("Basemap", ["Satellite", "Light"], horizontal=True)

    st.divider()
    st.caption("Prototype for decision support only. Outputs are screening results from open data "
               "(Sentinel-1/2, ALOS-2 DPM, ESA WorldCover, OSM) and must be verified by aerial "
               "reconnaissance and ground survey before any operational use. No bathymetry, tide or "
               "surf information is included.")

ranked = rank_sites(sites, W, scenario)
default_weights = all(abs(W[k] - DEFAULT_W[k]) < 1e-9 for k in W) and scenario == "baseline"

# Selected site shared by every tab; fall back to the top site if it is missing or not a valid site id
_valid_ids = set(ranked.site_id)
if st.session_state.get("sel") not in _valid_ids:
    st.session_state.sel = ranked.site_id.iloc[0]
for _k in ("sel_box", "re_site"):
    if _k in st.session_state and st.session_state[_k] not in _valid_ids:
        del st.session_state[_k]
# One selected site shared by every tab: widgets that show it are synced before they are drawn.
for _k in ("sel_box", "re_site"):
    if st.session_state.get(_k) != st.session_state.sel:
        st.session_state[_k] = st.session_state.sel


def _select_from(key):
    v = st.session_state.get(key)
    if v in _valid_ids:
        st.session_state.sel = v

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("## Where can supplies come ashore — and reach a hospital?")
n_high = int((ranked.live_recon == "HIGH").sum())
robust = sites[sites.scenarios_in_top5 == 12].site_id.tolist()
best = ranked.iloc[0]
alts = [x for x in ranked.site_id if x in robust and x != best.site_id]
flagged_alts = [x for x in alts if ranked.set_index("site_id").live_recon[x] == "HIGH"]
road_txt = "on a road" if best.road_dist_m == 0 else f"{best.road_dist_m:.0f} m from a {'sealed' if best.nearest_road_class == 1 else 'unsealed'} road"
rng = (f"#{int(best.rank_best)} in all 12" if best.rank_best == best.rank_worst
       else f"#{int(best.rank_best)}–{int(best.rank_worst)} across the 12")
robust_txt = (f"Robust: {rng} sensitivity scenarios" if default_weights
              else f"Proposal-weight sensitivity: {rng} precomputed scenarios (not rerun for your weights)")
alt_txt = (f"Alternatives if reconnaissance rules it out: {', '.join(alts)}"
           + (f" · verify {', '.join(flagged_alts)} first" if flagged_alts else "")) if alts else ""
st.markdown(f"""
<div style="background:linear-gradient(135deg,#173B57,#245B83);color:#fff;padding:20px 26px;border-radius:16px;margin:4px 0 14px 0">
  <div style="font-size:0.8rem;letter-spacing:0.06em;opacity:0.8;font-weight:700">RECOMMENDED STARTING POINT{'' if default_weights else ' · WITH YOUR WEIGHTS'}</div>
  <div style="display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 28px;margin:4px 0 2px 0">
    <span style="font-size:2.2rem;font-weight:750">{best.site_id}</span>
    <span style="font-size:1.05rem">Rank 1 of {len(ranked)} · score {best.live_score:.1f}</span>
    <span style="font-size:1.05rem">{best.length_m_t1 / 1000:.2f} km to {best.dest_t1_label}</span>
    <span style="font-size:1.05rem">{road_txt}</span>
    <span style="font-size:1.05rem">impact-data coverage {best.confidence:.0%} ({coverage_label(best.confidence)})</span>
  </div>
  <div style="font-size:0.95rem;opacity:0.92;margin-top:6px">{robust_txt}</div>
  <div style="font-size:0.95rem;opacity:0.92">{alt_txt}</div>
  <div style="font-size:0.85rem;opacity:0.75;margin-top:8px">Next step: aerial reconnaissance of the approach before use.</div>
</div>""", unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Candidate landing sites", f"{len(ranked)}", help="Open-sea coast of main Tongatapu, ~500 m spacing, after cliff/mangrove screening and lagoon exclusion")
c2.metric("Reach hospital + school/clinic", f"{len(ranked)}/{len(ranked)}")
c3.metric(VERIFY, n_high, help="Sites to check first by aerial reconnaissance: top-15 with weak impact evidence (<0.5), "
          "top-15 near the lagoon mouth (<1 km), or impact unknown. A flag means 'check first', not 'unsuitable'.")
stable = int((sites.scenarios_in_top5 == 12).sum())
c4.metric("Proposal shortlist stable", f"{stable}/5", help="Sites in the top 5 in all 12 precomputed scenarios around the proposal weights: baseline, ±20% on each weight (10) and the conservative unknown-impact scenario")
st.caption("Decision support only: no water depth, surf, tide or reef data. Every site must be confirmed by "
           "aerial reconnaissance and ground survey.")

tab_map, tab_short, tab_card, tab_route, tab_sens, tab_recon, tab_method = st.tabs(
    ["Map & ranking", "Compare shortlist", "Site card", "Route explorer", "Sensitivity", VERIFY, "Method & limits"])


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
def build_map(sel_id):
    # fixed centre/zoom (fit_bounds misbehaves when the map renders inside a hidden tab)
    center, zoom = [-21.165, -175.2], 11
    if zoom_sel:
        pts = np.array([c for f in routes["features"] if f["properties"]["site_id"] == sel_id
                        for c in f["geometry"]["coordinates"]])
        (lon0, lat0), (lon1, lat1) = pts.min(0), pts.max(0)
        center = [(lat0 + lat1) / 2, (lon0 + lon1) / 2]
        span = max(lon1 - lon0, (lat1 - lat0) / np.cos(np.radians(21.15)), 0.004)
        zoom = int(np.clip(np.floor(np.log2(360 * 520 / (256 * span * 1.15))), 11, 17))
    m = folium.Map(location=center, zoom_start=zoom, tiles=None, control_scale=True)
    if basemap == "Satellite":
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri, Maxar, Earthstar Geographics", name="Satellite").add_to(m)
    else:
        folium.TileLayer("CartoDB positron", name="Light").add_to(m)

    if show_fric:
        folium.raster_layers.ImageOverlay(str(D / "friction_overlay.png"), bounds=bounds["friction"],
                                          opacity=0.7, name="Friction (green low → red high)").add_to(m)
    if show_imp and (D / "impact_overlay.png").exists() and "impact" in bounds:
        folium.raster_layers.ImageOverlay(str(D / "impact_overlay.png"), bounds=bounds["impact"],
                                          opacity=0.85, name="Impact excess (grey = unknown)").add_to(m)

    folium.GeoJson(lagoon, name="Lagoon (excluded)",
                   style_function=lambda f: dict(color="#7fdbff", weight=1.5, fillColor="#7fdbff", fillOpacity=0.15),
                   tooltip="Fangaʻuta / Fangakakau Lagoon — excluded from landing candidates").add_to(m)
    folium.GeoJson(mouth, name="Lagoon mouth line",
                   style_function=lambda f: dict(color="#7fdbff", weight=2, dashArray="4 4")).add_to(m)

    if show_excl:
        fg = folium.FeatureGroup(name="Excluded coast")
        for f in cands["features"]:
            p = f["properties"]
            if not p["eligible"]:
                lon, lat = f["geometry"]["coordinates"]
                folium.CircleMarker([lat, lon], radius=3, color="#8a8a8a", fill=True, fill_opacity=0.8,
                                    weight=0, tooltip=f"Excluded: {p['exclusion']}").add_to(fg)
        fg.add_to(m)

    if show_dest or show_dest23:
        fg = folium.FeatureGroup(name="Destinations")
        for f in dests["features"]:
            p = f["properties"]
            lon, lat = f["geometry"]["coordinates"][:2]
            t = int(p.get("tier", 3))
            if (t == 1 and not show_dest) or (t > 1 and not show_dest23):
                continue
            if t == 3 and len(dests["features"]) > 200:
                r = 2
            else:
                r = 6 if t == 1 else 3
            name = p.get("name") or "Unnamed"
            name = name.replace("Hosptial", "Hospital")
            folium.CircleMarker([lat, lon], radius=r, color="#ffffff" if t == 1 else "#000",
                                weight=2 if t == 1 else 0.5, fill=True,
                                fill_color=DEST_COLOR[t], fill_opacity=0.95,
                                tooltip=f"{name} · {str(p.get('dest_type', '')).replace('_', ' ')} · tier {t}").add_to(fg)
        fg.add_to(m)

    top_ids = set(ranked.site_id.head(top_n))
    if show_routes:
        fg = folium.FeatureGroup(name="Hospital routes (top N)")
        for f in routes["features"]:
            p = f["properties"]
            if p["tier"] == 1 and p["site_id"] in top_ids and p["site_id"] != sel_id:
                folium.PolyLine([(b, a) for a, b in f["geometry"]["coordinates"]], color="#ffffff",
                                weight=2, opacity=0.6).add_to(fg)
        fg.add_to(m)

    # selected site: all three routes (casing first, then coloured lines, then end markers)
    sel_routes = sorted([f for f in routes["features"] if f["properties"]["site_id"] == sel_id],
                        key=lambda f: -f["properties"]["tier"])
    for f in sel_routes:
        st_ = ROUTE_STYLE[f["properties"]["tier"]]
        PolyLineOffset([(b, a) for a, b in f["geometry"]["coordinates"]], offset=st_["offset"],
                       color="#111111", weight=st_["weight"] + 3, opacity=0.7).add_to(m)
    for f in sel_routes:
        p = f["properties"]
        st_ = ROUTE_STYLE[p["tier"]]
        dest = p["destination"] or ("Unnamed " + str(p["dest_type"]).replace("_", " "))
        tip = (f"{sel_id} → {dest} ({TIER_NAME[p['tier']]}): "
               f"{p['length_m'] / 1000:.1f} km, {p['road_share']:.0%} on road")
        PolyLineOffset([(b, a) for a, b in f["geometry"]["coordinates"]], offset=st_["offset"],
                       color=st_["color"], weight=st_["weight"], opacity=1.0, tooltip=tip).add_to(m)
        lon0, lat0 = f["geometry"]["coordinates"][0]          # route starts at the destination
        folium.CircleMarker([lat0, lon0], radius=8, color="#111111", weight=3, fill=True,
                            fill_color=st_["color"], fill_opacity=1,
                            tooltip=f"{TIER_NAME[p['tier']]}: {dest}").add_to(m)

    fg = folium.FeatureGroup(name="Landing candidates")
    for _, r in ranked.iloc[::-1].iterrows():
        top = r.live_rank <= top_n
        flag = r.live_recon == "HIGH"
        tip = (f"<b>{r.site_id}</b> · rank {r.live_rank} · score {r.live_score:.1f}<br>"
               f"Hospital: {r.dest_t1_label} ({r.length_m_t1 / 1000:.1f} km)<br>"
               f"Data confidence {r.confidence:.2f} (evidence coverage, not safety)"
               + (f"<br><b>{VERIFY}:</b> {r.live_recon_reason}" if flag else ""))
        folium.CircleMarker([r.lat, r.lon], radius=9 if top else 5,
                            color="#e34948" if flag else ("#ffffff" if top else "#1f2937"),
                            weight=3 if flag else (2 if top else 1),
                            fill=True, fill_color=band_color(r.live_rank), fill_opacity=1.0,
                            tooltip=folium.Tooltip(tip)).add_to(fg)
        if top:
            folium.Marker([r.lat, r.lon], icon=folium.DivIcon(
                html=f'<div style="font:600 11px sans-serif;color:#fff;text-shadow:0 0 3px #000,0 0 3px #000;'
                     f'transform:translate(10px,-18px);white-space:nowrap">{r.site_id}</div>')).add_to(fg)
    fg.add_to(m)

    sel = ranked[ranked.site_id == sel_id].iloc[0]
    folium.CircleMarker([sel.lat, sel.lon], radius=14, color="#ffd166", weight=3, fill=False).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


with tab_map:
    left, right = st.columns([3, 2], gap="medium")
    with left:
        ids = ranked.site_id.tolist()
        sel = st.selectbox("Selected site (or click a site on the map)", ids, key="sel_box",
                           on_change=_select_from, args=("sel_box",),
                           format_func=lambda s: f"{s} — rank {int(ranked.set_index('site_id').live_rank[s])}")
        out = st_folium(build_map(sel), height=620, use_container_width=True,  # streamlit-folium arg
                        returned_objects=["last_object_clicked"], key="map")
        clk = (out or {}).get("last_object_clicked")
        if clk and clk != st.session_state.get("last_clk"):
            st.session_state.last_clk = clk
            d = (ranked.lat - clk["lat"]) ** 2 + ((ranked.lon - clk["lng"]) * np.cos(np.radians(21.15))) ** 2
            i = int(d.idxmin())
            if np.sqrt(d.iloc[i]) * 111_000 < 400 and ranked.site_id.iloc[i] != sel:
                st.session_state.sel = ranked.site_id.iloc[i]
                st.rerun()
        st.markdown(
            '<div style="font-size:0.85rem">Selected site routes: '
            '<span style="background:#111;color:#fff;padding:1px 8px;border-radius:3px">━ hospital</span> '
            '<span style="background:#111;color:#ffd166;padding:1px 8px;border-radius:3px">━ school / clinic</span> '
            '<span style="background:#111;color:#22d3ee;padding:1px 8px;border-radius:3px">━ community / worship</span>'
            ' · ● = destination (hospitals: navy) · lines are drawn side by side where they share a road · '
            f'red ring = {VERIFY.lower()}</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:0.85rem">Landing sites by rank: '
                    + " ".join(f'<span style="color:{c};font-size:1.1rem">●</span> {lbl}' for _, c, lbl in RANK_BANDS)
                    + ' · exact scores in the tooltip</div>', unsafe_allow_html=True)
        if show_imp:
            st.markdown(
                '<div style="font-size:0.8rem">Impact excess: '
                '<span style="background:#fccc5c;padding:0 6px">0.10–0.25</span> '
                '<span style="background:#f07a26;color:#fff;padding:0 6px">0.25–0.50</span> '
                '<span style="background:#b31a1a;color:#fff;padding:0 6px">≥ 0.50</span> '
                '<span style="background:#8c8c8c;color:#fff;padding:0 6px">unknown</span> '
                '· below 0.10 not shaded</div>', unsafe_allow_html=True)
        if show_fric:
            st.caption("Friction: green = easy (sealed road) → red = hard (steep, dense cover, impacted).")
    with right:
        st.markdown(f"**Ranking** — {'proposal weights, baseline' if default_weights else 'your weights / scenario'}")
        tbl = ranked.head(max(top_n, 15))[["live_rank", "site_id", "live_score", "rank_change", "dest_t1_label",
                                           "length_m_t1", "confidence", "live_recon"]].copy()
        tbl["length_m_t1"] = (tbl.length_m_t1 / 1000).round(1)
        tbl["confidence"] = tbl.confidence.round(2)
        tbl["live_recon"] = np.where(tbl.live_recon == "HIGH", VERIFY, "")
        tbl.columns = ["Rank", "Site", "Score", "Δ rank", "Nearest hospital", "Route km", "Confidence", "Check"]
        st.dataframe(tbl, hide_index=True, width="stretch", height=560,
                     column_config={"Δ rank": st.column_config.NumberColumn(help="Change vs baseline rank (+ = moved up)"),
                                    "Confidence": st.column_config.NumberColumn(help=CONF_HELP)})
        st.download_button("Download ranking (CSV)", ranked.to_csv(index=False).encode(),
                           "shoregate_ranking.csv", "text/csv", width="stretch")


# ---------------------------------------------------------------------------
# Compare shortlist (the sites that stay in the top five in every sensitivity scenario)
# ---------------------------------------------------------------------------
with tab_short:
    st.markdown(f"### The robust shortlist: {len(robust)} sites in the top five in all 12 scenarios")
    st.markdown("The finding is not only that one site wins, but that these sites survive every weight change "
                "we tried. Compare them side by side; exact values are in the Site card.")
    sl = ranked[ranked.site_id.isin(robust)].copy()
    cols_ = st.columns(len(sl))
    for col_, (_, r) in zip(cols_, sl.iterrows()):
        flag_ = r.live_recon == "HIGH"
        badge = (f'<span style="background:{RED};color:#fff;padding:2px 8px;border-radius:999px;font-size:0.75rem;font-weight:700">⚠ VERIFY FIRST</span>'
                 if flag_ else f'<span style="background:#E8F6EF;color:#0F7A52;padding:2px 8px;border-radius:999px;font-size:0.75rem;font-weight:700">✓ standard checks</span>')
        rr = f"#{int(r.rank_best)} in 12/12" if r.rank_best == r.rank_worst else f"#{int(r.rank_best)}–{int(r.rank_worst)}, top 5 in 12/12"
        road_ = "on road" if r.road_dist_m == 0 else f"{r.road_dist_m:.0f} m to road"
        col_.markdown(f"""
<div style="border:1px solid {'#F3C1BF' if flag_ else '#E6EAF0'};border-radius:14px;padding:14px 16px;background:#fff;min-height:236px">
 <div style="display:flex;justify-content:space-between;align-items:baseline">
  <span style="font-size:1.35rem;font-weight:750;color:{NAVY}">#{int(r.live_rank)} {r.site_id}</span>
  <span style="font-size:1.15rem;font-weight:700;color:{NAVY}">{r.live_score:.1f}</span></div>
 <div style="font-size:0.85rem;color:{MUTED};margin:2px 0 8px 0">{rr}</div>
 <div style="font-size:0.92rem;line-height:1.55;color:#17212B">{r.dest_t1_label}<br><b>{r.length_m_t1 / 1000:.2f} km</b> · {r.road_share_t1:.0%} on road<br>
 {road_}<br>coverage <b>{r.confidence:.0%}</b> ({coverage_label(r.confidence).split()[0]})</div>
 <div style="margin-top:10px">{badge}</div>
</div>""", unsafe_allow_html=True)
    st.markdown("")
    sl["Check"] = np.where(sl.live_recon == "HIGH", VERIFY, "")
    sl["Hazard (landing zone)"] = sl.lz_impact.apply(lambda v: "unknown" if pd.isna(v) else f"{v:.2f}")
    sl["Road access"] = np.where(sl.road_dist_m == 0, "on road",
                                 sl.road_dist_m.round(0).astype(int).astype(str) + " m "
                                 + np.where(sl.nearest_road_class == 1, "(sealed)", "(unsealed)"))
    sl["Rank range (12)"] = sl.rank_best.astype(int).astype(str) + "–" + sl.rank_worst.astype(int).astype(str)
    sl["Hospital route"] = (sl.length_m_t1 / 1000).map("{:.2f}".format) + " km to " + sl.dest_t1_label
    sl["On road"] = (sl.road_share_t1 * 100).round(0).astype(int).astype(str) + "%"
    tbl_s = sl[["live_rank", "site_id", "live_score", "Rank range (12)", "Hospital route", "On road", "Road access",
                "Hazard (landing zone)", "confidence", "Check"]].rename(
        columns={"live_rank": "Rank", "site_id": "Site", "live_score": "Score", "confidence": "Data confidence"})
    tbl_s["Data confidence"] = tbl_s["Data confidence"].round(2)
    st.markdown("**Detailed comparison**")
    st.dataframe(tbl_s, hide_index=True, width="stretch",
                 column_config={"Data confidence": st.column_config.NumberColumn(help=CONF_HELP),
                                "Hazard (landing zone)": st.column_config.TextColumn(
                                    help="Surface-relative impact excess in the 250 m landing zone (0 = typical, 1 = maximal)"),
                                "Check": st.column_config.TextColumn(help="Reason given in the sentence below the table")})
    for _, r in sl.iterrows():
        st.markdown("- " + why_sentence(r, W))
    pts_ = pd.DataFrame([{"Site": r.site_id, "Criterion": LABEL[k].split(" (")[0], "Points": W[k] * r[f"live_{k}"] * 100}
                         for _, r in sl.iterrows() for k in W])
    bars = alt.Chart(pts_).mark_bar(cornerRadiusEnd=3).encode(
        y=alt.Y("Site:N", sort=sl.site_id.tolist(), title=None),
        x=alt.X("sum(Points):Q", title="Score points (stacked by criterion)"),
        color=alt.Color("Criterion:N", sort=[LABEL[k].split(" (")[0] for k in W],
                        scale=alt.Scale(range=["#2a78d6", "#1baf7a", "#eda100", "#e87ba4", "#6a5acd"]),
                        legend=alt.Legend(orient="bottom", title=None)),
        order=alt.Order("Criterion:N"),
        tooltip=["Site", "Criterion", alt.Tooltip("Points:Q", format=".1f")])
    st.altair_chart(bars.properties(height=60 + 34 * len(sl)), width="stretch")
    st.download_button("Download shortlist (CSV)", tbl_s.to_csv(index=False).encode(),
                       "shoregate_shortlist.csv", "text/csv")


# ---------------------------------------------------------------------------
# Site card
# ---------------------------------------------------------------------------
with tab_card:
    s = ranked[ranked.site_id == st.session_state.sel].iloc[0]
    flag = s.live_recon == "HIGH"
    st.markdown(f"### Landing site {s.site_id} — rank {s.live_rank} of {len(ranked)}"
                + (f"  ·  :red[**{VERIFY}**]" if flag else ""))
    if flag:
        st.warning(f"Verify before relying on this site: **{s.live_recon_reason}**. "
                   + ("The sea approach is in the sheltered channel near the lagoon entrance; depth and reef "
                      "conditions are unknown (no bathymetry in this prototype). " if "lagoon" in s.live_recon_reason else "")
                   + ("Less than half of the landing zone and hospital route has valid impact evidence (mostly tree cover)."
                      if "weak evidence" in s.live_recon_reason else ""))
    a, b, c, d = st.columns(4)
    a.metric("Score", f"{s.live_score:.1f}")
    b.metric("Rank range (12 scenarios)", f"{int(s.rank_best)}–{int(s.rank_worst)}")
    c.metric("Impact-data coverage", f"{s.confidence:.0%}", coverage_label(s.confidence), delta_color="off",
             help=CONF_HELP + " Used as the 'Data confidence' criterion in the score.")
    d.metric("Road access", "on road" if s.road_dist_m == 0 else f"{s.road_dist_m:.0f} m",
             "sealed" if s.nearest_road_class == 1 else "unsealed", delta_color="off")
    st.caption(f"Location: {s.lat:.5f}°, {s.lon:.5f}°  ·  UTM 1S  E {s.utm_e:.0f}  N {s.utm_n:.0f}  ·  "
               f"{s.dist_lagoon_mouth_km:.1f} km from the lagoon mouth")

    st.markdown("**Routes to the nearest destination in each tier** (least-cost on the post-event friction surface)")
    rt = pd.DataFrame([{
        "Tier": TIER_NAME[t], "Destination": s[f"dest_t{t}_label"],
        "Route length (km)": round(s[f"length_m_t{t}"] / 1000, 2),
        "On road": f"{s[f'road_share_t{t}']:.0%}",
        "Route cost (relative units)": f"{s[f'cost_t{t}']:,.0f}",
        "Mean impact along route": None if pd.isna(s[f"impact_mean_t{t}"]) else round(s[f"impact_mean_t{t}"], 3),
        "Impact evidence along route": f"{s[f'impact_known_share_t{t}']:.0%}",
        "Max slope (°)": round(s[f"slope_max_t{t}"], 1),
    } for t in (1, 2, 3)])
    st.dataframe(rt, hide_index=True, width="stretch")
    st.caption("Route cost is accumulated friction (1 unit = 1 m of flat, sealed, unimpacted road); it is not a distance.")

    st.markdown(why_sentence(s, W))
    st.markdown("**Why it scores this way** — contribution of each criterion (weight × normalised criterion)")
    SHORT = {"hazard_safety": "Hazard safety", "corridor_efficiency": "Corridor (hospital)",
             "road_connectivity": "Road connectivity", "destination_access": "Destination access",
             "data_confidence": "Data confidence"}
    contrib = pd.DataFrame({"Criterion": [SHORT[k] for k in W],
                            "Points": [W[k] * s[f"live_{k}"] * 100 for k in W],
                            "Max": [W[k] * 100 for k in W]})
    base = alt.Chart(contrib).encode(y=alt.Y("Criterion:N", sort=None, title=None))
    chart = (base.mark_bar(color="#e6e6e6", cornerRadiusEnd=4).encode(x=alt.X("Max:Q", title="Score points"))
             + base.mark_bar(color="#2a78d6", cornerRadiusEnd=4).encode(
                 x="Points:Q", tooltip=[alt.Tooltip("Criterion:N"), alt.Tooltip("Points:Q", format=".1f"),
                                        alt.Tooltip("Max:Q", format=".1f")]))
    st.altair_chart(chart.properties(height=200), width="stretch")
    st.caption("Grey bar = maximum possible points for that criterion with the current weights.")

    st.markdown("**Landing zone (250 m)**")
    lz1, lz2 = st.columns(2)
    lz1.metric("Impact excess in landing zone", "unknown" if pd.isna(s.lz_impact) else f"{s.lz_impact:.2f}",
               help="Surface-relative post-event impact (0 = typical for its surface, 1 = maximal)")
    lz2.metric("Landing zone with impact evidence", f"{s.lz_confidence:.0%}")
    st.info("Not assessed here: water depth, approach, beach gradient, surf, tide, obstacles, bearing capacity. "
            "These must come from charts, aerial reconnaissance and ground survey.")


# ---------------------------------------------------------------------------
# Route explorer (concept adapted from Irene's "Shore Gate Interactive Routing" app)
# ---------------------------------------------------------------------------
ALT_COLORS = ["#ff5cad", "#ffd166", "#22d3ee"]          # route A, B, C
COND = {"impact": "Post-event (impact-aware)", "baseline": "Undamaged-road counterfactual", "compare": "Compare both"}


@st.cache_resource
def load_grid():
    return RoutingGrid(D / "routing_grid.npz")


@st.cache_data
def dest_table():
    rows = []
    for f in dests["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        typ = str(p.get("dest_type", "")).replace("_", " ")
        nm = (p.get("name") or "").replace("Hosptial", "Hospital") or f"Unnamed {typ}"
        rows.append(dict(dest_id=p.get("dest_id"), name=nm, type=typ, tier=int(p.get("tier", 3)), lon=lon, lat=lat))
    t = pd.DataFrame(rows).sort_values(["tier", "name"]).reset_index(drop=True)
    t["label"] = t.apply(lambda r: f"{TIER_NAME[r.tier]} · {r['name']} ({r['dest_id']})", axis=1)
    return t


@st.cache_data(show_spinner="Finding alternative routes…")
def compute_routes(start, end, scenario, k):
    g = load_grid()
    out = []
    for r in g.alternatives(start, end, scenario, k=k):
        p = r.pop("path")
        lon, lat = g.rc_to_lonlat(p[::3, 0], p[::3, 1])
        lon_e, lat_e = g.rc_to_lonlat(p[-1:, 0], p[-1:, 1])
        r["coords"] = [(float(a), float(b)) for a, b in zip(lat, lon)] + [(float(lat_e[0]), float(lon_e[0]))]
        r["cells"] = p
        out.append(r)
    return out


def _fmt_imp(v):
    return "unknown" if v is None else f"{v:.2f}"


with tab_route:
    ss = st.session_state
    st.markdown("### Route explorer — compare alternative routes inland")
    st.caption("For one landing point and one destination, find up to three genuinely different least-cost routes "
               "and compare them — with post-event road damage, or with every road restored to its undamaged cost "
               "(same terrain surface; a counterfactual, not a full reconstruction of pre-event conditions). "
               "Concept adapted from Irene's *Shore Gate Interactive Routing* app; here it runs on the "
               "Tongatapu friction surface used everywhere else in this tool.")
    g = load_grid()
    DT = dest_table()
    ss.setdefault("re_click_land", None)
    ss.setdefault("re_click_dest", None)
    ss.setdefault("re_last_click", None)

    c1, c2, c3 = st.columns([1.1, 1.5, 1.2], gap="medium")
    with c1:
        land_mode = st.radio("① Choose landing point", ["Ranked site", "Click on the map"], key="re_land_mode")
        if land_mode == "Ranked site":
            ids = ranked.site_id.tolist()
            st.selectbox("Site", ids, key="re_site", on_change=_select_from, args=("re_site",),
                         format_func=lambda s_: f"{s_} — rank {int(ranked.set_index('site_id').live_rank[s_])}")
    with c2:
        dest_mode = st.selectbox("② Choose destination", ["Nearest hospital", "Nearest school / clinic",
                                                 "Nearest community / worship", "Choose from list", "Click on the map"],
                                 key="re_dest_mode")
        if land_mode == "Click on the map" and dest_mode.startswith("Nearest"):
            st.caption("For a clicked landing point, *nearest* = closest in straight-line distance; "
                       "the route to it is then least-cost.")
        if dest_mode == "Choose from list":
            st.selectbox("Destination (type to search)", DT.label.tolist(), key="re_dest_pick",
                         index=int(DT.index[DT.tier == 1][0]))
    with c3:
        cond = st.radio("③ Choose road condition", list(COND), format_func=COND.get, key="re_cond",
                        help="Undamaged-road counterfactual: same terrain surface, but roads restored to their assumed "
                             "undamaged cost (sealed 1.0, unsealed 1.5, × slope).")
        k = st.slider("Alternative routes", 1, 3, 3, key="re_k")

    clickable = [x for x, on in (("Landing point", land_mode == "Click on the map"),
                                 ("Destination", dest_mode == "Click on the map")) if on]
    click_target = (st.radio("Next map click sets", clickable, horizontal=True, key="re_click_target")
                    if len(clickable) > 1 else (clickable[0] if clickable else None))

    # ---- resolve landing and destination
    land = dest = None
    if land_mode == "Ranked site":
        srow = sites.set_index("site_id").loc[ss.sel]
        land = (float(srow.lon), float(srow.lat), f"{ss.sel}")
    elif ss.re_click_land:
        land = (*ss.re_click_land, "Clicked landing point")
    tier_of = {"Nearest hospital": 1, "Nearest school / clinic": 2, "Nearest community / worship": 3}
    if dest_mode in tier_of and land:
        t = tier_of[dest_mode]
        if land_mode == "Ranked site":
            did = srow[f"dest_t{t}"]
            drow = DT[DT.dest_id == did].iloc[0]
            note = "nearest by least-cost route"
        else:
            cand = DT[DT.tier == t]
            dd = (cand.lat - land[1]) ** 2 + ((cand.lon - land[0]) * np.cos(np.radians(21.15))) ** 2
            drow = cand.loc[dd.idxmin()]
            note = "nearest by straight-line distance"
        dest = (float(drow.lon), float(drow.lat), f"{drow['name']} — {note}")
    elif dest_mode == "Choose from list":
        drow = DT[DT.label == ss.re_dest_pick].iloc[0]
        dest = (float(drow.lon), float(drow.lat), drow["name"])
    elif dest_mode == "Click on the map" and ss.re_click_dest:
        dest = (*ss.re_click_dest, "Clicked destination")

    results, msg, snaps = {}, None, []
    if land and dest:
        a, b = g.snap(land[0], land[1]), g.snap(dest[0], dest[1])
        snaps = [(nm_, d_[2]) for nm_, d_, clicked in (("Landing point", a, land_mode == "Click on the map"),
                                                       ("Destination", b, dest_mode == "Click on the map"))
                 if clicked and d_ is not None]
        if a is None or b is None:
            msg = "No passable land within 500 m of the " + ("landing point." if a is None else "destination.")
        elif a[:2] == b[:2]:
            msg = "Landing point and destination fall on the same 10 m cell."
        else:
            for scn in (["impact", "baseline"] if cond == "compare" else [cond]):
                results[scn] = compute_routes(a[:2], b[:2], scn, k if cond != "compare" else (k if scn == "impact" else 1))
    elif click_target:
        msg = f"Click the map to set the {click_target.lower()}."

    # ---- map
    left, right = st.columns([3, 2], gap="medium")
    with left:
        pts = [(land[1], land[0])] if land else []
        pts += [(dest[1], dest[0])] if dest else []
        for rs in results.values():
            for r in rs:
                pts += r["coords"]
        if pts:
            P = np.array(pts)
            center = [float(P[:, 0].mean()), float(P[:, 1].mean())]
            span = max(np.ptp(P[:, 1]), np.ptp(P[:, 0]) / np.cos(np.radians(21.15)), 0.004)
            zoom = int(np.clip(np.floor(np.log2(360 * 520 / (256 * span * 1.2))), 11, 17))
        else:
            center, zoom = [-21.165, -175.2], 11
        m2 = folium.Map(location=center, zoom_start=zoom, tiles=None, control_scale=True)
        if basemap == "Satellite":
            folium.TileLayer(
                tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                attr="Esri, Maxar, Earthstar Geographics", name="Satellite").add_to(m2)
        else:
            folium.TileLayer("CartoDB positron", name="Light").add_to(m2)
        if show_imp and (D / "impact_overlay.png").exists() and "impact" in bounds:
            folium.raster_layers.ImageOverlay(str(D / "impact_overlay.png"), bounds=bounds["impact"],
                                              opacity=0.85).add_to(m2)
        draw = results.get("impact") or results.get("baseline") or []
        if cond == "compare" and results.get("baseline"):
            b0 = results["baseline"][0]
            folium.PolyLine(b0["coords"], color="#111111", weight=7, opacity=0.6).add_to(m2)
            folium.PolyLine(b0["coords"], color="#ffffff", weight=4, dash_array="8 8", opacity=1,
                            tooltip=f"Undamaged-road best route: {b0['length_m'] / 1000:.2f} km").add_to(m2)
        for i, r in reversed(list(enumerate(draw))):
            folium.PolyLine(r["coords"], color="#111111", weight=8 if i == 0 else 6, opacity=0.6).add_to(m2)
            folium.PolyLine(r["coords"], color=ALT_COLORS[i], weight=5 if i == 0 else 3.5, opacity=1,
                            tooltip=f"Route {r['id']}: score {r['score']}, {r['length_m'] / 1000:.2f} km, "
                                    f"{r['road_share']:.0%} on road").add_to(m2)
        if land:
            folium.CircleMarker([land[1], land[0]], radius=10, color="#ffffff", weight=3, fill=True,
                                fill_color="#2a78d6", fill_opacity=1, tooltip=f"Landing: {land[2]}").add_to(m2)
        if dest:
            folium.CircleMarker([dest[1], dest[0]], radius=10, color="#ffffff", weight=3, fill=True,
                                fill_color=NAVY, fill_opacity=1, tooltip=f"Destination: {dest[2]}").add_to(m2)
        out2 = st_folium(m2, height=560, use_container_width=True, returned_objects=["last_clicked"], key="re_map")
        clk = (out2 or {}).get("last_clicked")
        if clk and click_target and clk != ss.re_last_click:
            ss.re_last_click = clk
            if click_target == "Landing point":
                ss.re_click_land = (float(clk["lng"]), float(clk["lat"]))
            else:
                ss.re_click_dest = (float(clk["lng"]), float(clk["lat"]))
            st.rerun()
        legend = " ".join(f'<span style="background:#111;color:{c};padding:1px 8px;border-radius:3px">━ route {chr(65 + i)}</span>'
                          for i, c in enumerate(ALT_COLORS[:max(len(draw), 1)]))
        if cond == "compare":
            legend += ' <span style="background:#111;color:#fff;padding:1px 8px;border-radius:3px">┅ undamaged-road best</span>'
        st.markdown(f'<div style="font-size:0.85rem">{legend} · '
                    '<span style="color:#2a78d6">●</span> landing · <span style="color:#173B57">●</span> destination</div>',
                    unsafe_allow_html=True)

    # ---- candidate cards
    with right:
        if msg:
            st.info(msg)
        if land and dest and not msg:
            st.markdown(f"**{land[2]} → {dest[2]}**")
            for nm_, dm in snaps:
                txt = f"{nm_}: routing starts {dm:.0f} m away, at the nearest passable 10 m cell."
                (st.warning(txt + " Check that the clicked point is on land.") if dm > 100 else st.caption(txt))
        if cond == "compare" and results.get("impact") and results.get("baseline"):
            a0, b0 = results["impact"][0], results["baseline"][0]
            ov = path_overlap(a0["cells"], b0["cells"])
            d_len = a0["length_m"] - b0["length_m"]
            same = ov > 0.9
            st.markdown("**Effect of post-event road damage on the best route** (vs undamaged-road counterfactual)")
            m1, m2_, m3 = st.columns(3)
            m1.metric("Route length", f"{a0['length_m'] / 1000:.2f} km", f"{d_len / 1000:+.2f} km vs undamaged",
                      delta_color="inverse")
            m2_.metric("Same corridor", f"{ov:.0%}", help="Share of the post-event best route within 20 m of the undamaged-road best route")
            m3.metric("On road", f"{a0['road_share']:.0%}", f"{(a0['road_share'] - b0['road_share']) * 100:+.0f} pts",
                      delta_color="normal")
            st.caption("The post-event route " + ("follows essentially the same corridor as with undamaged roads."
                                                   if same else "takes a different corridor: damage on the "
                                                   "undamaged-road route makes a detour cheaper."))
            st.divider()
        shown = results.get("impact") if cond in ("impact", "compare") else results.get("baseline")
        if shown:
            st.markdown("**Candidate routes** — " + ("post-event" if cond != "baseline" else "undamaged-road counterfactual"))
            for i, r in enumerate(shown):
                with st.container(border=True):
                    h1, h2 = st.columns([3, 1])
                    h1.markdown(f'<span style="color:{ALT_COLORS[i]};font-size:1.3rem">━</span> '
                                f'**#{i + 1} — Route {r["id"]}**' + ("  ·  best" if i == 0 else ""),
                                unsafe_allow_html=True)
                    h2.markdown(f'<div style="text-align:right;font-size:1.4rem;font-weight:600">{r["score"]}</div>',
                                unsafe_allow_html=True)
                    st.markdown(
                        f"{r['length_m'] / 1000:.2f} km · {r['road_share']:.0%} on road "
                        f"({r['unsealed_share']:.0%} unsealed) · max slope {r['slope_max']:.0f}°  \n"
                        f"Mean impact excess {_fmt_imp(r['impact_mean'])} · impact evidence on "
                        f"{r['evidence_share']:.0%} of route · route cost {r['cost']:,.0f}"
                        + (f" · {r['overlap_with_previous']:.0%} shared with a better route" if i else ""))
            st.caption("Comparative score = 60% route cost + 25% share on road + 15% length, each relative to the "
                       "best displayed route. It compares the displayed routes only; it is not a probability of "
                       "safe access. Route cost is accumulated friction (relative units), not a distance.")
            rows = pd.DataFrame([{"route": r["id"], "score": r["score"], "length_km": round(r["length_m"] / 1000, 3),
                                  "road_share": round(r["road_share"], 3), "impact_mean": r["impact_mean"],
                                  "impact_evidence": round(r["evidence_share"], 3), "slope_max_deg": round(r["slope_max"], 1),
                                  "route_cost": round(r["cost"], 1)} for r in shown])
            st.download_button("Download route comparison (CSV)", rows.to_csv(index=False).encode(),
                               "shoregate_route_comparison.csv", "text/csv", width="stretch")


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------
with tab_sens:
    st.markdown("### Does the shortlist depend on the weights?")
    st.markdown("Each criterion weight was changed by ±20% (others rescaled), plus a conservative scenario "
                "where unknown impact is set to the 90th percentile. **The top five sites stayed in the top five "
                "in all 12 scenarios.**")
    top_sites = sites.sort_values("rank_baseline").site_id.head(10).tolist()
    nice = {"baseline": "Baseline", "conservative_unknown_impact": "Conservative"}
    for k, v in {"hazard_safety": "Hazard", "corridor_efficiency": "Corridor", "road_connectivity": "Road",
                 "destination_access": "Access", "data_confidence": "Confidence"}.items():
        nice[f"{k}_-20%"], nice[f"{k}_+20%"] = f"{v} −20%", f"{v} +20%"
    sl = (sens[sens.site_id.isin(top_sites)].rename(columns=nice)
          .melt(id_vars="site_id", var_name="Scenario", value_name="Rank"))
    order = [nice.get(c, c) for c in sens.columns.drop("site_id")]
    heat = alt.Chart(sl).mark_rect(stroke="white", strokeWidth=2).encode(
        x=alt.X("Scenario:N", sort=order, axis=alt.Axis(labelAngle=-40)),
        y=alt.Y("site_id:N", sort=top_sites, title="Site (baseline order)"),
        color=alt.Color("Rank:Q", scale=alt.Scale(domain=[1, 15], range=["#163f75", "#c5dbf5"], clamp=True),
                        legend=alt.Legend(title="Rank")),
        tooltip=["site_id", "Scenario", "Rank"])
    txt = alt.Chart(sl).mark_text(fontSize=11).encode(
        x=alt.X("Scenario:N", sort=order), y=alt.Y("site_id:N", sort=top_sites), text="Rank:Q",
        color=alt.condition("datum.Rank <= 6", alt.value("white"), alt.value("#0b0b0b")))
    st.altair_chart((heat + txt).properties(height=380), width="stretch")
    st.caption("Fixed run from the notebook (proposal weights). Use the sidebar to try your own weights; the map and "
               "ranking update live, and 'Δ rank' shows the change from the baseline.")


# ---------------------------------------------------------------------------
# Reconnaissance list
# ---------------------------------------------------------------------------
with tab_recon:
    st.markdown(f"### {VERIFY}: reconnaissance target list")
    st.markdown("Sites that rank well but where the evidence is weak or the sea approach is uncertain. "
                "Check these first with aerial reconnaissance.")
    rc = ranked[ranked.live_recon == "HIGH"].copy()
    check = {
        "approach near lagoon mouth": "Approach depth, reef and channel conditions at the lagoon entrance",
        "top-ranked, weak evidence": "Ground conditions and damage on landing zone and route (impact not observable under tree cover)",
        "impact unknown": "All post-event conditions (no impact evidence)",
    }
    rc["What to verify"] = rc.live_recon_reason.apply(lambda x: " · ".join(check[k] for k in x.split("; ") if k in check))
    rc["confidence"] = rc.confidence.round(2)
    show = rc[["live_rank", "site_id", "live_score", "confidence", "dist_lagoon_mouth_km", "live_recon_reason",
               "What to verify", "lat", "lon"]]
    show.columns = ["Rank", "Site", "Score", "Confidence", "Lagoon mouth (km)", "Reason", "What to verify", "Lat", "Lon"]
    st.dataframe(show, hide_index=True, width="stretch",
                 column_config={"What to verify": st.column_config.TextColumn(width="large"),
                                "Reason": st.column_config.TextColumn(width="medium")})
    st.download_button("Download verify-first list (CSV)", show.to_csv(index=False).encode(),
                       "shoregate_recon_list.csv", "text/csv")
    st.caption(f"Rule: impact unknown; or top-{RECON_TOP_N} with data confidence < {CONF_LOW}; "
               f"or top-{RECON_TOP_N} within {MOUTH_FLAG_KM:.0f} km of the lagoon mouth.")


# ---------------------------------------------------------------------------
# Method & limits
# ---------------------------------------------------------------------------
def stat_html(value, label, color=None):
    return (f'<div style="background:#F7F9FC;border:1px solid #E6EAF0;border-radius:12px;padding:10px 12px;height:100%">'
            f'<div style="font-size:1.7rem;font-weight:750;color:{color or "#173B57"};line-height:1.2">{value}</div>'
            f'<div style="font-size:0.82rem;color:#667085;line-height:1.35;margin-top:2px">{label}</div></div>')


@st.cache_data
def extreme_weight_test(scenario):
    """Each weight at its maximum (0.5) and at 0, others at proposal values: is the proposal top site still #1?"""
    top0 = rank_sites(sites, DEFAULT_W, "baseline").site_id.iloc[0]
    rows = []
    for k in DEFAULT_W:
        for v in (0.5, 0.0):
            w = dict(DEFAULT_W); w[k] = v
            tot = sum(w.values())
            r = rank_sites(sites, {kk: vv / tot for kk, vv in w.items()}, scenario)
            rows.append({"Criterion": LABEL[k].split(" (")[0], "Weight": v, "Top site": r.site_id.iloc[0],
                         "Proposal top 5 still in top 5": int(r.site_id.head(5).isin(
                             rank_sites(sites, DEFAULT_W, "baseline").site_id.head(5)).sum())})
    df = pd.DataFrame(rows)
    return top0, int((df["Top site"] == top0).sum()), len(df), df


with tab_method:
    st.markdown("### How reliable is this?")
    st.markdown("There is no single accuracy for the whole tool: each layer is checked in its own way. "
                "In short, **the impact evidence is a moderate signal, the routing is exact given its inputs, "
                "and the recommendation is robust.**")
    top0, n_same, n_tests, ext = extreme_weight_test("baseline")
    l1, l2, l3 = st.columns(3, gap="medium")
    with l1:
        st.markdown("**1 · Impact map**: can satellites see it?")
        a1, a2 = st.columns(2)
        a1.markdown(stat_html("0.695", "Macro-F1, spatial cross-validation (simple rule 0.526; kappa 0.39)"),
                    unsafe_allow_html=True)
        a2.markdown(stat_html("0.61", "ROC-AUC against independent Copernicus EMSR558 roads (0.58 within image)"),
                    unsafe_allow_html=True)
        st.markdown(f"""
<div style="font-size:0.9rem;line-height:1.6;margin-top:10px">
Cart tracks <b>0.79</b> · village roads <b>0.51</b><br>
Damaged/destroyed buildings <b>0.58–0.61</b> vs built-up background <b>0.51</b><br>
Evidence available on <b>42%</b> of passable land; the rest is unknown
</div>""", unsafe_allow_html=True)
        st.caption("Good in open country, weak in villages: used as one input of five, not as a damage map.")
    with l2:
        st.markdown("**2 · Routes**: is the path calculation right?")
        b1, b2 = st.columns(2)
        b1.markdown(stat_html("exact", "match with the routing notebook (S001 → Vaiola 4,451 m in both)"),
                    unsafe_allow_html=True)
        b2.markdown(stat_html("336", "routes: 112 sites × hospital, school/clinic, community point"),
                    unsafe_allow_html=True)
        st.markdown("""
<div style="font-size:0.9rem;line-height:1.6;margin-top:10px">
Exact <i>given its inputs</i>: travel-cost values and OpenStreetMap roads (15 Jan 2022).<br>
<b>Not yet checked</b> against real travel times or field reports.
</div>""", unsafe_allow_html=True)
        st.caption("Route cost is relative effort, not a distance; kilometres come from the route length.")
    with l3:
        st.markdown("**3 · Ranking**: is the recommendation robust?")
        c1_, c2_ = st.columns(2)
        c1_.markdown(stat_html("12 / 12", "sensitivity scenarios keep the same top 5 (±20% weights + conservative)"),
                     unsafe_allow_html=True)
        c2_.markdown(stat_html(f"{n_same} / {n_tests}", f"extreme weight settings keep {top0} first (each weight at 0.5 and 0)"),
                     unsafe_allow_html=True)
        lost = ext[ext["Top site"] != top0]
        st.markdown(f"""
<div style="font-size:0.9rem;line-height:1.6;margin-top:10px">
There is no ground truth for "best beach", so we test robustness instead.<br>
{top0} loses first place only when: {"; ".join(f"{r.Criterion} = {r.Weight:g} (→ {r['Top site']})" for _, r in lost.iterrows()) or "never"}.
</div>""", unsafe_allow_html=True)
        st.caption("The lower ranks do move with the weights, which is why the partner should set them with us.")
    with st.expander("Why not the transfer model (Track A)?"):
        st.markdown("""
Random Forest on 24 Sentinel-1/2 features with xBD building-damage labels, trained on Palu 2018:
damaged-class F1 **0.65** on held-out Palu patches, but **0.10** on an unseen event (Sunda Strait 2018,
recall 0.19, precision 0.07); on Tongatapu it flagged 51% of built-up pixels as damaged. It did not transfer
between events, so the app uses the impact layer that held up.
""")
    with st.expander("Extreme weight test (each weight at 0.5 and at 0)"):
        st.dataframe(ext, hide_index=True, width="stretch")
    st.divider()
    st.markdown("### Evidence behind the recommendation")
    with st.expander("Important limitations", expanded=True):
        st.markdown("""
- **Sea side not assessed:** no bathymetry, tides, surf, reef, beach gradient or obstacles. The screen says where a
  landing *could* connect inland, not whether a craft can beach there.
- Impact evidence covers ~42% of passable land; tree-covered areas are **unknown**, never treated as safe.
- Impact-data coverage (the *data confidence* criterion) describes how much of a site has evidence; it does not mean a site is safe.
- Destination tiers and weights are provisional (pending partner input). OSM may be incomplete.
- Route cost is a relative friction measure, not a distance or travel time.
""")
    with st.expander("1 · Impact model"):
        st.markdown("""
Random Forest (Model 2B) on Sentinel-2 change (Oct–Dec 2021 vs 17–24 Jan 2022) and Sentinel-1 (27 Jan 2022),
trained on ALOS-2 Damage Proxy Map labels. Spatial-block cross-validation: Macro-F1 **0.695** (one-rule baseline 0.526).
Only valid on grass/crop, built-up and bare surfaces; the map shows *excess* impact above what is typical for each surface.
""")
    with st.expander("2 · Independent validation (Copernicus EMSR558)"):
        st.markdown("""
Against Copernicus EMSR558 damage grading (Pléiades, 17–20 Jan 2022), damaged/destroyed roads scored higher than roads
with no visible damage: ROC-AUC **0.61** (95% CI 0.57–0.65; 0.58 within the same source image), i.e. modest
discrimination. Damaged and destroyed buildings scored above the built-up background (0.58–0.61 vs 0.51).
By road type: cart tracks 0.79 (45 damaged segments), local roads 0.51 (102). Bootstrap intervals ignore spatial
correlation, so subgroup values are indicative (script `16_validation_figures.py`, `validation_metrics_v2.csv`).
The model is therefore used as a continuous impact-likelihood input, not a damage map.
""")
    with st.expander("3 · Friction surface and routing"):
        st.markdown("""
10 m cells: ESA WorldCover land cover × slope (×1 < 5°, ×1.5 at 5–15°, ×3 at 15–30°, impassable > 30°). OSM roads
(15 Jan 2022) cost 1.0 sealed / 1.5 unsealed and are slowed where impact excess is above the typical level for their
surface. 1 cost unit = 1 m of flat, sealed, undamaged road. Least-cost routes (scikit-image MCP_Geometric) to the
nearest hospital, school/clinic and community point: 336 routes.
""")
    with st.expander("4 · Landing-site screening"):
        st.markdown("""
Open-sea coast of main Tongatapu every ~500 m; cliffs (> 15° within 100 m) and mangrove/wetland frontage excluded;
Fangaʻuta/Fangakakau Lagoon (28 km², connected to the sea) excluded by closing its mouth at 21.1534° S → 112 sites.
""")
    with st.expander("5 · Scoring (MCDA) and sensitivity"):
        st.markdown("""
Five criteria, min–max normalised across the 112 sites, weighted sum × 100. Proposal weights: hazard safety 0.25,
corridor efficiency 0.25, road connectivity 0.20, destination access 0.15, data confidence 0.15.
Sensitivity: each weight ±20% (others rescaled) plus a conservative scenario (unknown impact at the 90th percentile)
= 12 scenarios; S001–S005 stay in the top five in all 12. These scenarios are precomputed around the proposal weights.
""")
    with st.expander("6 · Route explorer"):
        st.markdown("""
Concept from Irene's *Shore Gate Interactive Routing* app. Up to three distinct routes between one landing point and
one destination, found by making the cells within 20 m of each route 1.8× costlier and searching again (kept only if
≤ 85% overlaps an earlier route). The *undamaged-road counterfactual* uses the same surface with every road at its
undamaged cost (sealed 1.0, unsealed 1.5, × slope); off-road costs are unchanged. Comparative score: 60% cost,
25% share on road, 15% length, relative to the best displayed route.
""")
    st.caption(f"Run parameters: {json.dumps(params)}")
