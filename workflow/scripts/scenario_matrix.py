#!/usr/bin/env python3
"""Scenario matrix (PyPSA-ZA style, Hörsch & Calitz 2017): average system cost per MWh by technology for
PDP8 (fixed plan) vs least-cost pathways under CO2 policies and extra loads, 2035 and 2040.
Costs are incremental to the 2024 fleet: annualised capex+FOM of new assets (+ transmission) + fuel/VOM of all assets.
Inputs: <DATA>/expansion/results/<year>_<scen><tag>.nc (+ _summary.json)
Outputs: <DATA>/figures/expansion/scenario_matrix.{png,csv}
Run: python workflow/scripts/scenario_matrix.py
"""
import json
import os
import sys
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import logging  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plot_vn import INK, INK2, PALETTE, PYPSA_COLORS, SLOTS, SURF, save, vnum  # noqa: E402

logging.disable(logging.WARNING)
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
RES = Path(os.environ.get("RES_DIR", DATA / "expansion" / "results"))  # RES_DIR/FIG_DIR: run set and output directory
OUT = Path(os.environ.get("FIG_DIR", DATA / "figures" / "expansion"))
OUT.mkdir(parents=True, exist_ok=True)
# (label, scenario, tag) in display order
SCEN = [("PDP8 plan", "pdp8", "_vn"), ("PDP8, LNG take-or-pay", "pdp8", "_vn_lngqc"), ("Least cost", "opt", "_vn"), ("CO$_2$ −50%", "opt", "_vn_co2half"),
        ("Zero CO$_2$", "opt", "_vn_co2zero"), ("Zero CO$_2$, no build cap", "opt", "_vn_co2zero_nolim"), ("PDP8 + DC", "pdp8", "_vn_dc"), ("Least cost + DC", "opt", "_vn_dc"),
        ("PDP8 + HSR", "pdp8", "_vn_hsr"), ("Least cost + HSR", "opt", "_vn_hsr"),
        ("PDP8 + DC + HSR", "pdp8", "_vn_dchsr"), ("Least cost + DC + HSR", "opt", "_vn_dchsr"),
        ("PDP8, emission ceiling", "pdp8", "_vn_co2plan"), ("Least cost, emission ceiling", "opt", "_vn_co2plan"),
        ("Least cost, plan range", "opt", "_vn_planrange"), ("PDP8, high variant", "pdp8", "_vn_high"),
        ("Least cost, high demand", "opt", "_vn_high"), ("Plan range, plan lines", "pdp8", "_vn_prgrid")]
# figure: display names consistent with the scenario table; subset shown (all rows stay in the CSV)
DISPLAY = {"PDP8 plan": "PDP8", "Zero CO$_2$": "Zero CO$_2$, build-rate limits", "Zero CO$_2$, no build cap": "Zero CO$_2$",
           "Least cost, plan range": "Plan range, optimised lines"}
PLOT_MAIN = ["PDP8 plan", "PDP8, LNG take-or-pay", "PDP8, emission ceiling", "Plan range, plan lines",
             "Least cost, plan range", "Least cost", "Least cost, emission ceiling", "CO$_2$ −50%"]
PLOT = ["PDP8 plan", "PDP8, LNG take-or-pay", "PDP8, emission ceiling", "Least cost", "Least cost, plan range",
        "Least cost, emission ceiling", "CO$_2$ −50%", "Zero CO$_2$, no build cap", "Zero CO$_2$", "PDP8 + DC + HSR",
        "Least cost + DC + HSR"]
GRP = {"coal": "Coal", "gas": "Gas", "LNG": "Gas", "OCGT": "Gas", "oil": "Other", "nuclear": "Nuclear",
       "solar": "Solar PV", "rooftop": "Solar PV", "onwind": "Onshore wind", "offwind": "Offshore wind",
       "battery": "Storage", "PHS": "Storage", "hydro": "Other", "biomass": "Other", "imports": "Other"}
