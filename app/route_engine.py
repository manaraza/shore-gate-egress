"""
route_engine.py — alternative least-cost routes for the Shore-Gate app (Route explorer tab)

Idea (adapted from Irene's "Shore Gate Interactive Routing" app): for one landing point and one
destination, find up to K genuinely different routes by penalising the cells around each route found
so far, then compare the routes on cost, road use and length. Implemented here on the frozen
Tongatapu friction surface (friction_v1), using the same MCP_Geometric cost model as notebook 15.

Scenarios
- "impact":   post-event friction (friction_v1 — roads degraded by surface-relative impact excess)
- "baseline": the same surface with every road at its undamaged cost (sealed 1.0, unsealed 1.5,
              × slope multiplier); off-road cells are identical in both scenarios.
"""
from __future__ import annotations

import numpy as np
from pyproj import Transformer
from scipy import ndimage as ndi
from skimage.graph import MCP_Geometric

PIX = 10.0
SNAP_MAX_M = 500.0


class RoutingGrid:
    def __init__(self, npz_path):
        z = np.load(npz_path, allow_pickle=False)
        self.cost = {"impact": z["friction_impact"].astype("float64"),
                     "baseline": z["friction_baseline"].astype("float64")}
        for k in self.cost:
            self.cost[k][~np.isfinite(self.cost[k])] = np.inf
        self.excess = z["impact_excess"].astype("float32")          # NaN = impact unknown
        self.road = z["road_class"]                                   # 0 none, 1 sealed, 2 unsealed
        self.slope = z["slope_deg"].astype("float32")
        a, _, c, _, e, f = z["transform"]
        self.a, self.c, self.e, self.f = float(a), float(c), float(e), float(f)
        crs = str(z["crs"])
        self.to_grid = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        self.to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        self.passable = np.isfinite(self.cost["impact"])
        self.shape = self.passable.shape

    # ---------------------------------------------------------------- coordinates
    def lonlat_to_rc(self, lon, lat):
        x, y = self.to_grid.transform(lon, lat)
        return int(np.floor((y - self.f) / self.e)), int(np.floor((x - self.c) / self.a))

    def rc_to_lonlat(self, rows, cols):
        x = self.c + (np.asarray(cols) + 0.5) * self.a
        y = self.f + (np.asarray(rows) + 0.5) * self.e
        lon, lat = self.to_ll.transform(x, y)
        return np.asarray(lon), np.asarray(lat)

    def snap(self, lon, lat, max_m=SNAP_MAX_M):
        """Nearest passable cell within max_m; returns (row, col, snap_distance_m) or None."""
        r, c = self.lonlat_to_rc(lon, lat)
        w = int(max_m / PIX) + 1
        r0, r1 = max(r - w, 0), min(r + w + 1, self.shape[0])
        c0, c1 = max(c - w, 0), min(c + w + 1, self.shape[1])
        if r0 >= r1 or c0 >= c1:
            return None
        rr, cc = np.nonzero(self.passable[r0:r1, c0:c1])
        if rr.size == 0:
            return None
        d = np.hypot(rr + r0 - r, cc + c0 - c)
        i = int(np.argmin(d))
        if d[i] * PIX > max_m:
            return None
        return int(rr[i] + r0), int(cc[i] + c0), float(d[i] * PIX)

    # ---------------------------------------------------------------- routing
    def _window(self, a, b, margin_m=3000):
        m = int(max(margin_m, 0.6 * PIX * max(abs(a[0] - b[0]), abs(a[1] - b[1]))) / PIX)
        r0, r1 = max(min(a[0], b[0]) - m, 0), min(max(a[0], b[0]) + m + 1, self.shape[0])
        c0, c1 = max(min(a[1], b[1]) - m, 0), min(max(a[1], b[1]) + m + 1, self.shape[1])
        return r0, r1, c0, c1

    @staticmethod
    def _path_cost(cost, path):
        """Accumulated cost exactly as MCP_Geometric counts it, in cost-weighted metres."""
        cv = cost[path[:, 0], path[:, 1]]
        step = np.hypot(np.diff(path[:, 0]), np.diff(path[:, 1]))
        return float(((cv[:-1] + cv[1:]) / 2 * step).sum() * PIX)

    def route_metrics(self, path, scenario="impact"):
        r, c = path[:, 0], path[:, 1]
        step = np.hypot(np.diff(r), np.diff(c)) * PIX
        ex = self.excess[r, c]
        known = np.isfinite(ex)
        return {
            "length_m": float(step.sum()),
            "cost": self._path_cost(self.cost[scenario], path),
            "road_share": float((self.road[r, c] > 0).mean()),
            "unsealed_share": float((self.road[r, c] == 2).mean()),
            "impact_mean": float(ex[known].mean()) if known.any() else None,
            "impact_high_share": float((ex[known] >= 0.25).mean()) if known.any() else None,
            "evidence_share": float(known.mean()),
            "slope_max": float(np.nanmax(self.slope[r, c])),
        }

    def alternatives(self, start, end, scenario="impact", k=3, penalty=1.8, radius_cells=2,
                     max_overlap=0.85, max_attempts=12):
        """Up to k distinct least-cost routes from start (row, col) to end (row, col)."""
        r0, r1, c0, c1 = self._window(start, end)
        base = self.cost[scenario][r0:r1, c0:c1]
        work = base.copy()
        s, e = (start[0] - r0, start[1] - c0), (end[0] - r0, end[1] - c0)
        protect = np.zeros(base.shape, bool)
        protect[max(s[0] - 3, 0):s[0] + 4, max(s[1] - 3, 0):s[1] + 4] = True
        protect[max(e[0] - 3, 0):e[0] + 4, max(e[1] - 3, 0):e[1] + 4] = True
        found, masks = [], []
        footprint = ndi.generate_binary_structure(2, 2)
        for _ in range(max_attempts):
            if len(found) >= k:
                break
            mcp = MCP_Geometric(work, fully_connected=True)
            costs, _ = mcp.find_costs([s], [e])
            if not np.isfinite(costs[e]):
                break
            p = np.asarray(mcp.traceback(e))
            on = np.zeros(base.shape, bool)
            on[p[:, 0], p[:, 1]] = True
            buf = ndi.binary_dilation(on, structure=footprint, iterations=radius_cells)
            overlap = max((m_[p[:, 0], p[:, 1]].mean() for m_ in masks), default=0.0)
            if overlap <= max_overlap:
                found.append((p + [r0, c0], overlap))
                masks.append(buf)
            work = np.where(buf & ~protect, work * (penalty if overlap <= max_overlap else penalty * 1.25), work)
        routes = []
        for i, (p, ov) in enumerate(found):
            m = self.route_metrics(p, scenario)
            m.update({"id": chr(65 + i), "path": p, "overlap_with_previous": float(ov)})
            routes.append(m)
        return score_routes(routes)


