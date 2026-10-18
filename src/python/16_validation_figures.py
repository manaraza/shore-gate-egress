"""
16_validation_figures.py  -  Shore-Gate: Egress
Impact score (impact_score_v1) vs Copernicus EMSR558 AOI01 grading.

Inputs (from GEE script 11_validate_impact_emsr558, v2 exports):
  emsr558_roads_scores_v2.csv      one row per road segment, mean/max score
  emsr558_buildings_scores_v2.csv  one row per graded building, mean score

Outputs:
  validation_metrics_v2.csv
  fig_validation_roc_roads.png
  fig_validation_distributions.png

Notes
- Rows with no score (outside the impact-model domain) are dropped.
- Bootstrap CIs resample features independently within strata. Road
  segments and buildings are spatially clustered, so these intervals are
  optimistic (too narrow). A spatial block bootstrap needs feature
  coordinates, which the v2 CSVs do not carry.
- Stratified AUC = AUC computed only over (positive, negative) pairs that
  share a stratum (source image and/or road type), pooled across strata.
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import mannwhitneyu
from sklearn.metrics import roc_auc_score, roc_curve

SEED = 42
N_BOOT = 1000
BUILT_BG_MEAN = 0.509          # built-up background mean (script 11 bgStats)
rng = np.random.default_rng(SEED)

roads = pd.read_csv('emsr558_roads_scores_v2.csv')
bldg = pd.read_csv('emsr558_buildings_scores_v2.csv')
print('roads without score:', roads['mean'].isna().sum(), 'of', len(roads))
print('buildings without score:', bldg['mean'].isna().sum(), 'of', len(bldg))
roads = roads.dropna(subset=['mean']).reset_index(drop=True)
bldg = bldg.dropna(subset=['mean']).reset_index(drop=True)

roads['rtype'] = roads['info'].map({
    '21120-Primary Road': 'Primary/secondary road',
    '21121-Secondary Road': 'Primary/secondary road',
    '21122-Local Road': 'Local road',
    '21124-Cart Track': 'Cart track'})


# ---------------------------------------------------------------------
def strat_auc(df, strata):
    """Pairwise AUC within strata, pooled (Mann-Whitney U / n_pairs)."""
    if not strata:
        return roc_auc_score(df.y, df.s)
    num = den = 0.0
    for _, g in df.groupby(strata):
        p, n = g.loc[g.y, 's'].values, g.loc[~g.y, 's'].values
        if len(p) and len(n):
            num += mannwhitneyu(p, n).statistic
            den += len(p) * len(n)
    return num / den


def boot_auc(df, strata):
    groups = ([g.index.values for _, g in df.groupby(strata)]
              if strata else [df.index.values])
    out = []
    for _ in range(N_BOOT):
        idx = np.concatenate([rng.choice(ix, len(ix)) for ix in groups])
        s = df.loc[idx].reset_index(drop=True)
        if s.y.all() or (~s.y).all():
            continue
        out.append(strat_auc(s, strata))
    return np.percentile(out, [2.5, 97.5])


def boot_mean(x):
    x = np.asarray(x)
    return np.percentile([x[rng.integers(0, len(x), len(x))].mean()
                          for _ in range(N_BOOT)], [2.5, 97.5])


rows = []

def add_auc(test, df, strata, note=''):
    a = strat_auc(df, strata)
    lo, hi = boot_auc(df, strata)
    rows.append(dict(test=test, stratified_by='+'.join(strata) or 'none',
                     n_pos=int(df.y.sum()), n_neg=int((~df.y).sum()),
                     auc=round(a, 3), ci_lo=round(lo, 3), ci_hi=round(hi, 3),
                     note=note))


# --- Roads: Damaged/Destroyed (cls 1) vs No visible damage (cls 0) ----
r = roads[roads.cls.isin([0, 1])].copy()
r['y'] = r.cls == 1
r['s'] = r['mean']
add_auc('roads: damaged+destroyed vs none', r, [], 'headline, pooled')
add_auc('roads: damaged+destroyed vs none', r, ['dmg_src_id'], 'within source image')
add_auc('roads: damaged+destroyed vs none', r, ['rtype'], 'within road type')
add_auc('roads: damaged+destroyed vs none', r, ['dmg_src_id', 'rtype'], 'within source x type')
for t in ['Local road', 'Cart track']:
    add_auc(f'roads ({t}): damaged+destroyed vs none', r[r.rtype == t].reset_index(drop=True), [])
for src in sorted(r.dmg_src_id.unique()):
    add_auc(f'roads (source {src}): damaged+destroyed vs none',
            r[r.dmg_src_id == src].reset_index(drop=True), [])
rmax = r.copy(); rmax['s'] = rmax['max']
add_auc('roads: damaged+destroyed vs none (segment MAX score)', rmax, [], 'mean is the better summary')
r2 = roads[roads.cls.isin([0, 2])].copy(); r2['y'] = r2.cls == 2; r2['s'] = r2['mean']
add_auc('roads: possibly damaged vs none', r2, [])

# --- Buildings: Damaged/Destroyed vs Possibly damaged -----------------
b = bldg.copy()
b['y'] = b.damage_gra.isin(['Damaged', 'Destroyed'])
b['s'] = b['mean']
add_auc('buildings: damaged+destroyed vs possibly damaged', b, [], 'pooled')
add_auc('buildings: damaged+destroyed vs possibly damaged', b, ['dmg_src_id'], 'within source image')

# --- Building grade means vs built-up background -----------------------
for g in ['Destroyed', 'Damaged', 'Possibly damaged']:
    x = bldg.loc[bldg.damage_gra == g, 'mean']
    lo, hi = boot_mean(x)
    rows.append(dict(test=f'buildings ({g}): mean score', stratified_by='none',
                     n_pos=len(x), n_neg=np.nan, auc=round(x.mean(), 3),
                     ci_lo=round(lo, 3), ci_hi=round(hi, 3),
                     note=f'value = mean score; built-up background = {BUILT_BG_MEAN}'))

metrics = pd.DataFrame(rows)
metrics.to_csv('validation_metrics_v2.csv', index=False)
pd.set_option('display.width', 200)
print(metrics.to_string(index=False))


# ---------------------------------------------------------------------
# Figures (light surface, recessive axes, text in ink colours)
INK, INK2, GRID, SURF = '#0b0b0b', '#52514e', '#d9d8d4', '#fcfcfb'
C1, C2, C3 = '#2a78d6', '#eb6834', '#1baf7a'          # categorical slots 1-3
SEQ = ['#c5dbf5', '#8bb7ea', '#4a8fdd', '#1f5fae']     # one hue, light -> dark

plt.rcParams.update({
    'font.size': 10, 'axes.edgecolor': GRID, 'axes.labelcolor': INK2,
    'xtick.color': INK2, 'ytick.color': INK2, 'axes.facecolor': SURF,
    'figure.facecolor': SURF, 'axes.spines.top': False,
    'axes.spines.right': False, 'axes.titlecolor': INK,
    'axes.titlesize': 11, 'axes.titleweight': 'bold', 'axes.titlelocation': 'left'})


def auc_of(test, strat='none'):
    m = metrics[(metrics.test == test) & (metrics.stratified_by == strat)].iloc[0]
    return m.auc, m.ci_lo, m.ci_hi


# Figure 1: ROC, roads
fig, ax = plt.subplots(figsize=(5.2, 5.0))
ax.plot([0, 1], [0, 1], color=GRID, lw=1.2, ls='--', zorder=1)
series = [('All roads', r, C1, 'roads: damaged+destroyed vs none'),
          ('Cart tracks', r[r.rtype == 'Cart track'], C2,
           'roads (Cart track): damaged+destroyed vs none'),
          ('Local roads', r[r.rtype == 'Local road'], C3,
           'roads (Local road): damaged+destroyed vs none')]
for name, df, col, key in series:
    fpr, tpr, _ = roc_curve(df.y, df.s)
    a, lo, hi = auc_of(key)
    ax.plot(fpr, tpr, color=col, lw=2, zorder=3,
            label=f'{name}  AUC {a:.2f} ({lo:.2f}-{hi:.2f}), n+={int(df.y.sum())}')
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_aspect('equal')
ax.set_xlabel('False positive rate (undamaged roads flagged)')
ax.set_ylabel('True positive rate (damaged roads flagged)')
ax.set_title('Impact score vs EMSR558 road damage')
ax.grid(color=GRID, lw=0.6, alpha=0.6)
leg = ax.legend(loc='lower right', frameon=False, fontsize=8, labelcolor=INK)
fig.text(0.02, 0.01, 'Damaged + destroyed vs no visible damage.\n95% CIs: feature bootstrap '
         '(ignores spatial clustering, so optimistic).', fontsize=7, color=INK2)
fig.tight_layout(rect=(0, 0.05, 1, 1))
fig.savefig('fig_validation_roc_roads.png', dpi=200)
plt.close(fig)


# Figure 2: score distributions by EMSR grade
def boxes(ax, data, labels, colors, title):
    bp = ax.boxplot(data, orientation='horizontal', widths=0.5, patch_artist=True,
                    showfliers=False, medianprops=dict(color=INK, lw=1.5),
                    whiskerprops=dict(color=INK2, lw=1), capprops=dict(color=INK2, lw=1))
    for patch, c in zip(bp['boxes'], colors):
        patch.set(facecolor=c, edgecolor=SURF, lw=2)
    for i, d in enumerate(data, start=1):
        ax.text(1.0, i, f' n={len(d)}', va='center', fontsize=8, color=INK2,
                transform=ax.get_yaxis_transform())
    ax.set_yticks(range(1, len(labels) + 1), labels)
    ax.set_xlim(0, 1); ax.set_title(title)
    ax.grid(axis='x', color=GRID, lw=0.6, alpha=0.6)


grades_r = ['No visible damage', 'Possibly damaged', 'Damaged', 'Destroyed']
grades_b = ['Possibly damaged', 'Damaged', 'Destroyed']
fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.8))
boxes(a1, [roads.loc[roads.damage_gra == g, 'mean'].values for g in grades_r],
      grades_r, SEQ, 'Road segments')
boxes(a2, [bldg.loc[bldg.damage_gra == g, 'mean'].values for g in grades_b],
      grades_b, SEQ[1:], 'Graded buildings')
a2.axvline(BUILT_BG_MEAN, color=INK2, lw=1.2, ls='--')
a2.text(BUILT_BG_MEAN, 3.45, f' built-up background mean {BUILT_BG_MEAN}',
        fontsize=8, color=INK2, va='center')
for a in (a1, a2):
    a.set_xlabel('Mean impact score per feature')
fig.suptitle('Impact score by EMSR558 damage grade (AOI01, Pleiades 17-20 Jan 2022)',
             x=0.01, ha='left', fontsize=11, fontweight='bold', color=INK)
fig.tight_layout(rect=(0, 0, 0.97, 0.93), w_pad=3)
fig.savefig('fig_validation_distributions.png', dpi=200)
plt.close(fig)
print('saved figures')