ORDER = ["Coal", "Onshore wind", "Solar PV", "Storage", "Other", "Gas", "Offshore wind", "Nuclear", "Transmission"]
COL = dict(zip(ORDER, SLOTS + ["#52514e"]))
if PALETTE == "pypsa":
    COL = {k: PYPSA_COLORS[k] for k in ORDER}


def costs_by_tech(nc, summ):
    n = pypsa.Network(nc)
    w = n.snapshot_weightings.generators
    g, s = n.generators, n.storage_units
    g = g[g.carrier != "load shedding"]
    new_g = g.index[g.index.str.contains(" new") | g.p_nom_extendable]
    capg = g.p_nom_opt.where(g.p_nom_extendable, g.p_nom)
    capex = (capg[new_g] * g.capital_cost[new_g]).groupby(g.carrier[new_g]).sum()
    caps = s.p_nom_opt.where(s.p_nom_extendable, s.p_nom)
    new_s = s.index[s.carrier.isin(["battery", "PHS"])]
    capex = capex.add((caps[new_s] * s.capital_cost[new_s]).groupby(s.carrier[new_s]).sum(), fill_value=0)
    opex = (n.generators_t.p[g.index].mul(w, axis=0).sum() * g.marginal_cost).groupby(g.carrier).sum()
    tot = capex.add(opex, fill_value=0)
    out = tot.groupby(tot.index.map(GRP)).sum().reindex(ORDER).fillna(0) / 1e9
    out["Transmission"] = summ["cost_bnUSD_per_year"]["annualised_new_transmission"]
    out["Coal"] += summ.get("indicators", {}).get("startup_cost_bnUSD", 0.0)  # v4 coal unit commitment start-ups
    shed = summ["cost_bnUSD_per_year"].get("unserved_energy_at_VOLL", 0.0)
    return out, shed


rows, stacks = [], {}
for y in [2035, 2040]:
    for lab, sc, tag in SCEN:
        js, nc = RES / f"{y}_{sc}{tag}_summary.json", RES / f"{y}_{sc}{tag}.nc"
        if not (js.exists() and nc.exists()):
            continue
        d = json.loads(js.read_text())
        bt, shed = costs_by_tech(nc, d)
        dem = d["demand_TWh"]
        stacks[(y, lab)] = bt / dem * 1e3  # USD/MWh
        rows.append({"year": y, "scenario": lab.replace("$_2$", "2"), "demand_TWh": dem,
                     "total_bnUSD_yr": bt.sum(), "avg_cost_USD_MWh": bt.sum() / dem * 1e3, "unserved_bnUSD_VOLL": shed, "unserved_pct": 100 * d.get("load_shedding_TWh", 0.0) / dem,
                     "co2_Mt": d["co2_Mt"], "co2_shadow_USD_t": d.get("co2_shadow_USD_per_t", 0.0),
                     "overnight_bnUSD": sum(d["overnight_investment_new_bnUSD"].values()),
                     "overnight_grid_bnUSD": d["overnight_investment_new_bnUSD"].get("transmission_lines", 0.0),
                     "HVDC_GW": d["transmission_added"].get("HVDC_GW", 0.0),
                     **{f"{k}_GW": v for k, v in d["capacity_GW"].items()}})
T = pd.DataFrame(rows).round(2)
T.to_csv(OUT / "scenario_matrix.csv", index=False)
pd.DataFrame({f"{y}|{lab.replace('$_2$', '2')}": v for (y, lab), v in stacks.items()}).T.round(3).to_csv(
    OUT / "scenario_matrix_stacks.csv")  # USD/MWh by technology group (figure insets)
print(T[["year", "scenario", "total_bnUSD_yr", "avg_cost_USD_MWh", "co2_Mt", "co2_shadow_USD_t", "overnight_bnUSD"]]
      .to_string(index=False))

