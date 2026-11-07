#!/usr/bin/env python3
"""v5 robustness tables from results_v5 summaries.

adequacy.csv     fixed 2035 portfolios dispatched over weather years 2015-2024 x hydro (normal/dry), forced outages:
                 expected unserved energy (EUE), loss-of-load hours (LOLE), cost
regret.csv       fixed portfolios under stress futures (cost incl. unserved energy at VOLL) and regret vs. the better one
mga.csv          near-optimal (+5 % cost) maximum capacity of each plan group vs. its least-cost and PDP8 value
robust.csv       pathway 2040, every-second-day resolution, crossover, plan-range least cost, static credits
credits.csv      implied capacity credits (net output in the 10 highest net-load snapshots / capacity), SNSP
Run: RES_DIR=.../results_v5 FIG_DIR=... python expansion/v5_tables.py
"""
import json
import os
from pathlib import Path

import pandas as pd

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[1] / "data"))
RES = Path(os.environ.get("RES_DIR", DATA / "expansion" / "results_v6"))
OUT = Path(os.environ.get("FIG_DIR", DATA / "figures" / "expansion_v5"))
OUT.mkdir(parents=True, exist_ok=True)


def S(y, s, t):
    f = RES / f"{y}_{s}{t}_summary.json"
    return json.loads(f.read_text()) if f.exists() else None


def tot(d):  # system cost incl. unserved energy at VOLL
    c = d["cost_bnUSD_per_year"]
    return c["total_excl_VOLL"] + c.get("unserved_energy_at_VOLL", 0.0)


# adequacy
rows = []
for s, lab in [("pdp8", "PDP8"), ("opt", "Least cost")]:
    for wy in range(2015, 2025):
        for htag, hyd in [("", "normal"), ("d", "dry")]:
            d = S(2035, s, f"_vn_fix_w{wy}{htag}")
            if d:
                rows.append({"portfolio": lab, "weather_year": wy, "hydro": hyd, "eue_TWh": d["load_shedding_TWh"],
                             "eue_ppm": 1e6 * d["load_shedding_TWh"] / d["demand_TWh"],
                             "lole_h": d["indicators"].get("lole_h", float("nan")), "cost_bnUSD": tot(d),
                             "co2_Mt": d["co2_Mt"]})
A = pd.DataFrame(rows)
if len(A):
    A.round(4).to_csv(OUT / "adequacy.csv", index=False)
    print(A.groupby(["portfolio", "hydro"])[["eue_TWh", "eue_ppm", "lole_h", "cost_bnUSD"]].agg(["mean", "max"]).round(3))
# regret: fixed 2035 portfolios under stress futures (v6: five portfolios, nine futures)
PORT = {"pdp8": ("pdp8", "_vn"), "lc": ("opt", "_vn"), "lcrange": ("opt", "_vn_planrange"), "lcceil": ("opt", "_vn_co2plan"),
        "prgrid": ("pdp8", "_vn_prgrid")}
FUT = {"_ref": "Reference (2024 weather)", "_dem": "Demand +11 %", "_lng": "LNG 25 USD/MMBtu", "_dry": "Dry year (80 TWh hydro)",
       "_pv": "Half of new PV built", "_coal": "Coal price +50 %", "_bat": "Half of batteries delivered",
       "_north": "Corridors into the North at 50 %", "_weak": "Weak-wind year 2022 and dry hydro"}
rows = []
for f_, lab in FUT.items():
    r = {"future": lab, "key": f_.strip("_")}
    for k, (s_, src) in PORT.items():
        d = S(2035, s_, f"{src}_rg{f_}")
        if d:
            r[f"{k}_cost"], r[f"{k}_eue"] = tot(d), d["load_shedding_TWh"]
    costs = {k: r[f"{k}_cost"] for k in PORT if f"{k}_cost" in r}
    if costs:
        best = min(costs.values())
        for k, c in costs.items():
            r[f"{k}_regret"] = c - best
    rows.append(r)
R = pd.DataFrame(rows)
R.round(3).to_csv(OUT / "regret.csv", index=False)
print(R.round(2).to_string(index=False))
if len(R) and all(f"{k}_regret" in R for k in PORT):
    mx = R[[f"{k}_regret" for k in PORT]].max()
    print("maximum regret [bn USD/a]:", mx.round(2).to_dict())
# MGA: maximum capacity of each plan group at +2/5/10 % cost
lc, pdp = S(2035, "opt", "_vn"), S(2035, "pdp8", "_vn")
rows = []
for grp, car in [("offwind", "offwind"), ("lng", "LNG"), ("nuclear", "nuclear"), ("ac", None)]:
    if not (lc and pdp):
        break
    val = (lambda d: d["capacity_GW"].get(car, 0)) if car else (lambda d: d["transmission_added"]["AC_interregion_TWkm"])
    r = {"group": grp, "unit": "GW" if car else "TWkm", "least_cost": val(lc), "pdp8": val(pdp)}
    for et, tag in [("2", f"_vn_mga2_{grp}"), ("5", f"_vn_mga_{grp}"), ("10", f"_vn_mga10_{grp}")]:
        d = S(2035, "opt", tag)
        if d:
            r[f"max_{et}pct"] = val(d)
    rows.append(r)
M = pd.DataFrame(rows)
if len(M):
    M.round(2).to_csv(OUT / "mga.csv", index=False)
    print(M.round(2).to_string(index=False))