def score_routes(routes, w_cost=0.60, w_road=0.25, w_len=0.15):
    """Comparative score among the displayed routes (100 = best on every measure).
    Ratio-to-best, not min-max, so two near-identical routes get near-identical scores."""
    if not routes:
        return routes
    best_cost = min(r["cost"] for r in routes)
    best_len = min(r["length_m"] for r in routes)
    for r in routes:
        r["score"] = round(100 * (w_cost * best_cost / r["cost"] + w_road * r["road_share"]
                                  + w_len * best_len / r["length_m"]), 1)
    routes.sort(key=lambda r: -r["score"])
    for i, r in enumerate(routes):          # A = best comparative score
        r["id"] = chr(65 + i)
    return routes


def path_overlap(p, q, radius_cells=2):
    """Share of path p's cells lying within radius_cells of path q (0 = separate, 1 = same corridor)."""
    p, q = np.asarray(p), np.asarray(q)
    lo = np.minimum(p.min(0), q.min(0)) - radius_cells
    hi = np.maximum(p.max(0), q.max(0)) + radius_cells + 1
    m = np.zeros(hi - lo, bool)
    m[q[:, 0] - lo[0], q[:, 1] - lo[1]] = True
    m = ndi.binary_dilation(m, structure=ndi.generate_binary_structure(2, 2), iterations=radius_cells)
    return float(m[p[:, 0] - lo[0], p[:, 1] - lo[1]].mean())