# ---- figure: average system cost per MWh, stacked by technology (one panel per year) ----
def cost_figure_h(PLOT, name, voll=False):
  """Horizontal stacked bars, scenario labels once, legible at print width.
  voll: add unserved energy at VOLL as a hatched segment, clipped, with the share of demand unserved in the label."""
  years = [y for y in [2035, 2040] if any(k[0] == y for k in stacks)]
  fs = 10
  labs = [lab for lab in PLOT if any((y, lab) in stacks for y in years)]
  fig, axs = plt.subplots(1, len(years), figsize=(8.0, 1.0 + 0.42 * len(labs)), sharey=True, squeeze=False)
  yv = np.arange(len(labs))[::-1]
  rows = {}
  for y in years:
      for lab in labs:
          if (y, lab) not in stacks:
              continue
          r = T[(T.year == y) & (T.scenario == lab.replace("$_2$", "2"))].iloc[0]
          rows[(y, lab)] = (sum(max(float(stacks[(y, lab)][t]), 0.0) for t in ORDER), r)
  xmax = max(b for b, _ in rows.values())
  clip = 1.12 * xmax
  for ax, y in zip(axs[0], years):
      for yy, lab in zip(yv, labs):
          if (y, lab) not in stacks:
              ax.text(1.2, yy, "not run", va="center", fontsize=fs - 1.5, color=INK2, style="italic")
              continue
          b = 0.0
          for t in ORDER:
              v = stacks[(y, lab)][t]
              if v > 0:
                  ax.barh(yy, v, left=b, color=COL[t], height=0.7, edgecolor=SURF, linewidth=0.8,
                          hatch="xx" if t == "Transmission" else None)
                  b += v
          r = rows[(y, lab)][1]
          vo = 1e3 * r.unserved_bnUSD_VOLL / r.demand_TWh if voll else 0.0
          tot = b + vo
          if vo > 0.05:
              ax.barh(yy, min(vo, clip - b), left=b, color="#8b1a1a", height=0.7, edgecolor=SURF, linewidth=0.8, hatch="//")
          co2_ = max(float(r.co2_Mt), 0.0) if abs(r.co2_Mt) >= 0.5 else 0.0
          txt = f"{vnum(tot)}{'*' if tot > clip else ''} | {vnum(co2_)} Mt"
          if voll and r.unserved_pct >= 0.01:
              txt += f" | {vnum(r.unserved_pct, 1 if r.unserved_pct >= 1 else 2)}%†"
          ax.text(min(tot, clip) + 1.2, yy, txt, va="center", fontsize=fs - 1.5, color=INK)
      ax.set_title(f"{y}", loc="left", fontsize=fs + 1, weight="bold")
      ax.grid(axis="x")
      ax.set_axisbelow(True)
      ax.tick_params(axis="x", labelsize=fs - 1)
      ax.set_xlabel("Average system cost [USD/MWh]", fontsize=fs - 1)
      ax.set_xlim(0, xmax * (1.75 if voll else 1.42))
  axs[0][0].set_yticks(yv, [DISPLAY.get(l_, l_) for l_ in labs], fontsize=fs)
  handles = [plt.Rectangle((0, 0), 1, 1, color=COL[t], hatch="xx" if t == "Transmission" else None,
                           ec=SURF if t != "Transmission" else INK2) for t in ORDER]
  names = list(ORDER)
  if voll:
      handles.append(plt.Rectangle((0, 0), 1, 1, color="#8b1a1a", hatch="//", ec=SURF))
      names.append("Unserved energy (VOLL)")
  fig.legend(handles, names, loc="upper center", bbox_to_anchor=(0.55, 0.02), ncol=5, fontsize=fs - 1, frameon=False)
  fig.tight_layout()
  save(fig, OUT, name)


