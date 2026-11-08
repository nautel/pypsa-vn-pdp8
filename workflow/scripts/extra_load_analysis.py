#!/usr/bin/env python3
"""What must Vietnam's grid do for data centres (DC), the North-South high-speed rail (HSR), or both?
(A) PDP8 plan fixed: adequacy (unserved energy), reserve margin, congestion, nodal prices at the new loads, fuel/CO2.
(B) Least-cost: extra generation/storage by technology and region, extra inter-regional transmission by corridor,
    extra cost per MWh of new load. All differences are against the base (no extra load) run of the same type/year.
Inputs: <DATA>/expansion/results/<year>_{pdp8,opt}{_vn,_vn_dc,_vn_hsr,_vn_dchsr}.nc/_summary.json
Outputs: <DATA>/figures/expansion/extra_load_{summary.csv,corridors.csv,regions.csv}, extra_load_map_<year>.png
Run: python workflow/scripts/extra_load_analysis.py
"""
import json
import os
import sys
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import logging  # noqa: E402

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402
from matplotlib.patches import Patch, Wedge  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plot_vn import INK, INK2, PALETTE, PYPSA_COLORS, SLOTS, SURF, basemap, save, vnum  # noqa: E402

logging.disable(logging.WARNING)
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
RES = Path(os.environ.get("RES_DIR", DATA / "expansion" / "results"))  # RES_DIR/FIG_DIR: run set and output directory
OUT = Path(os.environ.get("FIG_DIR", DATA / "figures" / "expansion"))
OUT.mkdir(parents=True, exist_ok=True)
VAR = {"_vn_dc": "Data centres", "_vn_hsr": "High-speed rail", "_vn_dchsr": "DC + HSR"}
BASE = "_vn"
GRP = {"coal": "Coal", "gas": "Gas", "LNG": "Gas", "OCGT": "Gas", "oil": "Gas", "nuclear": "Nuclear",
       "solar": "Solar PV", "rooftop": "Solar PV", "onwind": "Onshore wind", "offwind": "Offshore wind",
       "battery": "Battery", "PHS": "Pumped hydro", "hydro": "Hydro", "biomass": "Other", "imports": "Other"}
ORDER = ["Solar PV", "Onshore wind", "Offshore wind", "Battery", "Pumped hydro", "Gas", "Nuclear", "Other"]
COL = dict(zip(ORDER, SLOTS))
UP, DOWN = "rosybrown", "#5b84b1"  # corridor change: AC colour of PyPSA-Eur vs muted blue
RADD, LWD = 0.09, 0.6  # pie radius [deg per sqrt(GW added)], line width [pt per GW change]
if PALETTE == "pypsa":
    COL = {k: PYPSA_COLORS[k] for k in ORDER}
DC_SITES = {"Hòa Lạc": (105.53, 21.01), "Yên Phong": (105.98, 21.20), "Đà Nẵng": (108.15, 16.07),
            "Thủ Đức": (106.79, 10.84)}
cl = pd.read_csv(DATA / "expansion" / "clusters.csv", index_col=0)
prov = gpd.read_file(DATA / "shapes" / "gadm41_VNM_1.json")
pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(cl.x, cl.y), index=cl.index, crs=4326)
cl["prov"] = gpd.sjoin_nearest(pts.to_crs(32648), prov[["NAME_1", "geometry"]].to_crs(32648)) \
    .groupby(level=0).NAME_1.first()
near = lambda lon, lat: cl.index[np.argmin(np.hypot(cl.x - lon, cl.y - lat))]  # noqa: E731
DC_CL = {k: near(*v) for k, v in DC_SITES.items()}


def load(y, s, t):
    js, nc = RES / f"{y}_{s}{t}_summary.json", RES / f"{y}_{s}{t}.nc"
    if not (js.exists() and nc.exists()):
        return None
    return json.loads(js.read_text()), pypsa.Network(nc)


def caps(n):
    g = n.generators[n.generators.carrier != "load shedding"]
    s = n.storage_units
    a = pd.concat([pd.DataFrame({"bus": g.bus, "car": g.carrier, "mw": g.p_nom_opt.where(g.p_nom_extendable, g.p_nom)}),
                   pd.DataFrame({"bus": s.bus, "car": s.carrier, "mw": s.p_nom_opt.where(s.p_nom_extendable, s.p_nom)})])
    a["grp"] = a.car.map(GRP)
    return a.groupby(["bus", "grp"]).mw.sum().unstack(fill_value=0)


