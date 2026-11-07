#!/usr/bin/env python3
"""Sensitivity table (run_sens.sh): PDP8 vs least cost under LNG price, dry year, battery capacity credit.
Reads <DATA>/expansion/results/{year}_{pdp8,opt}{tag}_summary.json.
Output: <DATA>/figures/expansion/sensitivity.csv (+ printed table)
Run: python expansion/sensitivity_table.py
"""
import os
import json
from pathlib import Path

import pandas as pd

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[1] / "data"))
RES = Path(os.environ.get("RES_DIR", DATA / "expansion" / "results"))  # RES_DIR/FIG_DIR: e.g. results/v2 for older runs
OUT = Path(os.environ.get("FIG_DIR", DATA / "figures" / "expansion"))
CASES = {"_vn": "Base", "_vn_lnglow": "LNG 12 USD/MMBtu", "_vn_dry": "Dry year (hydro 80 TWh)",
         "_vn_batcr": "Battery credit 0.5"}
if os.environ.get("MODEL_V", "5") == "5":  # v5 sensitivity set
    CASES = {"_vn": "Base", "_vn_lnglow": "LNG 12 USD/MMBtu", "_vn_dry": "Dry year (hydro 80 TWh)",
             "_vn_rm115": "Reserve margin 15 %", "_vn_rm120": "Reserve margin 20 %",
             "_vn_nores": "No operating reserve / SNSP limit", "_vn_conn": "PV and wind connection +100 USD/kW",
             "_vn_corr": "Corridor limits 50 % of thermal rating", "_vn_wacc10": "Discount rate 10 %",
             "_vn_bat150": "Battery cost +50 %", "_vn_off70": "Offshore wind cost -30 %",
             "_vn_nuc150": "Nuclear cost +50 %", "_vn_phs150": "Pumped hydro cost +50 %",
             "_vn_pv55": "PV build rate 5.5 GW/a", "_vn_batbuild": "Battery build rate 3 GW/a",
             "_vn_high": "High-demand plan variant", "_vn_co2plan": "Plan emission ceiling",
             "_vn_static": "Static capacity credits", "_vn_line2": "AC line cost x2 (circuit-3 benchmark)",
             "_vn_commit25": "Committed LNG: Nhon Trach 3&4 only", "_vn_hydfree": "Hydro without monthly budgets"}
OPT_ONLY = {"_vn_pv55", "_vn_batbuild"}  # the plan is unaffected: compare with the PDP8 base run


def load(y, s, t):
    f = RES / f"{y}_{s}{t}_summary.json"
    return json.loads(f.read_text()) if f.exists() else None


rows = []
for y in [2035, 2040]:
    for t, lab in CASES.items():
        p, o = load(y, "pdp8", "_vn" if t in OPT_ONLY else t), load(y, "opt", t)
        if not (p and o):
            continue
        cp, co = p["cost_bnUSD_per_year"]["total_excl_VOLL"], o["cost_bnUSD_per_year"]["total_excl_VOLL"]
        k = {c: o["capacity_GW"].get(c, 0.0) for c in ["solar", "onwind", "battery", "LNG", "OCGT", "offwind", "nuclear"]}
        rows.append({"year": y, "case": lab, "pdp8_bnUSD": cp, "opt_bnUSD": co, "saving_bnUSD": cp - co,
                     "saving_pct": 100 * (1 - co / cp), "pdp8_co2_Mt": p["co2_Mt"], "opt_co2_Mt": o["co2_Mt"],
                     "opt_shed_TWh": o["load_shedding_TWh"], "opt_solar_GW": k["solar"], "opt_onwind_GW": k["onwind"],
                     "opt_battery_GW": k["battery"], "opt_gas_new_GW": k["LNG"] + k["OCGT"],
                     "opt_coal_TWh": o["energy_TWh"]["coal"], "opt_invest_bnUSD": sum(o["overnight_investment_new_bnUSD"].values()),
                     "pdp8_invest_bnUSD": sum(p["overnight_investment_new_bnUSD"].values())})
for y in [2035, 2040]:
    z = load(y, "opt", "_vn_co2zero_nolim")
    if z:
        c = z["cost_bnUSD_per_year"]
        rows.append({"year": y, "case": "Zero CO2, no build-rate limit", "opt_bnUSD": c["total_excl_VOLL"],
                     "opt_co2_Mt": z["co2_Mt"], "opt_shed_TWh": z["load_shedding_TWh"],
                     "opt_solar_GW": z["capacity_GW"]["solar"], "opt_onwind_GW": z["capacity_GW"]["onwind"],
                     "opt_battery_GW": z["capacity_GW"]["battery"],
                     "opt_invest_bnUSD": sum(z["overnight_investment_new_bnUSD"].values())})
T = pd.DataFrame(rows)
OUT.mkdir(parents=True, exist_ok=True)
T.round(3).to_csv(OUT / "sensitivity.csv", index=False)
print(T.round(2).to_string(index=False))