def cost_figure(PLOT, name, compact=False):
  # compact: main-text version (fonts legible at print width, legend below, no footnote)
  W, H, fs = (4.6, 4.6, 11) if compact else (7.4, 5.8, 9)
  years = [y for y in [2035, 2040] if any(k[0] == y for k in stacks)]
  fig, axs = plt.subplots(1, len(years), figsize=(W * len(years), H), sharey=True, squeeze=False)
  for ax, y in zip(axs[0], years):
      labs = [lab for lab in PLOT if (y, lab) in stacks]
      tops = []
      for i, lab in enumerate(labs):
          b = 0.0
          for t in ORDER:
              v = stacks[(y, lab)][t]
              if v > 0:
                  ax.bar(i, v, bottom=b, color=COL[t], width=0.72, edgecolor=SURF, linewidth=1.0,
                         hatch="xx" if t == "Transmission" else None)
                  b += v
          r = T[(T.year == y) & (T.scenario == lab.replace("$_2$", "2"))].iloc[0]
          vo = 1e3 * r.unserved_bnUSD_VOLL / r.demand_TWh  # unserved energy valued at VOLL, USD/MWh
          tops.append((i, b, vo, r))
      ymax = 1.3 * max(t_[1] + (t_[2] if t_[2] < 0.5 * t_[1] else 0) for t_ in tops)
      for i, b, vo, r in tops:
          if vo > 0.05:  # unserved energy at VOLL, stacked on top (clipped at the axis limit)
              ax.bar(i, min(vo, ymax - b), bottom=b, color="#8b1a1a", width=0.72, edgecolor=SURF, linewidth=1.0, hatch="//")
          tot_ = b + vo
          note = (f"\n†{vnum(r.unserved_pct, 1 if r.unserved_pct >= 1 else 2)}%" if r.unserved_pct >= 0.01 else "")
          ytxt = min(tot_, ymax * 0.82) + 1
          co2_ = max(float(r.co2_Mt), 0.0) if abs(r.co2_Mt) >= 0.5 else 0.0  # no "-0" labels
          ax.text(i, ytxt, f"{vnum(tot_)}{'↑' if tot_ > ymax else ''}\n{vnum(co2_)} Mt{note}", ha="center",
                  va="bottom", fontsize=fs - 0.5, color=INK, bbox=dict(facecolor=SURF, edgecolor="none", pad=1.0, alpha=0.9))
      ax.set_ylim(0, ymax)
      ax.set_xticks(range(len(labs)), [DISPLAY.get(l_, l_) for l_ in labs], rotation=35 if compact else 30, ha="right", fontsize=fs)
      ax.tick_params(axis="y", labelsize=fs)
      ax.grid(axis="y")
      ax.set_title(f"{y}", loc="left", fontsize=fs + 2, weight="bold")
  axs[0][0].set_ylabel("Average system cost [USD/MWh]\n(incremental to the 2024 fleet)", fontsize=fs)
  handles = [plt.Rectangle((0, 0), 1, 1, color=COL[t], hatch="xx" if t == "Transmission" else None,
                           ec=SURF if t != "Transmission" else INK2) for t in ORDER[::-1]]
  handles = [plt.Rectangle((0, 0), 1, 1, color="#8b1a1a", hatch="//", ec=SURF)] + handles
  if compact:
      fig.legend(handles[1:], ORDER[::-1], loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=5, fontsize=fs, frameon=False)
      save(fig, OUT, name)
      return
  axs[0][-1].legend(handles, ["Unserved energy (VOLL)"] + ORDER[::-1], loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=9, frameon=False)
  fig.text(0.01, -0.13, "Labels above bars: average cost and CO$_2$ emissions. Least-cost runs co-optimise generation, "
           "storage and inter-regional transmission (30 regions, 1-in-4-day 3-hourly sampling); PDP8 runs fix the plan's "
           "capacities (Decisions 768/1509). Unserved energy is valued at 3,000 USD/MWh (dark red; ↑ bar clipped); † share of demand unserved.", fontsize=8.5, color=INK, wrap=True)
  save(fig, OUT, name)


cost_figure_h(PLOT_MAIN, "scenario_matrix")  # main text: main scenarios
cost_figure_h(PLOT, "scenario_matrix_full", voll=True)  # Supplementary Material: all scenarios