def lmp(n, buses):
    w = n.snapshot_weightings.generators
    p = n.buses_t.marginal_price[buses].clip(upper=3000)
    return float((p.mul(w, axis=0).sum() / w.sum()).mean())


def binding_hours(n):
    lk = n.links
    cap = lk.p_nom_opt.where(lk.p_nom_extendable, lk.p_nom).replace(0, np.nan)
    ld = n.links_t.p0.abs().div(cap, axis=1)
    lam = n.buses_t.marginal_price.clip(upper=3000)
    dl = np.abs(lam[lk.bus1].values - lam[lk.bus0].values)
    w = n.snapshot_weightings.generators
    return pd.Series((((ld.values >= 0.99) & (dl >= 1)) * w.values[:, None]).sum(0) / w.sum() * 100, index=lk.index)


rows, corr, regs, maps = [], [], [], {}
for y in [2035, 2040]:
    base = {s: load(y, s, BASE) for s in ["pdp8", "opt"]}
    for t, lab in VAR.items():
        for s in ["pdp8", "opt"]:
            cur, ref = load(y, s, t), base[s]
            if cur is None or ref is None:
                continue
            (d, n), (d0, n0) = cur, ref
            c, c0 = d["cost_bnUSD_per_year"], d0["cost_bnUSD_per_year"]
            dc_buses = sorted(set(DC_CL.values()))
            r = {"year": y, "case": lab, "run": "PDP8 fixed" if s == "pdp8" else "Least cost",
                 "extra_TWh": d.get("extra_TWh", 0), "extra_peak_MW": d.get("extra_peak_MW", 0),
                 "unserved_TWh": d["load_shedding_TWh"], "reserve_margin_pct": 100 * d["firm_capacity_GW"] / d["pmax_GW"],
                 "d_cost_bnUSD_yr": c["total_excl_VOLL"] - c0["total_excl_VOLL"],
                 "d_cost_USD_per_MWh_new_load": (c["total_excl_VOLL"] - c0["total_excl_VOLL"]) * 1e3 / max(d.get("extra_TWh", 0), 1e-9),
                 "d_overnight_bnUSD": sum(d["overnight_investment_new_bnUSD"].values()) - sum(d0["overnight_investment_new_bnUSD"].values()),
                 "d_co2_Mt": d["co2_Mt"] - d0["co2_Mt"],
                 "LMP_DC_sites_USD_MWh": lmp(n, dc_buses), "d_LMP_DC_sites": lmp(n, dc_buses) - lmp(n0, dc_buses),
                 "corridors_binding_5pct": int((binding_hours(n) >= 5).sum()),
                 "d_corridors_binding_5pct": int((binding_hours(n) >= 5).sum() - (binding_hours(n0) >= 5).sum()),
                 "co2_cap_mu": float(n.global_constraints.mu.get("CO2", 0.0)) if "CO2" in n.global_constraints.index else None}
            if s == "opt":
                k, k0 = caps(n), caps(n0).reindex_like(caps(n)).fillna(0)
                dk = (k - k0).reindex(columns=ORDER, fill_value=0)
                for g_ in ORDER:
                    r[f"d_{g_}_GW"] = float(dk[g_].sum() / 1e3)
                lk, lk0 = n.links, n0.links
                pn = lk.p_nom_opt.where(lk.p_nom_extendable, lk.p_nom)
                pn0 = lk0.p_nom_opt.where(lk0.p_nom_extendable, lk0.p_nom).reindex(pn.index).fillna(0)
                dl = (pn - pn0)
                for i in dl.index[dl.abs() >= 50]:
                    corr.append({"year": y, "case": lab, "link": i, "type": lk.carrier[i],
                                 "from": cl.prov[lk.bus0[i]], "to": cl.prov[lk.bus1[i]], "km": round(lk.length[i]),
                                 "d_MW": round(dl[i]), "MW": round(pn[i])})
                for b_, row in dk.iterrows():
                    if row.abs().sum() >= 50:
                        regs.append({"year": y, "case": lab, "region": b_, "province": cl.prov[b_],
                                     **{g_: round(row[g_]) for g_ in ORDER}})
                maps[(y, lab)] = (n, dk, dl)
            rows.append(r)
S = pd.DataFrame(rows)
S.round(2).to_csv(OUT / "extra_load_summary.csv", index=False)
pd.DataFrame(corr).to_csv(OUT / "extra_load_corridors.csv", index=False)
pd.DataFrame(regs).to_csv(OUT / "extra_load_regions.csv", index=False)
with pd.option_context("display.width", 250, "display.max_columns", 40):
    print(S.round(2).to_string(index=False))
    if corr:
        C = pd.DataFrame(corr)
        print("\n--- corridors changed in least-cost runs (|dMW|>=50)\n",
              C.sort_values(["year", "case", "d_MW"], ascending=[True, True, False]).to_string(index=False))
    if regs:
        print("\n--- regional capacity change (MW) in least-cost runs\n", pd.DataFrame(regs).to_string(index=False))