# robustness runs
rows = []
for lab, y, a, b in [("Central", 2035, ("pdp8", "_vn"), ("opt", "_vn")), ("Central", 2040, ("pdp8", "_vn"), ("opt", "_vn")),
                     ("Pathway from 2035", 2040, ("pdp8", "_vn_path"), ("opt", "_vn_path")),
                     ("Every 2nd day", 2035, ("pdp8", "_vn_ds2"), ("opt", "_vn_ds2")),
                     ("Crossover", 2035, ("pdp8", "_vn"), ("opt", "_vn_xo")),
                     ("Least cost within plan ranges", 2035, ("pdp8", "_vn"), ("opt", "_vn_planrange")),
                     ("Plan ranges with the plan's lines", 2035, ("pdp8", "_vn"), ("pdp8", "_vn_prgrid")),
                     ("Plan ranges with the plan's lines", 2040, ("pdp8", "_vn"), ("pdp8", "_vn_prgrid")),
                     ("Plan storage with optimised siting", 2035, ("pdp8", "_vn"), ("pdp8", "_vn_storsite")),
                     ("Least cost within plan ranges", 2040, ("pdp8", "_vn"), ("opt", "_vn_planrange")),
                     ("Plan emission ceiling", 2035, ("pdp8", "_vn_co2plan"), ("opt", "_vn_co2plan")),
                     ("Plan emission ceiling", 2040, ("pdp8", "_vn_co2plan"), ("opt", "_vn_co2plan")),
                     ("High-demand plan variant", 2035, ("pdp8", "_vn_high"), ("opt", "_vn_high")),
                     ("High-demand plan variant", 2040, ("pdp8", "_vn_high"), ("opt", "_vn_high")),
                     ("Static capacity credits", 2035, ("pdp8", "_vn_static"), ("opt", "_vn_static"))]:
    p_, o_ = S(y, *a), S(y, *b)
    if p_ and o_:
        cp, co = p_["cost_bnUSD_per_year"]["total_excl_VOLL"], o_["cost_bnUSD_per_year"]["total_excl_VOLL"]
        k = o_["capacity_GW"]
        rows.append({"case": lab, "year": y, "pdp8_bnUSD": cp, "lc_bnUSD": co, "saving_bnUSD": cp - co,
                     "saving_pct": 100 * (1 - co / cp), "pdp8_co2": p_["co2_Mt"], "lc_co2": o_["co2_Mt"],
                     "lc_solar": k.get("solar", 0), "lc_battery": k.get("battery", 0), "lc_ocgt": k.get("OCGT", 0),
                     "lc_lng": k.get("LNG", 0), "lc_nuclear": k.get("nuclear", 0), "lc_offwind": k.get("offwind", 0),
                     "lc_onwind": k.get("onwind", 0), "lc_phs": k.get("PHS", 0)})
Rb = pd.DataFrame(rows)
if len(Rb):
    Rb.round(3).to_csv(OUT / "robust.csv", index=False)
print(Rb.round(2).to_string(index=False))
# implied credits, SNSP
rows = []
for y in [2035, 2040]:
    for s, lab in [("pdp8", "PDP8"), ("opt", "Least cost")]:
        d = S(y, s, "_vn")
        if d:
            ic = d["indicators"].get("implied_credit_top10", {})
            rows.append({"year": y, "system": lab, **{f"credit_{k}": v for k, v in ic.items()},
                         "snsp_max_pct": d["indicators"].get("snsp_max_pct"),
                         "net_peak_hour": d["indicators"].get("net_peak_snapshot_hour"),
                         "curtailment_pct": d["indicators"].get("curtailment_pct")})
if rows:
    pd.DataFrame(rows).round(3).to_csv(OUT / "credits.csv", index=False)
print(pd.DataFrame(rows).round(2).to_string(index=False))
# Monte Carlo (Latin hypercube, run_mc.py): gap per sample and standardised regression coefficients
fs = RES / "mc_samples.csv"
if fs.exists():
    SM_ = pd.read_csv(fs, index_col=0)
    rows = []
    for i, r in SM_.iterrows():
        p_, o_ = S(2035, "pdp8", f"_vn_mc{i}"), S(2035, "opt", f"_vn_mc{i}")
        if p_ and o_:
            cp, co = tot(p_), tot(o_)
            rows.append({"sample": i, **r.to_dict(), "pdp8_bnUSD": cp, "lc_bnUSD": co, "saving_bnUSD": cp - co,
                         "saving_pct": 100 * (1 - co / cp), "lc_co2": o_["co2_Mt"], "pdp8_co2": p_["co2_Mt"]})
    MC = pd.DataFrame(rows)
    if len(MC):
        MC.round(4).to_csv(OUT / "mc.csv", index=False)
        print(MC[["saving_bnUSD", "saving_pct"]].describe().round(2))
        if len(MC) >= 8:  # Spearman rank correlation of each input with the saving (robust for small samples)
            from scipy.stats import spearmanr
            rho = pd.Series({c: spearmanr(MC[c], MC.saving_bnUSD)[0] for c in SM_.columns}).sort_values(key=abs, ascending=False)
            pv = pd.Series({c: spearmanr(MC[c], MC.saving_bnUSD)[1] for c in SM_.columns})
            pd.DataFrame({"rho": rho, "p": pv.reindex(rho.index), "n": len(MC)}).round(3).to_csv(OUT / "mc_src.csv")
            print("Spearman rank correlations with the saving:\n", pd.DataFrame({"rho": rho, "p": pv.reindex(rho.index)}).round(2))
