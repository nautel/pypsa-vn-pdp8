#!/usr/bin/env python3
"""Summary of the run set: figures, tables and key indicators.

Reads the optimised networks and run summaries of the run set (RES_DIR) and runs the analysis scripts in
workflow/scripts/ (scenario_matrix, sensitivity_table, extra_load_analysis, congestion, shapley, robustness_tables,
benchmark_2024, adequacy_margin). Writes into <output-dir>:
  key_indicators.csv   all reported indicators (costs and savings, capacities, emissions, attribution, robustness),
                       rounded as reported
  key_indicators.tex   the same values as LaTeX macros \\R{key}
  tab_*.tex            LaTeX table rows (costs, the plan's capacities, regret, near-optimal space)
  figures/*.png        figures; figures/gen/*.csv the tables behind them
Run (or `snakemake make_summary` in workflow/):
  RES_DIR=<DATA>/expansion/results_v6 python workflow/scripts/make_summary.py <output-dir>
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402
from matplotlib.patches import Wedge  # noqa: E402

HERE = Path(__file__).resolve().parent
CODE = HERE  # all scripts in workflow/scripts
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
RES = Path(os.environ.get("RES_DIR", DATA / "expansion" / "results"))
SUMMARY = Path(sys.argv[1])
FIG = SUMMARY / "figures"
GEN = FIG / "gen"
GEN.mkdir(parents=True, exist_ok=True)
PY = sys.executable
INK, MUTED, SURF = "#1f1e1c", "#6b6a66", "#ffffff"
# PyPSA-Eur/DE technology colours and grouping (pypsa-de/config/plotting.default.yaml); hydro shown separately
sys.path.insert(0, str(CODE))
from plot_vn import PYPSA_COLORS  # noqa: E402
GRP = {"coal": "Coal", "gas": "Gas", "LNG": "Gas", "OCGT": "Gas", "oil": "Gas", "nuclear": "Nuclear",
       "hydro": "Hydro", "biomass": "Imports & biomass", "imports": "Imports & biomass", "onwind": "Onshore wind",
       "offwind": "Offshore wind", "solar": "Solar PV", "rooftop": "Solar PV", "battery": "Battery",
       "PHS": "Pumped hydro"}
ORDER = ["Coal", "Gas", "Nuclear", "Hydro", "Imports & biomass", "Onshore wind", "Offshore wind", "Solar PV",
         "Battery", "Pumped hydro"]
COL = {k: PYPSA_COLORS[k] for k in ORDER}
# PyPSA-Eur plot_power_network colours: AC "rosybrown", DC "darkseagreen"; existing corridors in neutral grey on top
LINE_CUR, LINE_EXP, LINE_DC = "#9e9e9e", "rosybrown", "darkseagreen"
LAND, BORDER = "#f5f5f3", "#cfcfcb"
plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "legend.frameon": False, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                     "axes.spines.right": False})


def summ(y, s, t):
    f = RES / f"{y}_{s}{t}_summary.json"
    return json.loads(f.read_text()) if f.exists() else None


# ---------------- 1. analysis scripts (English number format, summary figure dir) ----------------
env = dict(os.environ, RES_DIR=str(RES), FIG_DIR=str(GEN), NUMFMT="en", MPLBACKEND="Agg", PALETTE="pypsa")
for scr in ["scenario_matrix.py", "sensitivity_table.py", "extra_load_analysis.py", "congestion.py", "shapley.py",
            "robustness_tables.py", "benchmark_2024.py", "adequacy_margin.py"]:
    r = subprocess.run([PY, "-W", "ignore", scr], cwd=CODE, env=env, capture_output=True, text=True)
    print(scr, "rc", r.returncode, (r.stderr.strip().splitlines() or [""])[-1][:200])
VAL = DATA / "figures" / "validation"
subprocess.run([PY, "-W", "ignore", "validate_2024.py"], cwd=CODE, env=dict(env, MPLBACKEND="Agg"),
               capture_output=True, text=True)
for src, dst in [(GEN / "scenario_matrix.png", "fig_scenario_matrix.png"),
                 (GEN / "scenario_matrix_full.png", "fig_scenario_matrix_full.png"), (VAL / "validation_2024_monthly.png", "fig_validation.png"),
                 (GEN / "extra_load_map_2040.png", "fig_extra_load_2040.png"), (GEN / "congestion_map.png", "fig_congestion.png"),
                 (DATA / "figures" / "vn_grid_model_2024.png", "fig_network_2024.png")]:
    if Path(src).exists():
        shutil.copy(src, FIG / dst)

# ---------------- 2. capacity and generation mix ----------------
SCEN = [("PDP8", "pdp8", "_vn"), ("Least cost", "opt", "_vn"), ("CO$_2$ $-$50%", "opt", "_vn_co2half"),
        ("Zero CO$_2$", "opt", "_vn_co2zero_nolim")]
fig, axs = plt.subplots(1, 2, figsize=(10, 4.2))
for ax, (key, unit) in zip(axs, [("capacity_GW", "Capacity [GW]"), ("energy_TWh", "Generation [TWh]")]):
    xt, xl = [], []
    for j, y in enumerate([2035, 2040]):
        for i, (lab, s, t) in enumerate(SCEN):
            d = summ(y, s, t)
            if d is None:
                continue
            v = pd.Series(d[key]).drop(["load shedding"], errors="ignore")
            if key == "energy_TWh":
                v = v.drop(["battery", "PHS"], errors="ignore")  # storage throughput not counted as generation
            v = v.groupby(v.index.map(GRP)).sum().reindex(ORDER).fillna(0)
            x = j * (len(SCEN) + 1) + i
            b = 0.0
            for g, val in v.items():
                if val > 0:
                    ax.bar(x, val, bottom=b, color=COL[g], width=0.8, edgecolor=SURF, linewidth=1.0)
                    b += val
            xt.append(x)
            xl.append(lab)
        ax.text(j * (len(SCEN) + 1) + (len(SCEN) - 1) / 2, 1.02, str(y), transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", fontsize=10, weight="bold", color=INK)
    ax.set_xticks(xt, xl, rotation=30, ha="right", fontsize=8.5)
    ax.set_ylabel(unit)
    ax.grid(axis="y", color="#e6e5e1", linewidth=0.6)
    ax.set_axisbelow(True)
h = [plt.Rectangle((0, 0), 1, 1, color=COL[g]) for g in ORDER[::-1]]
fig.legend(h, ORDER[::-1], loc="center left", bbox_to_anchor=(0.80, 0.55), frameon=False, fontsize=8.5)
fig.subplots_adjust(right=0.79, bottom=0.27, wspace=0.25)
fig.text(0.01, 0.01, "Gas includes domestic gas, LNG, OCGT and oil. Battery and pumped hydro: capacity only (their "
         "throughput is not generation). Zero CO$_2$ shown without build-rate limits.", fontsize=7.5, color=MUTED)
fig.savefig(FIG / "fig_mix.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# ---------------- 3. maps: capacity pies + transmission, PDP8 vs least cost ----------------
vn = gpd.read_file(DATA / "shapes" / "gadm41_VNM_0.json")
cor = pd.read_csv(DATA / "expansion" / "corridors.csv", index_col=0)
# scales chosen relative to map size as in PyPSA-USA (bus_scale 1e5, line_scale 2e3 per interconnect) and PyPSA-Eur
# (linewidth_factor 4e3): 50 GW pie radius ~4 % of map width, 10 GW corridor ~1.8 pt
LWF, RADF = 0.18, 0.045  # line width [pt per GW], pie radius [deg per sqrt(GW)]
fig, axs = plt.subplots(1, 4, figsize=(12, 6.6))
for ax, (y, s, lab) in zip(axs, [(2035, "pdp8", "PDP8 2035"), (2035, "opt", "Least cost 2035"),
                                 (2040, "pdp8", "PDP8 2040"), (2040, "opt", "Least cost 2040")]):
    fn = RES / f"{y}_{s}_vn.nc"
    if not fn.exists():
        ax.set_axis_off()
        continue
    n = pypsa.Network(fn)
    vn.plot(ax=ax, color=LAND, edgecolor=BORDER, linewidth=0.4)
    L = n.links
    for i, r in L.iterrows():
        x0, y0, x1, y1 = n.buses.x[r.bus0], n.buses.y[r.bus0], n.buses.x[r.bus1], n.buses.y[r.bus1]
        tot = r.p_nom_opt if r.p_nom_extendable else r.p_nom
        if r.carrier == "DC":
            if tot > 100:
                ax.plot([x0, x1], [y0, y1], color=LINE_DC, lw=LWF * tot / 1e3, ls=(0, (3, 2)), zorder=2)
            continue
        ex = min(cor.mw.get(f"{r.bus0}|{r.bus1}", 0.0) * 0.7, tot)
        if tot - ex > 100:  # expansion: total width in red, existing drawn on top in purple (PyPSA-ZA plot_network.py)
            ax.plot([x0, x1], [y0, y1], color=LINE_EXP, lw=LWF * tot / 1e3, zorder=2, solid_capstyle="butt")
        if ex > 50:
            ax.plot([x0, x1], [y0, y1], color=LINE_CUR, lw=LWF * ex / 1e3, zorder=3, solid_capstyle="butt")
    cap = pd.concat([n.generators.assign(c=n.generators.p_nom_opt).groupby(["bus", "carrier"]).c.sum(),
                     n.storage_units.assign(c=n.storage_units.p_nom_opt).groupby(["bus", "carrier"]).c.sum()])
    cap = cap.drop("load shedding", level=1, errors="ignore").unstack(fill_value=0)
    cap = cap.T.groupby(cap.columns.map(GRP)).sum().T.reindex(columns=ORDER, fill_value=0) / 1e3
    for b_, row in cap.iterrows():
        tot = row.sum()
        if tot < 0.5:
            continue
        rad, a0 = RADF * np.sqrt(tot), 90.0
        for g, v in row.items():
            if v <= 0:
                continue
            a1 = a0 + 360 * v / tot
            ax.add_patch(Wedge((n.buses.x[b_], n.buses.y[b_]), rad, a0, a1, facecolor=COL[g], edgecolor=SURF,
                               linewidth=0.4, zorder=4))
            a0 = a1
    ax.set_xlim(102, 110)
    ax.set_ylim(8.3, 23.6)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(lab, fontsize=10, color=INK, loc="left")
# size legends (PyPSA-ZA scaled circles) in an inset axes with the same degrees-per-inch scale as the maps
fig.subplots_adjust(wspace=0.02, bottom=0.14, right=0.88)
fig.canvas.draw()
ax0 = axs[0]
bb = ax0.get_window_extent()
deg_per_px = (ax0.get_xlim()[1] - ax0.get_xlim()[0]) / bb.width
lg = fig.add_axes([0.885, 0.35, 0.11, 0.55])
pw, ph = lg.get_window_extent().width, lg.get_window_extent().height
lg.set_xlim(0, pw * deg_per_px)
lg.set_ylim(0, ph * deg_per_px)
lg.set_aspect("equal")
lg.set_axis_off()
X, Y = lg.get_xlim()[1], lg.get_ylim()[1]
lg.text(0.05 * X, Y - 0.3, "Capacity", fontsize=8, color=INK, weight="bold", va="top")
yy = Y - 1.5
for gw in [50, 20, 5]:
    rr = RADF * np.sqrt(gw)
    lg.add_patch(plt.Circle((0.05 * X + 0.8, yy - rr), rr, facecolor="none", edgecolor=INK, lw=0.7))
    lg.text(0.05 * X + 1.8, yy - rr, f"{gw} GW", va="center", fontsize=7.5, color=INK)
    yy -= 2 * rr + 0.45
yy -= 0.4
lg.text(0.05 * X, yy, "Transmission", fontsize=8, color=INK, weight="bold", va="top")
yy -= 1.0
for gw in [10, 5]:
    lg.plot([0.05 * X, 0.05 * X + 1.4], [yy, yy], color=LINE_EXP, lw=LWF * gw, solid_capstyle="butt")
    lg.plot([0.05 * X, 0.05 * X + 1.4], [yy, yy], color=LINE_CUR, lw=LWF * gw * 0.5, solid_capstyle="butt")
    lg.text(0.05 * X + 1.8, yy, f"{gw} GW", va="center", fontsize=7.5, color=INK)
    yy -= 0.8
h = [plt.Rectangle((0, 0), 1, 1, color=COL[g]) for g in ORDER]
h += [plt.Line2D([], [], color=LINE_CUR, lw=3), plt.Line2D([], [], color=LINE_EXP, lw=3),
      plt.Line2D([], [], color=LINE_DC, lw=2, ls=(0, (3, 2)))]
fig.legend(h, ORDER + ["AC existing (2024)", "AC expanded", "HVDC"], loc="lower center", ncol=7, frameon=False,
           fontsize=8, bbox_to_anchor=(0.5, 0.03))
fig.text(0.01, -0.01, "Pie area proportional to installed capacity of each of the 30 regions. Line width proportional to "
         "transfer capacity; the red margin is capacity added beyond the 2024 corridors (purple).", fontsize=7, color=MUTED)
fig.savefig(FIG / "fig_maps.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# ---------------- 4. mean diurnal dispatch ----------------
fig, axs = plt.subplots(2, 2, figsize=(9.5, 6.2), sharex=True, sharey=True)
for r_, (s, lab) in enumerate([("pdp8", "PDP8"), ("opt", "Least cost")]):
    fn = RES / f"2035_{s}_vn.nc"
    if not fn.exists():
        continue
    n = pypsa.Network(fn)
    g = n.generators_t.p.T.groupby(n.generators.carrier).sum().T
    shed = g.pop("load shedding") if "load shedding" in g else 0.0
    su = n.storage_units_t.p.T.groupby(n.storage_units.carrier).sum().T
    gen = pd.concat([g, su.clip(lower=0)], axis=1)
    gen = gen.T.groupby(gen.columns.map(GRP)).sum().T.reindex(columns=ORDER, fill_value=0) / 1e3
    charge = su[[c for c in su if c in ["battery", "PHS"]]].clip(upper=0).sum(axis=1) / 1e3
    load = n.loads_t.p_set.sum(axis=1) / 1e3
    for c_, (m, mlab) in enumerate([(4, "April (dry season, peak)"), (8, "August (wet season)")]):
        ax = axs[r_][c_]
        sel = gen.index.month == m
        hrs = gen.index[sel].hour
        G = gen[sel].groupby(hrs).mean()
        ax.stackplot(G.index, *[G[k] for k in ORDER], colors=[COL[k] for k in ORDER], linewidth=0)
        ax.fill_between(G.index, charge[sel].groupby(hrs).mean(), 0, color=COL["Battery"], alpha=0.6, linewidth=0)
        ax.plot(G.index, load[sel].groupby(hrs).mean(), color=INK, lw=1.6)
        ax.axhline(0, color=MUTED, lw=0.6)
        ax.set_title(f"{lab}, {mlab}", fontsize=9, loc="left", color=INK)
        ax.grid(axis="y", color="#e6e5e1", linewidth=0.6)
        ax.set_xticks(range(0, 24, 3))
for ax in axs[1]:
    ax.set_xlabel("Hour of day (local time, 3-h steps)")
for ax in axs[:, 0]:
    ax.set_ylabel("GW")
h = [plt.Rectangle((0, 0), 1, 1, color=COL[k]) for k in ORDER[::-1]] + [plt.Line2D([], [], color=INK, lw=1.6)]
fig.legend(h, ORDER[::-1] + ["Load"], loc="center right", frameon=False, fontsize=8)
fig.subplots_adjust(right=0.84, hspace=0.25, wspace=0.08)
fig.text(0.01, 0.0, "Mean over the sampled days of the month, 2035. Area below zero: battery and pumped-hydro charging.",
         fontsize=7.5, color=MUTED)
fig.savefig(FIG / "fig_diurnal.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# ---------------- 6. network model figure (PyPSA-ZA Fig. 1 analogue): nodal 2024 + 30-region model ----------------
g2 = gpd.read_file(DATA / "shapes" / "gadm41_VNM_2.json").to_crs(32648)
g1 = gpd.read_file(DATA / "shapes" / "gadm41_VNM_1.json").to_crs(4326)
cl = pd.read_csv(DATA / "expansion" / "clusters.csv", index_col=0)
cxy = gpd.GeoSeries(gpd.points_from_xy(cl.x, cl.y), crs=4326)
cx_ = cxy.to_crs(32648)
rp_ = g2.geometry.representative_point()
g2["cl"] = cl.index[np.argmin(np.hypot(rp_.x.values[:, None] - cx_.x.values[None], rp_.y.values[:, None] - cx_.y.values[None]), 1)]
REG = g2.dissolve("cl").to_crs(4326).reindex(cl.index)
_pw = gpd.sjoin(gpd.GeoDataFrame(geometry=cxy), g1[["NAME_1", "geometry"]], how="left", predicate="within")
_pw = _pw[~_pw.index.duplicated()]
_pn = gpd.sjoin_nearest(gpd.GeoDataFrame(geometry=cxy.to_crs(32648)), g1.to_crs(32648)[["NAME_1", "geometry"]])
_pn = _pn[~_pn.index.duplicated()]
cl["prov"] = _pw.NAME_1.fillna(_pn.NAME_1).values  # centroid's own province; nearest if offshore
nb = pypsa.Network(DATA / "networks" / "vn2024_base.nc")
fig, axs = plt.subplots(1, 2, figsize=(10, 8.6))
VC = {500: ("#2b0f54", 1.1), 220: ("#7b3294", 0.55), 110: ("#c2a5cf", 0.3)}
ax = axs[0]
vn.plot(ax=ax, color=LAND, edgecolor=BORDER, linewidth=0.4)
vb = nb.lines.bus0.map(nb.buses.v_nom)
for kv in [110, 220, 500]:
    li = nb.lines[vb == kv]
    xs_ = np.c_[li.bus0.map(nb.buses.x), li.bus1.map(nb.buses.x), np.full(len(li), np.nan)].ravel()
    ys_ = np.c_[li.bus0.map(nb.buses.y), li.bus1.map(nb.buses.y), np.full(len(li), np.nan)].ravel()
    ax.plot(xs_, ys_, color=VC[kv][0], lw=VC[kv][1], label=f"{kv} kV", zorder={110: 2, 220: 3, 500: 4}[kv])
b5 = nb.buses[nb.buses.v_nom == 500]
ax.scatter(b5.x, b5.y, s=4, color=VC[500][0], zorder=5)
ax.legend(loc="lower left", fontsize=8, title="Lines", title_fontsize=8, bbox_to_anchor=(0.0, 0.25))
ax.set_title(f"(a) Nodal model 2024: {len(nb.buses):,} buses, {len(nb.lines):,} lines", loc="left", fontsize=9.5)
ax = axs[1]
REG.plot(ax=ax, color=LAND, edgecolor=BORDER, linewidth=0.5)
for k_, r in cor.iterrows():
    a_, b_ = k_.split("|")
    if a_ in cl.index and b_ in cl.index:
        ax.plot([cl.x[a_], cl.x[b_]], [cl.y[a_], cl.y[b_]], color=LINE_EXP, lw=LWF * r.mw * 0.7 / 1e3, zorder=2,
                solid_capstyle="round")
ax.scatter(cl.x, cl.y, s=18, color=INK, zorder=3)
LBL = {"Lai Châu": (-4, 3, "right"), "Hòa Bình": (-4, -9, "right"), "Lâm Đồng": (4, -10, "left"),
       "Đắk Nông": (-4, 3, "right"), "Tây Ninh": (-4, 3, "right"), "BR-VT": (4, -9, "left"), "Hà Nội": (2, 5, "left"),
       "Kiên Giang": (-4, 3, "right")}
seen_ = set()
for c_, r in cl.iterrows():
    nm_ = r.prov.replace("ThừaThiênHuế", "Huế").replace("BàRịa-VũngTàu", "BR-VT").replace("HồChíMinh", "HCMC")
    nm_ = "".join((" " + ch) if (i_ > 0 and ch.isupper() and nm_[i_ - 1].islower()) else ch for i_, ch in enumerate(nm_))
    if nm_ in seen_:
        continue  # two regions in the same province: label once
    seen_.add(nm_)
    dx_, dy_, ha_ = LBL.get(nm_, (3, 2, "left"))
    ax.annotate(nm_, (r.x, r.y), xytext=(dx_, dy_), textcoords="offset points", fontsize=5.5, color=INK, zorder=4, ha=ha_)
for gw in [10, 5]:
    ax.plot([], [], color=LINE_EXP, lw=LWF * gw, label=f"{gw} GW")
ax.legend(loc="lower left", fontsize=8, title="2024 corridors (70% of rating)", title_fontsize=8, bbox_to_anchor=(0.0, 0.25))
ax.set_title(f"(b) Expansion model: {len(cl)} regions", loc="left", fontsize=9.5)
# full national territory incl. the Hoang Sa (Paracel) and Truong Sa (Spratly) archipelagos (GADM 4.1 XPI / XSP):
# Hoang Sa inside the main frame, Truong Sa in an inset frame, as on official Vietnamese maps
ISL = DATA / "shapes" / "islands"
hs = gpd.read_file(ISL / "gadm41_XPI_0.json").to_crs(4326)
ts = gpd.read_file(ISL / "gadm41_XSP_0.json").to_crs(4326)


def islands(ax_, gdf, label, xy_lab, inset=False):
    gdf.plot(ax=ax_, color="#bdbdb8", edgecolor="#8c8c88", linewidth=0.3)
    parts = gdf.explode(index_parts=False).representative_point()
    ax_.scatter(parts.x, parts.y, s=1.2, color="#6b6a66", zorder=3)
    ax_.text(*xy_lab, label, fontsize=6.5 if inset else 7, color=MUTED, ha="center", style="italic")


for ax in axs:
    ax.set_xlim(102, 113.8)
    ax.set_ylim(8.3, 23.6)
    ax.set_aspect("equal")
    ax.set_axis_off()
    islands(ax, hs, "Hoàng Sa\n(Paracel) Islands", (112.0, 17.35))
    ins = ax.inset_axes([0.70, 0.0, 0.30, 0.21])  # Truong Sa inset frame in the open sea east of the south coast
    islands(ins, ts, "Trường Sa\n(Spratly) Islands", (114.9, 11.85), inset=True)
    ins.set_xlim(112.4, 117.4)
    ins.set_ylim(8.9, 12.7)
    ins.set_xlabel("")
    ins.set_ylabel("")
    ins.set_aspect("equal")
    ins.set_xticks([])
    ins.set_yticks([])
    for sp in ins.spines.values():
        sp.set_visible(True)
        sp.set_color("#9a9994")
        sp.set_linewidth(0.6)
    ins.set_facecolor(SURF)
fig.subplots_adjust(wspace=0.02)
fig.savefig(FIG / "fig_network.png", dpi=220, bbox_inches="tight")
plt.close(fig)

# ---------------- 7. matrix of scenario results (PyPSA-ZA Fig. 2 analogue) ----------------
STK = pd.read_csv(GEN / "scenario_matrix_stacks.csv", index_col=0) if (GEN / "scenario_matrix_stacks.csv").exists() else None
SMX = pd.read_csv(GEN / "scenario_matrix.csv")
CSTK = {"Coal": PYPSA_COLORS["Coal"], "Gas": PYPSA_COLORS["Gas"], "Nuclear": PYPSA_COLORS["Nuclear"],
        "Onshore wind": PYPSA_COLORS["Onshore wind"], "Offshore wind": PYPSA_COLORS["Offshore wind"],
        "Solar PV": PYPSA_COLORS["Solar PV"], "Storage": PYPSA_COLORS["Battery"], "Other": PYPSA_COLORS["Imports & biomass"],
        "Transmission": PYPSA_COLORS["Transmission"]}
MAT = [("PDP8", "pdp8", "_vn", "PDP8 plan"), ("Least cost", "opt", "_vn", "Least cost"),
       ("CO$_2$ $-$50%", "opt", "_vn_co2half", "CO2 −50%")]
ymax = 0
if STK is not None:
    ymax = STK.sum(axis=1).max() * 1.05
for y, MATX, fname in [(2035, MAT, "fig_matrix_2035"), (2040, MAT, "fig_matrix_2040"), (2035, MAT[:2], "fig_maps_main")]:
    fig, axs = plt.subplots(1, len(MATX), figsize=(3.5 * len(MATX), 6.9))
    for c_, (lab, s_, t_, mlab) in enumerate(MATX):
        ax = axs[c_]
        fn = RES / f"{y}_{s_}{t_}.nc"
        ax.set_xlim(102, 110)
        ax.set_ylim(8.3, 23.6)
        ax.set_aspect("equal")
        ax.set_axis_off()
        if not fn.exists():
            continue
        n = pypsa.Network(fn)
        vn.plot(ax=ax, color=LAND, edgecolor=BORDER, linewidth=0.4)
        for i, r in n.links.iterrows():
            x0, y0, x1, y1 = n.buses.x[r.bus0], n.buses.y[r.bus0], n.buses.x[r.bus1], n.buses.y[r.bus1]
            tot = r.p_nom_opt if r.p_nom_extendable else r.p_nom
            if r.carrier == "DC":
                if tot > 100:
                    ax.plot([x0, x1], [y0, y1], color=LINE_DC, lw=LWF * tot / 1e3, ls=(0, (3, 2)), zorder=2)
                continue
            ex = min(cor.mw.get(f"{r.bus0}|{r.bus1}", 0.0) * 0.7, tot)
            if tot - ex > 100:
                ax.plot([x0, x1], [y0, y1], color=LINE_EXP, lw=LWF * tot / 1e3, zorder=2, solid_capstyle="butt")
            if ex > 50:
                ax.plot([x0, x1], [y0, y1], color=LINE_CUR, lw=LWF * ex / 1e3, zorder=3, solid_capstyle="butt")
        cap = pd.concat([n.generators.assign(c=n.generators.p_nom_opt).groupby(["bus", "carrier"]).c.sum(),
                         n.storage_units.assign(c=n.storage_units.p_nom_opt).groupby(["bus", "carrier"]).c.sum()])
        cap = cap.drop("load shedding", level=1, errors="ignore").unstack(fill_value=0)
        cap = cap.T.groupby(cap.columns.map(GRP)).sum().T.reindex(columns=ORDER, fill_value=0) / 1e3
        for b_, row in cap.iterrows():
            tot = row.sum()
            if tot < 0.5:
                continue
            rad, a0 = RADF * np.sqrt(tot), 90.0
            for g, v in row.items():
                if v > 0:
                    a1 = a0 + 360 * v / tot
                    ax.add_patch(Wedge((n.buses.x[b_], n.buses.y[b_]), rad, a0, a1, facecolor=COL[g], edgecolor=SURF,
                                       linewidth=0.3, zorder=4))
                    a0 = a1
        d = summ(y, s_, t_)
        e = pd.Series(d["energy_TWh"]).drop(["load shedding", "battery", "PHS"], errors="ignore")
        e = e.groupby(e.index.map(GRP)).sum().reindex(ORDER).fillna(0)
        e = e[e > 0.005 * e.sum()]
        ia = ax.inset_axes([-0.02, 0.38, 0.44, 0.21])
        ia.pie(e.values, colors=[COL[k] for k in e.index], startangle=90, counterclock=False,
               wedgeprops=dict(edgecolor=SURF, linewidth=0.5),
               labels=[f"{k}\n{100 * v / e.sum():.0f}%" if k in e.nlargest(3).index and v / e.sum() > 0.12 else ""
                       for k, v in e.items()], textprops=dict(fontsize=7.5, color=INK), labeldistance=1.2)
        ia.set_title("Energy", fontsize=8, color=MUTED, pad=1)
        if STK is not None and f"{y}|{mlab}" in STK.index:
            st = STK.loc[f"{y}|{mlab}"]
            ib = ax.inset_axes([0.07, 0.06, 0.12, 0.27])
            bb_ = 0.0
            for k in ["Coal", "Onshore wind", "Solar PV", "Storage", "Other", "Gas", "Offshore wind", "Nuclear", "Transmission"]:
                v = st.get(k, 0.0)
                if v > 0:
                    ib.bar(0, v, bottom=bb_, color=CSTK[k], width=0.8, edgecolor=SURF, linewidth=0.4,
                           hatch="xxx" if k == "Transmission" else None)
                    bb_ += v
            ib.set_ylim(0, ymax)
            ib.set_xticks([])
            ib.tick_params(labelsize=7, length=2)
            ib.set_ylabel("USD/MWh", fontsize=7, labelpad=1)
            for sp in ["top", "right"]:
                ib.spines[sp].set_visible(False)
            ib.patch.set_alpha(0)
        rr = SMX[(SMX.year == y) & (SMX.scenario == mlab)]
        if len(rr):
            rr = rr.iloc[0]
            txt = f"{rr.avg_cost_USD_MWh:.0f} USD/MWh\nCO$_2$: {rr.co2_Mt:.0f} Mt/a"
            if rr.unserved_pct >= 0.01:
                txt += f"\nunserved {rr.unserved_pct:.2f}%"
            ax.text(0.0, 0.69, txt, transform=ax.transAxes, va="top", fontsize=8.5, color=INK)
        ax.set_title(f"{lab}, {y}", fontsize=10, color=INK, loc="left")
    h = [plt.Rectangle((0, 0), 1, 1, color=COL[g]) for g in ORDER]
    h += [plt.Line2D([], [], color=LINE_CUR, lw=3), plt.Line2D([], [], color=LINE_EXP, lw=3),
          plt.Line2D([], [], color=LINE_DC, lw=2, ls=(0, (3, 2))), plt.Rectangle((0, 0), 1, 1, facecolor=CSTK["Transmission"], hatch="xxx", edgecolor=SURF)]
    fig.legend(h, ORDER + ["AC existing (2024)", "AC expanded", "HVDC", "New transmission (cost bar)"], loc="lower center",
               ncol=5 if len(MATX) == 3 else 4, fontsize=8, bbox_to_anchor=(0.5, -0.02))
    fig.subplots_adjust(wspace=0.0, bottom=0.12, top=0.97)
    fig.savefig(FIG / f"{fname}.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

PRM = {}
# ---------------- 8. merit order of dispatchable capacity (PyPSA-USA plot_generator_cost_stack style) ----------------
DISP = ["coal", "gas", "LNG", "OCGT", "oil", "nuclear", "biomass", "imports"]
fig, axs = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
for ax, (s_, lab) in zip(axs, [("pdp8", "PDP8 2035"), ("opt", "Least cost 2035")]):
    fn = RES / f"2035_{s_}_vn.nc"
    if not fn.exists():
        continue
    n = pypsa.Network(fn)
    g = n.generators[n.generators.carrier.isin(DISP)].copy()
    g["cap"] = g.p_nom_opt * n.get_switchable_as_dense("Generator", "p_max_pu")[g.index].mean() / 1e3
    g["mc"] = n.get_switchable_as_dense("Generator", "marginal_cost")[g.index].mean()
    g = g[g.cap > 0.01].sort_values("mc")
    x0 = np.cumsum(g.cap.values) - g.cap.values
    for xi, (_, r) in zip(x0, g.iterrows()):
        ax.bar(xi, r.mc, width=r.cap, align="edge", color=COL[GRP[r.carrier]], linewidth=0)
    disp = n.generators_t.p[g.index].sum(axis=1) / 1e3
    for v, ls, t, yt in [(disp.mean(), "--", "mean", 155), (disp.max(), "-", "max", 128)]:
        ax.axvline(v, color=INK, ls=ls, lw=1.1)
        ax.text(v, yt, f" {t} dispatch\n {v:.0f} GW", fontsize=7.5, color=INK, va="top",
                bbox=dict(facecolor=SURF, edgecolor="none", pad=0.5, alpha=0.85))
    ax.set_xlabel("Cumulative available capacity [GW]")
    ax.set_title(lab, loc="left", fontsize=10, color=INK)
    ax.grid(axis="y", color="#e6e5e1", linewidth=0.6)
    ax.set_axisbelow(True)
axs[0].set_ylabel("Marginal cost [USD/MWh]")
axs[0].set_ylim(0, 160)
used = [k for k in ORDER if k in {GRP[c] for c in DISP}]
fig.legend([plt.Rectangle((0, 0), 1, 1, color=COL[k]) for k in used], used, loc="center left", bbox_to_anchor=(0.86, 0.55),
           fontsize=8.5)
fig.subplots_adjust(right=0.85, wspace=0.06)
fig.text(0.01, -0.03, "Dispatchable fleet sorted by marginal cost (capacity x availability). Vertical lines: mean and maximum "
         "combined dispatch of these plants over the year.", fontsize=7.5, color=MUTED)
fig.savefig(FIG / "fig_merit.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# ---------------- 9. load-weighted mean marginal price per region (PyPSA-Eur plot_balance_map style) ----------------
PR = {}
for y in [2035, 2040]:
    for s_ in ["pdp8", "opt"]:
        fn = RES / f"{y}_{s_}_vn.nc"
        if fn.exists():
            n = pypsa.Network(fn)
            w = n.snapshot_weightings.generators
            ld = n.loads_t.p_set.T.groupby(n.loads.bus).sum().T.reindex(columns=n.buses.index, fill_value=0)
            lmp = n.buses_t.marginal_price.reindex(columns=n.buses.index).clip(upper=500)  # cap scarcity spikes for display
            PR[(y, s_)] = (lmp * ld).mul(w, axis=0).sum() / ld.mul(w, axis=0).sum()
if PR:
    # show each region's deviation from the panel's national load-weighted mean (diverging, common
    # symmetric scale), so that regional spreads are visible in every panel; the national mean is printed per panel
    NM = {}
    for (y, s_), v in PR.items():
        n_ = pypsa.Network(RES / f"{y}_{s_}_vn.nc")
        ldw = n_.loads_t.p_set.T.groupby(n_.loads.bus).sum().T.reindex(columns=n_.buses.index, fill_value=0) \
            .mul(n_.snapshot_weightings.generators, axis=0).sum()
        NM[(y, s_)] = float((v * ldw).sum() / ldw.sum())
    dev = {k: v - NM[k] for k, v in PR.items()}
    lim = max(2.0, np.ceil(max(abs(d_).max() for d_ in dev.values())))
    norm = matplotlib.colors.TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)
    fig, axs = plt.subplots(1, 4, figsize=(11.5, 6.2))
    for ax, ((y, s_), v) in zip(axs, sorted(dev.items(), key=lambda kv: (kv[0][0], kv[0][1] != "pdp8"))):
        REG.assign(p=v.reindex(REG.index).values).plot(column="p", ax=ax, cmap="RdBu_r", norm=norm, edgecolor="white",
                                                         linewidth=0.4)
        ax.set_title(f"{'PDP8' if s_ == 'pdp8' else 'Least cost'} {y}\nnational mean {NM[(y, s_)]:.0f} USD/MWh",
                     loc="left", fontsize=9.5, color=INK)
        ax.set_xlim(102, 110)
        ax.set_ylim(8.3, 23.6)
        ax.set_aspect("equal")
        ax.set_axis_off()
    sm = plt.cm.ScalarMappable(cmap="RdBu_r", norm=norm)
    cb = fig.colorbar(sm, ax=axs, shrink=0.6, pad=0.01)
    cb.set_label("Regional price minus national mean [USD/MWh]")
    for (y, s_), v in NM.items():
        PRM[f"lmpmean_{'pdp' if s_ == 'pdp8' else 'lc'}{y}"] = v
    fig.savefig(FIG / "fig_prices.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    for (y, s_), v in PR.items():
        k = "pdp" if s_ == "pdp8" else "lc"
        put_later = (f"lmpmin_{k}{y}", v.min()), (f"lmpmax_{k}{y}", v.max())
        for kk, vv in put_later:
            PRM[kk] = vv

# ---------------- 5. number macros ----------------
M = {}


def put(k, v, d=1):
    if isinstance(v, (int, float, np.floating)) and not pd.isna(v) and round(v, d) == 0:
        v = 0.0  # avoid "-0"
    M[k] = f"{v:,.{d}f}" if isinstance(v, (int, float, np.floating)) and not pd.isna(v) else str(v)


for (y_, s_), v_ in globals().get("NM", {}).items():  # national mean prices (fig_prices)
    put(f"natprice_{'pdp' if s_ == 'pdp8' else 'lc'}{y_}", v_, 0)
SM = pd.read_csv(GEN / "scenario_matrix.csv")
SL = {"PDP8 plan": "pdp", "PDP8, LNG take-or-pay": "pdpqc", "Least cost": "lc", "CO2 −50%": "half",
      "Zero CO2": "zero", "Zero CO2, no build cap": "zeronl", "PDP8 + DC": "pdpdc", "Least cost + DC": "lcdc",
      "PDP8 + HSR": "pdphsr", "Least cost + HSR": "lchsr", "PDP8 + DC + HSR": "pdpdchsr", "Least cost + DC + HSR": "lcdchsr",
      "PDP8, emission ceiling": "pdpceil", "Least cost, emission ceiling": "lcceil", "Least cost, plan range": "lcrange",
      "PDP8, high variant": "pdphigh", "Least cost, high demand": "lchigh", "Plan range, plan lines": "prgridm"}
for _, r in SM.iterrows():
    k = f"{SL.get(r.scenario, r.scenario)}{r.year}"
    put(f"cost_{k}", r.total_bnUSD_yr)
    put(f"avg_{k}", r.avg_cost_USD_MWh, 0)
    put(f"co2_{k}", r.co2_Mt, 0)
    put(f"inv_{k}", r.overnight_bnUSD, 0)
    put(f"invgrid_{k}", r.overnight_grid_bnUSD, 0)
    put(f"unserved_{k}", r.unserved_pct, 2)
    put(f"unserved1_{k}", r.unserved_pct, 1)
    put(f"shadow_{k}", r.co2_shadow_USD_t, 0)
    put(f"dem_{k}", r.demand_TWh, 0)
    for c in ["solar", "onwind", "offwind", "battery", "PHS", "LNG", "OCGT", "nuclear", "coal", "gas", "hydro"]:
        put(f"{c}_{k}", r[f"{c}_GW"], 1 if (r[f"{c}_GW"] < 10 or c == "LNG") else 0)
for y in [2035, 2040]:
    a = SM[(SM.year == y) & (SM.scenario == "PDP8 plan")].iloc[0]
    b = SM[(SM.year == y) & (SM.scenario == "Least cost")].iloc[0]
    put(f"save_{y}", a.total_bnUSD_yr - b.total_bnUSD_yr)
    put(f"savepct_{y}", 100 * (1 - b.total_bnUSD_yr / a.total_bnUSD_yr), 0)
    put(f"saveinv_{y}", a.overnight_bnUSD - b.overnight_bnUSD, 0)
    # saving per MWh of demand and relative to the average retail tariff (2,204 VND/kWh from May 2025,
    # Decision 1279/QD-BCT; 25,500 VND/USD -> 86.4 USD/MWh)
    usd_ = 1e3 * (a.total_bnUSD_yr - b.total_bnUSD_yr) / a.demand_TWh
    put(f"saveusd_{y}", usd_, 0)
    put(f"savetariff_{y}", 100 * usd_ / 86.4, 0)
    h_ = SM[(SM.year == y) & (SM.scenario == "CO2 −50%")]
    if len(h_):
        put(f"halfdelta_{y}", h_.total_bnUSD_yr.iloc[0] - b.total_bnUSD_yr)
    z_ = SM[(SM.year == y) & (SM.scenario == "Zero CO2, no build cap")]
    if len(z_):
        put(f"lcpremium_zero_{y}", 100 * (z_.total_bnUSD_yr.iloc[0] / b.total_bnUSD_yr - 1), 0)
    for s, t, k in [("pdp8", "_vn", "pdp"), ("opt", "_vn", "lc"), ("pdp8", "_vn_lngqc", "pdpqc")]:
        d = summ(y, s, t)
        if d:
            put(f"twkm_{k}{y}", d["transmission_added"]["AC_interregion_TWkm"])
            put(f"hvdc_{k}{y}", d["transmission_added"].get("HVDC_GW", 0), 0)
            e, c = d["energy_TWh"], d["capacity_GW"]
            for t_ in ["LNG", "coal", "imports", "gas"]:
                if c.get(t_, 0) > 0:
                    put(f"cf{t_}_{k}{y}", e.get(t_, 0) / (c[t_] * 8.76), 2)
            put(f"vreshare_{k}{y}", 100 * sum(e.get(t_, 0) for t_ in ["solar", "rooftop", "onwind", "offwind"])
                / sum(v for k_, v in e.items() if k_ not in ["battery", "PHS", "load shedding"]), 0)
            put(f"firm_{k}{y}", d.get("firm_capacity_GW", 0), 0)
            put(f"pmax_{k}{y}", d.get("pmax_GW", 0), 0)
            put(f"demand_{k}{y}", d.get("demand_TWh", 0), 0)
            put(f"reserve_{k}{y}", d.get("reserve_requirement_GW", 0), 0)
SE = pd.read_csv(GEN / "sensitivity.csv")
sv = SE.dropna(subset=["saving_pct"])
# the high-demand variant and the emission ceiling are scenarios, not sensitivities
SCEN_VAR = ["High-demand plan variant", "Plan emission ceiling"]
sv_ = sv[(sv.year == 2035) & ~sv.case.isin(SCEN_VAR + ["Base"])]
put("sens_min", sv_.saving_pct.min(), 0)
put("sens_max", sv_.saving_pct.max(), 0)
put("sens_minabs", sv_.saving_bnUSD.min())
put("sens_maxabs", sv_.saving_bnUSD.max())
put("sens_n", len(sv_), 0)
CK = {"Base": "base", "LNG 12 USD/MMBtu": "lng", "Dry year (hydro 80 TWh)": "dry", "Battery credit 0.5": "bat",
      "Reserve margin 15 %": "rm115", "Reserve margin 20 %": "rm120", "No operating reserve / SNSP limit": "nores",
      "PV and wind connection +100 USD/kW": "conn", "Corridor limits 50 % of thermal rating": "corr",
      "Discount rate 10 %": "wacc", "Battery cost +50 %": "bat150", "Offshore wind cost -30 %": "off70",
      "Nuclear cost +50 %": "nuc150", "Pumped hydro cost +50 %": "phs150", "PV build rate 5.5 GW/a": "pv55",
      "Battery build rate 3 GW/a": "batbuild", "High-demand plan variant": "high", "Plan emission ceiling": "co2plan",
      "Static capacity credits": "static", "AC line cost x2 (circuit-3 benchmark)": "line2",
      "Committed LNG: Nhon Trach 3&4 only": "commit25", "Hydro within monthly inflow budgets": "hydmon",
      "Hydro without monthly budgets": "hydfree"}
for _, r in sv.iterrows():
    k = CK.get(r.case, "x")
    put(f"sens_{k}{r.year}", r.saving_pct, 0)
    put(f"senslc_{k}{r.year}", r.opt_bnUSD)
    put(f"senspdp_{k}{r.year}", r.pdp8_bnUSD)
    put(f"sensabs_{k}{r.year}", r.saving_bnUSD)
    put(f"sensbat_{k}{r.year}", r.opt_battery_GW, 0)
    put(f"sensgas_{k}{r.year}", r.opt_gas_new_GW, 0)
EX = pd.read_csv(GEN / "extra_load_summary.csv")
XK = {"Data centres": "dc", "High-speed rail": "hsr", "DC + HSR": "both"}
for _, r in EX.iterrows():
    k = f"{XK.get(r.case, r.case[:3].lower())}{'pdp' if 'PDP8' in r.run else 'lc'}{r.year}"
    put(f"xTWh_{k}", r.extra_TWh, 1)
    put(f"xGW_{k}", r.extra_peak_MW / 1e3, 1)
    put(f"xcost_{k}", r.d_cost_bnUSD_yr, 2)
    put(f"xusd_{k}", r.d_cost_USD_per_MWh_new_load, 0)
    put(f"xrm_{k}", r.reserve_margin_pct, 0)
    put(f"xlmp_{k}", r.d_LMP_DC_sites, 0)
    for col_, kk in [("Nuclear", "nuc"), ("Gas", "gas"), ("Onshore wind", "onw"), ("Solar PV", "pv"), ("Battery", "bat")]:
        if f"d_{col_}_GW" in r and not pd.isna(r[f"d_{col_}_GW"]):
            put(f"xd{kk}_{k}", r[f"d_{col_}_GW"], 1)  # least-cost capacity change caused by the extra load
U = pd.read_csv(GEN / "pdp8_unused_additions_summary.csv") if (GEN / "pdp8_unused_additions_summary.csv").exists() else None
if U is not None and len(U):
    for _, r in U.iterrows():
        y = str(r.case)[:4]
        if y.isdigit() and len(str(r.case).split()) <= 2:
            put(f"acadd_{y}", r["AC added GW"], 0)
            put(f"acunused_{y}", r["never used GW"], 0)
            put(f"acunusedpct_{y}", 100 * r["never used GW"] / r["AC added GW"], 0)
            put(f"acunusedbn_{y}", r["never used bn USD"], 1)
VA = pd.read_csv(VAL / "validation_2024_annual.csv", index_col=0)
for c, k in [("coal", "coal"), ("gas", "gas"), ("hydro", "hydro"), ("onwind", "wind"), ("solar+rooftop", "solar"),
             ("other", "other")]:
    if c in VA.index:
        put(f"val_{k}_model", VA.loc[c, "model_TWh"], 1)
        put(f"val_{k}_ember", VA.loc[c, "ember_TWh"], 1)
        put(f"val_{k}_diff", VA.loc[c, "diff_pct"], 1)
        put(f"val_{k}_absdiff", abs(VA.loc[c, "diff_pct"]), 1)
        put(f"val_{k}_corr", VA.loc[c, "monthly_corr"], 2)
VM = pd.read_csv(VAL / "validation_2024_monthly.csv", index_col=0, header=[0, 1])
put("val_shed_TWh", VM["shed_TWh"].sum().sum() if "shed_TWh" in VM.columns.get_level_values(0) else 0, 2)
th_m = VA.loc[["coal", "gas"], "model_TWh"].sum()
th_e = VA.loc[["coal", "gas"], "ember_TWh"].sum()
put("val_thermal_model", th_m, 1)
put("val_thermal_ember", th_e, 1)
put("val_thermal_diff", 100 * (th_m / th_e - 1), 1)
put("val_thermal_absdiff", abs(100 * (th_m / th_e - 1)), 1)
put("res_dir", RES.name)
for y in [2035, 2040]:
    for s_, t_, k in [("pdp8", "_vn", "pdp"), ("opt", "_vn", "lc")]:
        d = summ(y, s_, t_)
        if d and "indicators" in d:
            ind = d["indicators"]
            put(f"rm_{k}{y}", ind["reserve_margin_pct"], 0)
            put(f"curt_{k}{y}", ind["curtailment_pct"], 1)
            put(f"stor_{k}{y}", ind["storage_energy_GWh"], 0)
            put(f"su_{k}{y}", ind["startup_cost_bnUSD"], 2)
            put(f"imp_{k}{y}", d["energy_TWh"].get("imports", 0), 0)
            put(f"shedpct_{k}{y}", 100 * d["load_shedding_TWh"] / d["demand_TWh"], 2)
    # investment difference computed from the rounded values shown in the table
    a_ = SM[(SM.year == y) & (SM.scenario == "PDP8 plan")].iloc[0]
    b_ = SM[(SM.year == y) & (SM.scenario == "Least cost")].iloc[0]
    put(f"saveinv_{y}", round(a_.overnight_bnUSD) - round(b_.overnight_bnUSD), 0)
# provisional fallbacks for older result sets (v2) without the v4 indicators: computed from summaries/networks
PROVISIONAL = []
for y in [2035, 2040]:
    for s_, t_, k in [("pdp8", "_vn", "pdp"), ("opt", "_vn", "lc")]:
        d = summ(y, s_, t_)
        if d and "indicators" not in d:
            PROVISIONAL.append(f"{k}{y}")
            put(f"rm_{k}{y}", 100 * d["firm_capacity_GW"] / (d["reserve_requirement_GW"] / 1.1), 0)
            put(f"imp_{k}{y}", d["energy_TWh"].get("imports", 0), 0)
            put(f"shedpct_{k}{y}", 100 * d["load_shedding_TWh"] / d["demand_TWh"], 2)
            n = pypsa.Network(RES / f"{y}_{s_}{t_}.nc")
            w_ = n.snapshot_weightings.generators
            capg_ = n.generators.p_nom_opt.where(n.generators.p_nom_extendable, n.generators.p_nom)
            vre_ = n.generators.index[n.generators.carrier.isin(["solar", "rooftop", "onwind", "offwind"])]
            av_ = (n.generators_t.p_max_pu.reindex(columns=vre_).fillna(1.0) * capg_[vre_]).mul(w_, axis=0).sum().sum()
            dp_ = n.generators_t.p[vre_].mul(w_, axis=0).sum().sum()
            put(f"curt_{k}{y}", 100 * (av_ - dp_) / av_, 1)
            su_ = n.storage_units
            sc_ = su_.p_nom_opt.where(su_.p_nom_extendable, su_.p_nom)
            put(f"stor_{k}{y}", float((sc_ * su_.max_hours)[su_.carrier.isin(["battery", "PHS"])].sum() / 1e3), 0)
# cost decomposition (cumulative release of PDP8 groups, 2035)
dec = {"pdp": summ(2035, "pdp8", "_vn"), "lc": summ(2035, "opt", "_vn")}
for i_ in range(1, 5):
    dec[f"rel{i_}"] = summ(2035, "pdp8", f"_vn_rel{i_}")
if all(dec.values()):
    cost = {k: round(v["cost_bnUSD_per_year"]["total_excl_VOLL"], 2) for k, v in dec.items()}
    steps = [("lng", "pdp", "rel1"), ("off", "rel1", "rel2"), ("nuc", "rel2", "rel3"), ("ac", "rel3", "rel4"), ("rest", "rel4", "lc")]
    gap = cost["pdp"] - cost["lc"]
    for k, a_, b_ in steps:
        put(f"dec_{k}", cost[a_] - cost[b_], 2)
        put(f"decpct_{k}", 100 * (cost[a_] - cost[b_]) / gap, 0)
    for k, v in cost.items():
        put(f"deccost_{k}", v, 1)
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    lab_ = {"lng": "LNG", "off": "Offshore\nwind", "nuc": "Nuclear", "ac": "Transmission", "rest": "Remaining\n(siting, mix)"}
    col_ = {"lng": PYPSA_COLORS["Gas"], "off": PYPSA_COLORS["Offshore wind"], "nuc": PYPSA_COLORS["Nuclear"],
            "ac": PYPSA_COLORS["Transmission"], "rest": "#9a9994"}
    x_, level = 0, cost["pdp"]
    ax.bar(x_, level, color="#545454", width=0.6)
    ax.text(x_, level + 0.3, f"{level:.1f}", ha="center", fontsize=8)
    xt = ["PDP8"]
    for k, a_, b_ in steps:
        x_ += 1
        dlt = cost[a_] - cost[b_]
        ax.bar(x_, -dlt, bottom=level, color=col_[k], width=0.6)
        ax.text(x_, level + 0.3, f"$-${dlt:.1f}", ha="center", fontsize=8)
        level -= dlt
        xt.append(lab_[k])
    x_ += 1
    ax.bar(x_, cost["lc"], color="#1f1e1c", width=0.6)
    ax.text(x_, cost["lc"] + 0.3, f"{cost['lc']:.1f}", ha="center", fontsize=8)
    xt.append("Least\ncost")
    ax.set_xticks(range(len(xt)), xt, fontsize=8)
    ax.set_ylabel("System cost 2035 [bn USD/a]")
    ax.set_ylim(min(cost.values()) * 0.85, cost["pdp"] * 1.05)
    ax.grid(axis="y", color="#e6e5e1", linewidth=0.6)
    ax.set_axisbelow(True)
    fig.savefig(FIG / "fig_decomposition.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
if "dec_lng" not in M and (GEN / "scenario_matrix_stacks.csv").exists():
    st_ = pd.read_csv(GEN / "scenario_matrix_stacks.csv", index_col=0)
    if "2035|PDP8 plan" in st_.index and "2035|Least cost" in st_.index:
        dem_ = float(SM[(SM.year == 2035) & (SM.scenario == "PDP8 plan")].demand_TWh.iloc[0])
        dd = (st_.loc["2035|PDP8 plan"] - st_.loc["2035|Least cost"]) * dem_ / 1e3  # bn USD/a
        grp_ = {"lng": ["Gas"], "off": ["Offshore wind"], "nuc": ["Nuclear"], "ac": ["Transmission"]}
        gap_ = float(dd.sum())
        rest_ = gap_
        for k, cols in grp_.items():
            v = float(dd.reindex(cols).fillna(0).sum())
            rest_ -= v
            put(f"dec_{k}", v, 2)
            put(f"decpct_{k}", 100 * v / gap_, 0)
        put("dec_rest", rest_, 2)
        put("decpct_rest", 100 * rest_ / gap_, 0)
        PROVISIONAL.append("decomposition (cost-stack accounting)")
for t_, k in [("_vn_wacc10", "wacc"), ("_vn_bat150", "bat150"), ("_vn_off70", "off70"), ("_vn_pv55", "pv55")]:
    a_, b_ = summ(2035, "pdp8", t_), summ(2035, "opt", t_)
    if a_ and b_:
        ca, cb = a_["cost_bnUSD_per_year"]["total_excl_VOLL"], b_["cost_bnUSD_per_year"]["total_excl_VOLL"]
        put(f"sens_{k}2035", 100 * (1 - cb / ca), 0)
        put(f"sensabs_{k}2035", ca - cb, 1)
cc = pd.read_csv(CODE.parent / "repo_data" / "costs" / "costs_2035.csv", index_col=0)
put("lng_fuelcost", cc.loc["CCGT", "fuel_usd_mwhth"] / cc.loc["CCGT", "eff"] + cc.loc["CCGT", "vom_usd_mwh"], 0)
put("coal_fuelcost", cc.loc["coal_existing", "fuel_usd_mwhth"] / cc.loc["coal_existing", "eff"] + cc.loc["coal_existing", "vom_usd_mwh"], 0)
# coal +50 % compared with domestic gas and LNG; domestic gas and import prices
put("coalshock_cost", 1.5 * cc.loc["coal_existing", "fuel_usd_mwhth"] / cc.loc["coal_existing", "eff"] + cc.loc["coal_existing", "vom_usd_mwh"], 0)
put("gasdom_cost", cc.loc["gas_domestic", "fuel_usd_mwhth"] / cc.loc["gas_domestic", "eff"] + cc.loc["gas_domestic", "vom_usd_mwh"], 0)
put("gasdom_mmbtu", cc.loc["gas_domestic", "fuel_usd_mwhth"] / 3.412 / 1.108, 1)  # USD/MWh_th LHV -> USD/MMBtu HHV
put("import_price", cc.loc["imports", "vom_usd_mwh"], 0)
fn = RES / "2035_opt_vn.nc"
if fn.exists():
    n = pypsa.Network(fn)
    vre = n.generators.index[n.generators.carrier.isin(["solar", "rooftop", "onwind", "offwind"])]
    net = n.loads_t.p_set.sum(axis=1) - n.generators_t.p[vre].sum(axis=1)
    put("netpeak_hour", int(net.groupby(net.index.hour).mean().idxmax()), 0)
    put("loadpeak_hour", int(n.loads_t.p_set.sum(axis=1).groupby(n.snapshots.hour).mean().idxmax()), 0)
for kk, vv in PRM.items():
    put(kk, vv, 0)
# ---------------- 10. v5: Shapley decomposition, adequacy, regret, MGA, robustness, credits ----------------
GK = {"lng": "lng", "offwind": "off", "nuclear": "nuc", "ac": "ac", "rest": "rest"}
if (GEN / "shapley_2035.csv").exists():
    SH = pd.read_csv(GEN / "shapley_2035.csv")
    for _, r in SH.iterrows():
        k = GK[r.group]
        put(f"dec_{k}", r.shapley_bnUSD, 2)
        put(f"decpct_{k}", r.share_pct, 0)
        put(f"decmin_{k}", r.min_marginal_bnUSD, 1)
        put(f"decmax_{k}", r.max_marginal_bnUSD, 1)
        put(f"decalone_{k}", r.alone_bnUSD, 1)
        put(f"declast_{k}", r.last_bnUSD, 1)
    put("decgap", float(SH.gap_bnUSD.iloc[0]), 1)
    SH = SH.set_index("group").reindex(list(GK))
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    lab_ = {"lng": "LNG fleet", "offwind": "Offshore wind", "nuclear": "Nuclear", "ac": "Inter-regional\ntransmission",
            "rest": "Other technologies\n(PV, wind, storage, OCGT)"}
    col_ = {"lng": PYPSA_COLORS["Gas"], "offwind": PYPSA_COLORS["Offshore wind"], "nuclear": PYPSA_COLORS["Nuclear"],
            "ac": PYPSA_COLORS["Transmission"], "rest": "#9a9994"}
    y_ = np.arange(len(SH))[::-1]
    ax.barh(y_, SH.shapley_bnUSD, color=[col_[g] for g in SH.index], height=0.55)
    ax.errorbar(SH.shapley_bnUSD, y_, xerr=[SH.shapley_bnUSD - SH.min_marginal_bnUSD, SH.max_marginal_bnUSD - SH.shapley_bnUSD],
                fmt="none", ecolor=INK, elinewidth=0.8, capsize=3)
    for yy, v_, pc in zip(y_, SH.shapley_bnUSD, SH.share_pct):
        ax.text(max(v_, 0) + 0.15, yy + 0.3, f"{v_:.1f} ({pc:.0f}%)", fontsize=8, color=INK, va="center")
    ax.set_yticks(y_, [lab_[g] for g in SH.index], fontsize=8)
    ax.axvline(0, color=MUTED, lw=0.6)
    ax.set_xlabel("Saving from releasing the group to optimisation, 2035 [bn USD/a]")
    ax.grid(axis="x", color="#e6e5e1", linewidth=0.6)
    ax.set_axisbelow(True)
    fig.text(0.01, -0.06, f"Bars: Shapley values (sum = {SH.gap_bnUSD.iloc[0]:.1f} bn USD/a, the full gap). Whiskers: range of "
             "the group's marginal saving over all 120 release orders.", fontsize=7.5, color=MUTED)
    fig.savefig(FIG / "fig_decomposition.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    PROVISIONAL[:] = [x for x in PROVISIONAL if "decomposition" not in x]
if (GEN / "bounds.csv").exists():  # v6 first/last release bounds
    for _, r in pd.read_csv(GEN / "bounds.csv").iterrows():
        k = ("b40_" if r.case == "2040" else "bceil_") + GK[r.group]
        put(f"{k}_first", r.first_bnUSD, 1)
        put(f"{k}_last", r.last_bnUSD, 1)
        put(("b40" if r.case == "2040" else "bceil") + "_gap", r.gap_bnUSD, 1)
for y in [2035, 2040]:
    for t_, k_ in [("_vn", "pdp"), ("_vn_high", "pdphigh"), ("_vn_co2plan", "pdpceil")]:
        d_ = summ(y, "pdp8", t_)
        if d_ and "ocgt_topup_GW" in d_:
            put(f"topup_{k_}{y}", d_["ocgt_topup_GW"], 1)
if (GEN / "decomposition_seq_2040.csv").exists():
    for _, r in pd.read_csv(GEN / "decomposition_seq_2040.csv").iterrows():
        put(f"dec40_{GK[r.group]}", r.saving_bnUSD, 1)
        put(f"dec40pct_{GK[r.group]}", r.share_pct, 0)
if (GEN / "adequacy.csv").exists():
    AD = pd.read_csv(GEN / "adequacy.csv")
    for pf, k in [("PDP8", "pdp"), ("Least cost", "lc")]:
        for hyd, hk in [("normal", "n"), ("dry", "d")]:
            a_ = AD[(AD.portfolio == pf) & (AD.hydro == hyd)]
            if len(a_):
                put(f"eue_{k}{hk}_mean", a_.eue_ppm.mean(), 2)
                put(f"eue_{k}{hk}_max", a_.eue_ppm.max(), 2)
                put(f"lole_{k}{hk}_mean", a_.lole_h.mean(), 1)
                put(f"lole_{k}{hk}_max", a_.lole_h.max(), 0)
                put(f"adcost_{k}{hk}_mean", a_.cost_bnUSD.mean(), 1)
                put("nyears_ad", a_.weather_year.nunique(), 0)
    for pf, k in [("PDP8", "pdp"), ("Least cost", "lc")]:
        put(f"eue_{k}_max", AD[AD.portfolio == pf].eue_ppm.max(), 2)
    fig, axs = plt.subplots(1, 2, figsize=(7.5, 3.0), sharey=True)
    for ax, hyd, tt in zip(axs, ["normal", "dry"], ["Normal hydrology (100 TWh)", "Dry year (80 TWh)"]):
        for pf, c_, dx in [("PDP8", "#545454", -0.18), ("Least cost", PYPSA_COLORS["Solar PV"], 0.18)]:
            a_ = AD[(AD.portfolio == pf) & (AD.hydro == hyd)].sort_values("weather_year")
            ax.bar(a_.weather_year + dx, a_.eue_ppm, width=0.36, color=c_, label=pf)
        ax.set_title(tt, fontsize=9, loc="left")
        ax.set_xticks(range(2015, 2025), [str(y)[2:] for y in range(2015, 2025)], fontsize=7.5)
        ax.set_xlabel("Weather year (20xx)")
        ax.grid(axis="y", color="#e6e5e1", linewidth=0.6)
        ax.set_axisbelow(True)
    axs[0].set_ylabel("Unserved energy [ppm of demand]")
    axs[1].legend(fontsize=8, loc="upper right")
    fig.savefig(FIG / "fig_adequacy.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
RG = pd.read_csv(GEN / "regret.csv") if (GEN / "regret.csv").exists() else pd.DataFrame()
PK = ["pdp8", "lc", "lcrange", "lcceil", "prgrid"]
if not (len(RG) and all(f"{k}_cost" in RG for k in PK) and RG[[f"{k}_cost" for k in PK]].notna().all().all()):
    (SUMMARY / "tab_regret_rows.tex").write_text("\\textcolor{gray}{[pending]} & & & & & & \\\\\n")
if len(RG) and all(f"{k}_cost" in RG for k in PK) and RG[[f"{k}_cost" for k in PK]].notna().all().all():
    RGL = {"ref": "Reference (2024 weather)", "dem": "Demand +11\\,\\%", "lng": "LNG 25\\,USD/MMBtu",
           "dry": "Dry year (80\\,TWh hydro)", "pv": "Half of the new PV built", "coal": "Coal price +50\\,\\%",
           "bat": "Half of the batteries delivered", "north": "Corridors into the North at 50\\,\\%",
           "weak": "Weak-wind year 2022, dry hydro"}
    rows_ = []
    for _, r in RG.iterrows():
        cs = [r[f"{k}_cost"] for k in PK]
        mn = min(cs)
        cells = [(f"\\textbf{{{c:.1f}}}" if abs(c - mn) < 0.05 else f"{c:.1f}") for c in cs]
        eue = max(r[f"{k}_eue"] for k in PK)
        rows_.append(f"{RGL[r.key]} & " + " & ".join(cells) + f" & {eue:.2f} \\\\")
        put(f"regdiff_{r.key}", r.pdp8_cost - r.lc_cost, 1)
        for k in PK:
            put(f"regcost_{k}_{r.key}", r[f"{k}_cost"], 1)
    mxr = {k: RG[f"{k}_regret"].max() for k in PK}
    rows_.append("\\midrule Maximum regret & " + " & ".join(f"{mxr[k]:.1f}" for k in PK) + " & \\\\")
    for k in PK:
        put(f"regmax_{k}", mxr[k], 1)
    (SUMMARY / "tab_regret_rows.tex").write_text("\n".join(rows_) + "\n")
MG = pd.read_csv(GEN / "mga.csv") if (GEN / "mga.csv").exists() else pd.DataFrame()
if len(MG):
    ML = {"offwind": "Offshore wind [GW]", "lng": "LNG-fired CCGT [GW]", "nuclear": "Nuclear [GW]",
          "ac": "Inter-regional AC [TW\\,km]"}
    fmt_ = lambda r, c: f"{r[c]:.1f}" if c in r and not pd.isna(r[c]) else "--"  # noqa: E731
    (SUMMARY / "tab_mga_rows.tex").write_text("\n".join(
        f"{ML[r.group]} & {r.least_cost:.1f} & {fmt_(r, 'max_2pct')} & {fmt_(r, 'max_5pct')} & {fmt_(r, 'max_10pct')} & "
        f"{r.pdp8:.1f} \\\\" for _, r in MG.iterrows()) + "\n")
    for _, r in MG.iterrows():
        for et in ["2", "5", "10"]:
            if f"max_{et}pct" in r and not pd.isna(r[f"max_{et}pct"]):
                put(f"mga{et}_{r.group}", r[f"max_{et}pct"], 1)
        put(f"mga_{r.group}", r.get("max_5pct", float("nan")), 1)
        put(f"mgalc_{r.group}", r.least_cost, 1)
        put(f"mgapdp_{r.group}", r.pdp8, 1)
if (GEN / "robust.csv").exists():
    RBK = {"Central": "cen", "Pathway from 2035": "path", "Every 2nd day": "ds2", "Crossover": "xo",
           "Plan ranges with the plan's lines": "prgrid", "Plan storage with optimised siting": "storsite",
           "Least cost within plan ranges": "range", "Plan emission ceiling": "ceil", "High-demand plan variant": "high",
           "Static capacity credits": "static"}
    RB = pd.read_csv(GEN / "robust.csv")
    for _, r in RB.iterrows():
        k = f"{RBK[r.case]}{r.year}"
        cen_ = RB[(RB.case == "Central") & (RB.year == r.year)]
        if len(cen_):
            put(f"rbdir_{k}", r.lc_bnUSD - cen_.lc_bnUSD.iloc[0], 1)  # cost above the unconstrained least-cost system
        put(f"rbpdp_{k}", r.pdp8_bnUSD, 1)
        put(f"rblc_{k}", r.lc_bnUSD, 1)
        put(f"rbsave_{k}", r.saving_bnUSD, 1)
        put(f"rbpct_{k}", r.saving_pct, 0)
        put(f"rbco2pdp_{k}", r.pdp8_co2, 0)
        put(f"rbco2lc_{k}", r.lc_co2, 0)
        for c_ in ["solar", "battery", "ocgt", "lng", "nuclear", "offwind", "onwind", "phs"]:
            put(f"rb{c_}_{k}", r[f"lc_{c_}"], 1 if r[f"lc_{c_}"] < 10 else 0)
if (GEN / "credits.csv").exists():
    for _, r in pd.read_csv(GEN / "credits.csv").iterrows():
        k = f"{'pdp' if r.system == 'PDP8' else 'lc'}{r.year}"
        for c_ in ["battery", "PHS", "hydro", "imports", "onwind"]:
            if f"credit_{c_}" in r and not pd.isna(r[f"credit_{c_}"]):
                put(f"icr{c_}_{k}", r[f"credit_{c_}"], 2)
        put(f"snsp_{k}", r.snsp_max_pct, 0)
if (GEN / "mc.csv").exists():  # Monte Carlo (Latin hypercube) global sensitivity
    MCd = pd.read_csv(GEN / "mc.csv")
    put("mc_n", len(MCd), 0)
    put("mc_min", MCd.saving_pct.min(), 0)
    put("mc_max", MCd.saving_pct.max(), 0)
    put("mc_med", MCd.saving_pct.median(), 0)
    put("mc_minabs", MCd.saving_bnUSD.min())
    put("mc_maxabs", MCd.saving_bnUSD.max())
    put("mc_npos", int((MCd.saving_bnUSD > 0).sum()), 0)
    fig, axs = plt.subplots(1, 2, figsize=(7.5, 3.0), gridspec_kw=dict(width_ratios=[1, 1.4]))
    axs[0].scatter(np.zeros(len(MCd)) + np.random.default_rng(0).uniform(-0.15, 0.15, len(MCd)), MCd.saving_pct,
                   s=18, color="#545454", zorder=3)
    axs[0].set_xlim(-0.6, 0.6)
    axs[0].set_xticks([])
    axs[0].set_ylabel("Cost advantage of least cost [%]")
    axs[0].set_title(f"{len(MCd)} joint samples, 2035", fontsize=9, loc="left")
    axs[0].grid(axis="y", color="#e6e5e1", linewidth=0.6)
    if (GEN / "mc_src.csv").exists():
        src_ = pd.read_csv(GEN / "mc_src.csv", index_col=0)
        LBL = {"LNG_USD_MMBTU": "LNG price", "SOLAR_CAPEX_X": "PV cost", "ONWIND_CAPEX_X": "Onshore wind cost",
               "BAT_CAPEX_X": "Battery cost", "OFFWIND_CAPEX_X": "Offshore wind cost", "NUC_CAPEX_X": "Nuclear cost",
               "DISCOUNT": "Discount rate", "DEMAND_X": "Demand", "HYDRO_TWH": "Hydro energy"}
        v_ = src_.rho[::-1]
        axs[1].barh(range(len(v_)), v_.values, color=["#3b6ea8" if x > 0 else "#c0504d" for x in v_.values], height=0.6)
        axs[1].set_yticks(range(len(v_)), [LBL.get(k, k) for k in v_.index], fontsize=8)
        axs[1].axvline(0, color=MUTED, lw=0.6)
        axs[1].set_xlabel("Spearman rank correlation with the saving")
        axs[1].set_title("Drivers of the saving", fontsize=9, loc="left")
        axs[1].set_xlim(-1, 1)
        for k_, v__ in src_.rho.items():
            put(f"mcrho_{k_.split('_')[0].lower()}", v__, 2)
    fig.tight_layout()
    fig.savefig(FIG / "fig_mc.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
if (GEN / "benchmark_2024.csv").exists() and (GEN / "benchmark_2024.csv").stat().st_size > 10:  # 30-region benchmark (M7)
    BM = pd.read_csv(GEN / "benchmark_2024.csv")
    BK = {"30-region, economic dispatch": "eco", "30-region, observed gas offtake": "gq",
          "30-region, gas offtake, monthly hydro budgets": "hm"}
    for _, r in BM.iterrows():
        k = BK.get(r.case)
        c_ = {"coal": "coal", "gas": "gas", "hydro": "hydro", "onwind": "wind", "solar+rooftop": "solar", "other": "other"}[r.carrier]
        if k:
            put(f"bm{k}_{c_}", r.model_TWh, 1)
            put(f"bm{k}_{c_}_diff", r.diff_pct, 1)
            put(f"bm{k}_{c_}_absdiff", abs(r.diff_pct), 1)
            put(f"bm{k}_{c_}_dir", "below" if r.diff_pct < 0 else "above")
            put(f"bm{k}_{c_}_corr", r.monthly_corr, 2)
            put(f"bm{k}_northmax", r.north_import_max_GW, 1)
            put(f"bm{k}_shed", r.shed_TWh, 2)
if (GEN / "adequacy_margin.csv").exists():  # minimum operating margin
    AM = pd.read_csv(GEN / "adequacy_margin.csv")
    for pf, k in [("PDP8", "pdp"), ("Least cost", "lc")]:
        a_ = AM[AM.portfolio == pf]
        if len(a_):
            put(f"minmargin_{k}", a_.min_margin_pct.min(), 1)
            put(f"p1margin_{k}", a_.p1_margin_pct.median(), 0)
            M[f"minmargin_{k}_year"] = str(int(a_.loc[a_.min_margin_pct.idxmin(), "weather_year"]))
# fuel prices, emission factors, marginal and indicative levelised costs (2035, 8 % real)
cc5 = pd.read_csv(CODE.parent / "repo_data" / "costs" / "costs_2035.csv", index_col=0)


def _fix(t, cf_):
    r_ = cc5.loc[t]
    return r_.capex_usd_kw * 1e3 * (0.08 / (1 - 1.08 ** -r_.life) + r_.fom_pct / 100) / (8760 * cf_)


def _var(t):
    r_ = cc5.loc[t]
    return (r_.fuel_usd_mwhth / r_.eff if r_.eff > 0 else 0) + r_.vom_usd_mwh


def _cf(y, s_, t_, car):
    d_ = summ(y, s_, t_)
    if not d_ or d_["capacity_GW"].get(car, 0) <= 0:
        return None
    return d_["energy_TWh"].get(car, 0) / (d_["capacity_GW"][car] * 8.784)


cf_pv, cf_on, cf_off = _cf(2035, "opt", "_vn", "solar"), _cf(2035, "opt", "_vn", "onwind"), _cf(2035, "pdp8", "_vn", "offwind")
rows_ = []
for lab, t, fuel_lab, cf_ in [("Utility PV", "solar", "--", cf_pv), ("Onshore wind", "onwind", "--", cf_on),
                              ("Offshore wind", "offwind", "--", cf_off), ("Nuclear", "nuclear", "4.0", 0.85),
                              ("CCGT (LNG)", "CCGT", "62.9", 0.60), ("OCGT (LNG)", "OCGT", "62.9", 0.10),
                              ("Coal (existing)", "coal_existing", "14.5", None), ("Domestic gas", "gas_domestic", "41.9", None),
                              ("Imports", "imports", "--", None)]:
    r_ = cc5.loc[t]
    ef = r_.co2_t_mwhth / r_.eff if r_.eff > 0 else 0.0
    mc_ = _var(t)
    lc_ = f"{_fix(t, cf_) + mc_:.0f}" if (cf_ and r_.capex_usd_kw > 0) else "--"
    rows_.append(f"{lab} & {fuel_lab} & {r_.eff:.3g} & {ef:.2f} & {mc_:.0f} & " + (f"{cf_:.2f}" if cf_ else "--")
                 + f" & {lc_} " + r"\\")
    if t == "offwind" and cf_:
        put("lcoe_off", _fix(t, cf_) + mc_, 0)
        put("cf_off", cf_, 2)
    if t == "solar" and cf_:
        put("lcoe_pv", _fix(t, cf_) + mc_, 0)
    if t == "nuclear":
        put("lcoe_nuc", _fix(t, cf_) + mc_, 0)
(SUMMARY / "tab_lcoe_rows.tex").write_text("\n".join(r_.replace(" & 0.00 & 0.00 &", " & -- & -- &") for r_ in rows_) + "\n")
# ---------------- 11. combined main-text figures ----------------
if (GEN / "shapley_2035.csv").exists() and len(MG):
    SH2 = pd.read_csv(GEN / "shapley_2035.csv").set_index("group").reindex(list(GK))
    fig, (axa, axb) = plt.subplots(1, 2, figsize=(8.0, 3.6), gridspec_kw=dict(width_ratios=[1.15, 1]))
    labA = {"lng": "LNG fleet", "offwind": "Offshore wind", "nuclear": "Nuclear", "ac": "Inter-regional\ntransmission",
            "rest": "Solar, wind,\nstorage, OCGT"}
    colA = {"lng": PYPSA_COLORS["Gas"], "offwind": PYPSA_COLORS["Offshore wind"], "nuclear": PYPSA_COLORS["Nuclear"],
            "ac": PYPSA_COLORS["Transmission"], "rest": PYPSA_COLORS["Solar PV"]}
    order_ = SH2.shapley_bnUSD.sort_values().index
    y_ = np.arange(len(order_))
    axa.barh(y_, SH2.shapley_bnUSD[order_], color=[colA[g] for g in order_], height=0.55)
    axa.errorbar(SH2.shapley_bnUSD[order_], y_, xerr=[SH2.shapley_bnUSD[order_] - SH2.min_marginal_bnUSD[order_],
                 SH2.max_marginal_bnUSD[order_] - SH2.shapley_bnUSD[order_]], fmt="none", ecolor=INK, elinewidth=0.8, capsize=3)
    for yy, g in zip(y_, order_):
        axa.text(SH2.max_marginal_bnUSD[g] + 0.1, yy, f"{SH2.shapley_bnUSD[g]:.1f} ({SH2.share_pct[g]:.0f}%)", va="center",
                 fontsize=8.5, color=INK)
    axa.set_yticks(y_, [labA[g] for g in order_], fontsize=9.5)
    axa.set_xlabel("Saving from releasing the group [bn USD/a]", fontsize=9.5)
    axa.set_title(f"(a) Shapley values 2035, gap {SH2.gap_bnUSD.iloc[0]:.1f} bn USD/a", loc="left", fontsize=10)
    axa.set_xlim(0, SH2.max_marginal_bnUSD.max() * 1.45)
    axa.grid(axis="x", color="#e6e5e1", linewidth=0.6)
    axa.set_axisbelow(True)
    labB = {"offwind": "Offshore wind [GW]", "lng": "LNG [GW]", "nuclear": "Nuclear [GW]", "ac": "New AC [TW km/10]"}
    for k_, (_, r) in enumerate(MG.iterrows()):
        sc_ = 0.1 if r.group == "ac" else 1.0
        vals = [(r.least_cost, "Least cost", "#1f1e1c", "o"), (r.get("max_2pct"), "+2% cost", "#9ecae1", "s"),
                (r.get("max_5pct"), "+5% cost", "#4292c6", "s"), (r.get("max_10pct"), "+10% cost", "#08519c", "s"),
                (r.pdp8, "Plan", "#c0504d", "D")]
        axb.plot([0, max(v for v, *_ in vals if v == v) * sc_], [k_, k_], color="#e6e5e1", lw=1, zorder=1)
        for v, lab_, c_, mk in vals:
            if v == v and v is not None:
                axb.scatter(v * sc_, k_, color=c_, marker=mk, s=36, zorder=3, label=lab_ if k_ == 0 else None)
    axb.set_yticks(range(len(MG)), [labB[g] for g in MG.group], fontsize=9.5)
    axb.set_xlabel("Capacity", fontsize=9.5)
    axb.set_title("(b) Near-optimal space, 2035", loc="left", fontsize=10)
    axb.legend(fontsize=8.5, loc="upper center", bbox_to_anchor=(0.45, -0.2), ncol=3, frameon=False, columnspacing=0.8)
    axb.grid(axis="x", color="#e6e5e1", linewidth=0.6)
    fig.tight_layout()
    fig.savefig(FIG / "fig_attribution.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
if (GEN / "sensitivity.csv").exists() and (GEN / "mc.csv").exists() and len(RG):
    SEN = pd.read_csv(GEN / "sensitivity.csv")
    SEN = SEN[(SEN.year == 2035) & SEN.saving_pct.notna() & ~SEN.case.isin(SCEN_VAR)].sort_values("saving_pct")
    SEN["case"] = SEN.case.replace({"Base": "Central", "AC line cost x2 (circuit-3 benchmark)": "AC line cost x2",
                                    "Committed LNG: Nhon Trach 3&4 only": "Only Nhon Trach 3&4 committed",
                                    "No operating reserve / SNSP limit": "No operating reserve / SNSP",
                                    "PV and wind connection +100 USD/kW": "PV/wind connection +100 USD/kW",
                                    "Corridor limits 50 % of thermal rating": "Corridor limits 50 %"})
    MCd2 = pd.read_csv(GEN / "mc.csv")
    # legible at print width -> two rows, figure close to the printed size
    fig = plt.figure(figsize=(8.0, 8.4))
    gs_ = fig.add_gridspec(2, 2, width_ratios=[1, 0.32], height_ratios=[1.25, 1], hspace=0.32, wspace=0.08)
    axs = [fig.add_subplot(gs_[0, 0]), fig.add_subplot(gs_[0, 1]), fig.add_subplot(gs_[1, :])]
    ax = axs[0]
    yv = np.arange(len(SEN))
    ax.scatter(SEN.saving_pct, yv, color=["#c0504d" if c == "Central" else "#545454" for c in SEN.case], s=24, zorder=3)
    ax.set_yticks(yv, SEN.case, fontsize=9)
    ax.set_xlabel("Cost advantage of least cost [%]", fontsize=9.5)
    ax.set_title(f"(a) One-at-a-time sensitivities (n = {len(SEN) - 1})", loc="left", fontsize=10)
    ax.grid(axis="x", color="#e6e5e1", linewidth=0.6)
    ax.tick_params(axis="x", labelsize=9)
    ax = axs[1]
    ax.scatter(np.random.default_rng(0).uniform(-0.15, 0.15, len(MCd2)), MCd2.saving_pct, s=16, color="#545454")
    ax.set_xlim(-0.5, 0.5)
    ax.set_xticks([])
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.set_ylabel("Cost advantage [%]", fontsize=9.5)
    ax.tick_params(axis="y", labelsize=9)
    ax.set_title(f"(b) Monte Carlo, n = {len(MCd2)}", loc="left", fontsize=10)
    ax.grid(axis="y", color="#e6e5e1", linewidth=0.6)
    ax = axs[2]
    PKL = {"pdp8": ("PDP8", "#c0504d", "D"), "lc": ("Least cost", "#1f1e1c", "o"), "lcrange": ("Plan range, opt. lines", "#4292c6", "s"),
           "prgrid": ("Plan range, plan lines", "#9ecae1", "s"), "lcceil": ("Least cost, ceiling", "#7a9a01", "^")}
    yf = np.arange(len(RG))
    for k, (lab_, c_, mk) in PKL.items():
        if f"{k}_regret" in RG:
            ax.scatter(RG[f"{k}_regret"], yf, label=lab_, color=c_, marker=mk, s=26, zorder=3)
    ax.set_yticks(yf, [f.replace(" (2024 weather)", "") for f in RG.future], fontsize=9)
    ax.set_xlabel("Regret: cost above the cheapest portfolio [bn USD/a]", fontsize=9.5)
    ax.tick_params(axis="x", labelsize=9)
    ax.set_title("(c) Stress futures", loc="left", fontsize=10)
    ax.legend(fontsize=9, loc="upper center", bbox_to_anchor=(0.4, -0.13), ncol=3, frameon=False, columnspacing=1.0)
    ax.grid(axis="x", color="#e6e5e1", linewidth=0.6)
    fig.savefig(FIG / "fig_robust.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
# merged cost table (main text): investment, FOM, life, efficiency, fuel, marginal and levelised cost
cc6 = pd.read_csv(CODE.parent / "repo_data" / "costs" / "costs_2035.csv", index_col=0)
rows_ = []
for lab, t, cf_lab in [("Utility PV", "solar", "pv"), ("Onshore wind", "onwind", "on"), ("Offshore wind", "offwind", "off"),
                       ("CCGT (LNG)", "CCGT", 0.60), ("OCGT (LNG)", "OCGT", 0.10), ("Nuclear (PWR)", "nuclear", 0.85),
                       ("Battery, 4\\,h", "battery_4h", None), ("Pumped hydro, 5\\,h", "PHS", None),
                       ("Coal, existing", "coal_existing", None), ("Domestic gas", "gas_domestic", None)]:
    r_ = cc6.loc[t]
    cfv = {"pv": _cf(2035, "opt", "_vn", "solar"), "on": _cf(2035, "opt", "_vn", "onwind"),
           "off": _cf(2035, "pdp8", "_vn", "offwind")}.get(cf_lab, cf_lab) if cf_lab is not None else None
    capex = f"{r_.capex_usd_kw:,.0f}" if r_.capex_usd_kw > 0 else "--"
    fom = f"{r_.fom_pct:.1f}" if r_.capex_usd_kw > 0 else "--"
    life = f"{r_.life:.0f}" if r_.capex_usd_kw > 0 else "--"
    eff = f"{r_.eff:.3g}" if r_.eff > 0 else "--"
    fuel = f"{r_.fuel_usd_mwhth:.1f}" if r_.fuel_usd_mwhth > 0 else "--"
    mc_ = _var(t)
    lc_ = f"{_fix(t, cfv) + mc_:.0f} ({cfv:.2f})" if (cfv and r_.capex_usd_kw > 0) else "--"
    rows_.append(f"{lab} & {capex} & {fom} & {life} & {eff} & {fuel} & {mc_:.0f} & {lc_} \\\\")
rows_.append(f"500\\,kV AC line [USD/(MW\\,km)] & {cc6.loc['HVAC_line', 'capex_usd_kw']:.0f} & 2.0 & 50 & -- & -- & -- & -- \\\\")
(SUMMARY / "tab_cost_rows.tex").write_text("\n".join(rows_) + "\n")
# documented PDP8 capacity vector: table from the PDP8 runs, low (base) and high variants
PT = {"solar": "Solar PV incl. rooftop", "onwind": "Onshore wind", "offwind": "Offshore wind", "LNG": "LNG-fired CCGT",
      "gas": "Domestic gas", "coal": "Coal", "nuclear": "Nuclear", "hydro": "Hydropower", "PHS": "Pumped hydro",
      "battery": "Batteries", "OCGT": "Flexible (OCGT) incl. top-up", "imports": "Imports", "biomass": "Biomass and waste"}
cols_ = [(2035, "_vn"), (2035, "_vn_high"), (2040, "_vn"), (2040, "_vn_high")]
runs_ = {c: summ(c[0], "pdp8", c[1]) for c in cols_}
if all(runs_.values()):
    rows_ = []
    for t_, lab in PT.items():
        vals = []
        for c in cols_:
            cap_ = runs_[c]["capacity_GW"]
            v_ = cap_.get(t_, 0) + (cap_.get("rooftop", 0) if t_ == "solar" else 0)
            vals.append(f"{v_:.1f}")
        rows_.append(lab + " & " + " & ".join(vals) + r" \\")
    for c, lab in [("demand_TWh", "Demand [TWh]"), ("pmax_GW", "Peak demand [GW]")]:
        rows_.append(lab + " & " + " & ".join(f"{runs_[cc][c]:.0f}" for cc in cols_) + r" \\")
    (SUMMARY / "tab_pdp8_rows.tex").write_text("\n".join(rows_) + "\n")
lines = ["% key indicators, generated by workflow/scripts/make_summary.py -- do not edit",
         f"% results: {RES}",
         r"\newcommand{\R}[1]{\ifcsname r@#1\endcsname\csname r@#1\endcsname\else\textcolor{gray}{[pending]}\fi}",
         r"\newcommand{\provisional}{" + ("Provisional numbers from model run set " + RES.name.replace("_", "-") +
                                           "; final results pending." if PROVISIONAL else "") + "}"]
lines += [rf"\expandafter\def\csname r@{k}\endcsname{{{v}}}" for k, v in sorted(M.items())]
(SUMMARY / "key_indicators.tex").write_text("\n".join(lines) + "\n")
pd.Series(M, name="value").rename_axis("key").sort_index().to_csv(SUMMARY / "key_indicators.csv")
print(f"{len(M)} key indicators ->", SUMMARY / "key_indicators.csv")