# ---- maps: where to build (least-cost delta vs base), one row per year, columns DC / HSR / DC+HSR ----
for y in sorted({k[0] for k in maps}):
    labs = [lab for lab in VAR.values() if (y, lab) in maps]
    fig, axs = plt.subplots(1, len(labs), figsize=(5.4 * len(labs), 8.2), squeeze=False)
    for ax, lab in zip(axs[0], labs):
        n, dk, dl = maps[(y, lab)]
        basemap(ax)
        b = n.buses
        for i in n.links.index:  # all corridors faint, changed ones coloured (orange = more, blue = less)
            x0, y0, x1, y1 = b.x[n.links.bus0[i]], b.y[n.links.bus0[i]], b.x[n.links.bus1[i]], b.y[n.links.bus1[i]]
            ls = (0, (4, 2)) if n.links.carrier[i] == "DC" else "-"
            if abs(dl[i]) >= 50:
                ax.plot([x0, x1], [y0, y1], color=UP if dl[i] > 0 else DOWN, ls=ls, zorder=3,
                        lw=max(0.8, min(abs(dl[i]) / 1e3 * LWD, 5)), solid_capstyle="butt")
            else:
                ax.plot([x0, x1], [y0, y1], color="#c8c8c8", lw=0.4, ls=ls, zorder=2)
        for bus, row in dk.iterrows():
            pos = row.clip(lower=0)
            if pos.sum() < 100:
                continue
            start, rad = 0.0, RADD * np.sqrt(pos.sum() / 1e3)
            for g_ in ORDER:
                if pos[g_] > 0:
                    ang = 360 * pos[g_] / pos.sum()
                    ax.add_patch(Wedge((b.x[bus], b.y[bus]), rad, start, start + ang, facecolor=COL[g_], edgecolor=SURF,
                                       linewidth=0.3, zorder=5))
                    start += ang
        if "DC" in lab or "Data" in lab:
            for k_, (lo, la) in DC_SITES.items():
                ax.plot(lo, la, marker="s", ms=6, mfc=INK, mec=SURF, zorder=6)
                left_ = k_.startswith("H")  # Hoa Lac and Yen Phong are close: label Hoa Lac to the left
                ax.annotate(k_, (lo, la), xytext=(-5, -3) if left_ else (5, -3), textcoords="offset points", fontsize=8,
                            color=INK, zorder=7, ha="right" if left_ else "left")
        r = S[(S.year == y) & (S.case == lab) & (S.run == "Least cost")]
        sub = (f"+{vnum(r.extra_TWh.iloc[0], 1)} TWh · +{vnum(r.d_cost_bnUSD_yr.iloc[0], 2)} bn USD/yr · "
               f"{vnum(r.d_cost_USD_per_MWh_new_load.iloc[0])} USD/MWh") if len(r) else ""
        ax.set_title(f"{lab}, {y}\n{sub}", loc="left", fontsize=10)
    for k_, gw in enumerate([10, 5, 1]):  # pie size legend in data units (PyPSA add_legend_circles style), placed
        yy = 13.5 - 0.75 * k_                # over Cambodia (empty), clear of the outside colour legend
        axs[0][0].add_patch(plt.Circle((102.5, yy), RADD * np.sqrt(gw), facecolor="none", edgecolor=INK, lw=0.6, zorder=6))
        axs[0][0].text(102.95, yy, f"{gw} GW", va="center", fontsize=7.5, color=INK)
    axs[0][0].text(102.1, 14.15, "Added capacity", fontsize=8, color=INK)
    axs[0][-1].legend(handles=[Patch(color=COL[g_], label=g_) for g_ in ORDER] +
                      [plt.Line2D([], [], color=UP, lw=3, label="corridor reinforced"),
                       plt.Line2D([], [], color=DOWN, lw=3, label="corridor reduced"),
                       plt.Line2D([], [], color=INK2, lw=2, ls=(0, (4, 2)), label="HVDC")],
                      loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=8, frameon=False)
    fig.text(0.01, 0.01, "Least-cost expansion with the extra load minus least-cost expansion without it (same year). "
             "Pies: added capacity by region (area ~ MW). Squares: data-centre sites.", fontsize=8.5, color=INK)
    save(fig, OUT, f"extra_load_map_{y}")
