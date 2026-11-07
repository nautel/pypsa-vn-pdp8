#!/usr/bin/env python3
"""Minimum hourly operating margin of the fixed 2035 portfolios over weather years.

For every fixed-portfolio dispatch run (2035_{pdp8,opt}_vn_fix_w<year>[d]), the spare capacity in each 3-hourly step is
    headroom_t = sum_thermal (available_t - dispatch_t) + sum_storage min(p_nom - net_output_t, SOC_t / 3 h)
(available thermal capacity includes the drawn forced outages; storage headroom is limited by its stored energy), and
the margin is headroom_t / demand_t. Reported: minimum and 1st percentile over the year, per portfolio and run.
Output: <FIG_DIR>/adequacy_margin.csv
Run: RES_DIR=.../results_v6 FIG_DIR=... python workflow/scripts/adequacy_margin.py
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
RES = Path(os.environ.get("RES_DIR", DATA / "expansion" / "results_v6"))
OUT = Path(os.environ.get("FIG_DIR", DATA / "figures" / "expansion_v6"))
OUT.mkdir(parents=True, exist_ok=True)
THERM = ["coal", "gas", "LNG", "OCGT", "oil", "nuclear", "biomass", "imports"]
rows = []
for s, lab in [("pdp8", "PDP8"), ("opt", "Least cost")]:
    for f in sorted(RES.glob(f"2035_{s}_vn_fix_w*.nc")):
        tag = f.stem.split("_fix_w")[1]
        n = pypsa.Network(f)
        g = n.generators[n.generators.carrier.isin(THERM)]
        pmax = n.generators_t.p_max_pu.reindex(columns=g.index)
        pmax = pmax.fillna(pd.Series(g.p_max_pu, index=g.index))
        avail = pmax * g.p_nom
        th = (avail - n.generators_t.p[g.index]).clip(lower=0).sum(axis=1)
        su = n.storage_units
        net = n.storage_units_t.p.reindex(columns=su.index).fillna(0)
        soc = n.storage_units_t.state_of_charge.reindex(columns=su.index).fillna(0)
        st = np.minimum((su.p_nom - net).clip(lower=0), soc / 3.0).sum(axis=1)
        ld = n.loads_t.p_set.sum(axis=1)
        m = (th + st) / ld
        rows.append({"portfolio": lab, "weather_year": int(tag[:4]), "hydro": "dry" if tag.endswith("d") else "normal",
                     "min_margin_pct": 100 * float(m.min()), "p1_margin_pct": 100 * float(m.quantile(0.01)),
                     "min_thermal_headroom_GW": float(th.min() / 1e3)})
T = pd.DataFrame(rows)
T.round(2).to_csv(OUT / "adequacy_margin.csv", index=False)
print(T.groupby(["portfolio", "hydro"])[["min_margin_pct", "p1_margin_pct"]].agg(["min", "mean"]).round(1))
