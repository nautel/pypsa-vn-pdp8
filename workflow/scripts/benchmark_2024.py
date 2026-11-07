#!/usr/bin/env python3
"""Benchmark of the 30-region expansion model in 2024 dispatch mode.

Compares annual and monthly generation of the 30-region transport model (2024 fleet and demand, full year, 3-hourly;
model.py 2024 pdp8 with NO_RESERVE=1, HYDRO_TWH=88.76) with the nodal model and Ember 2024, without and with the
observed domestic-gas offtake imposed (GAS_QC=0.35). Also reports the flow on the corridors into the North.
Output: <FIG_DIR>/benchmark_2024.csv
Run: RES_DIR=.../results_v6 FIG_DIR=... python workflow/scripts/benchmark_2024.py
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
RES = Path(os.environ.get("RES_DIR", DATA / "expansion" / "results_v5"))
OUT = Path(os.environ.get("FIG_DIR", DATA / "figures" / "expansion_v5"))
OUT.mkdir(parents=True, exist_ok=True)
VAL = pd.read_csv(DATA / "figures" / "validation" / "validation_2024_monthly.csv", header=[0, 1], index_col=0, skiprows=[2])
VAL.index = VAL.index.astype(int)  # month 1..12
GRP = {"coal": "coal", "gas": "gas", "oil": "gas", "LNG": "gas", "OCGT": "gas", "hydro": "hydro", "onwind": "onwind",
       "solar": "solar+rooftop", "rooftop": "solar+rooftop", "imports": "other", "biomass": "other"}
cl = pd.read_csv(DATA / "expansion" / "clusters.csv", index_col=0)
NORTH = cl.index[cl.region == "Bắc"]
rows = []
for tag, lab in [("_bench", "30-region, economic dispatch"), ("_bench_gasqc", "30-region, observed gas offtake"),
                 ("_bench_hydmon", "30-region, gas offtake, monthly hydro budgets")]:
    f = RES / f"2024_pdp8{tag}.nc"
    if not f.exists():
        continue
    n = pypsa.Network(f)
    w = n.snapshot_weightings.generators
    g = n.generators_t.p.mul(w, axis=0)
    g = g.T.groupby(n.generators.carrier).sum().T
    s = n.storage_units_t.p.clip(lower=0).mul(w, axis=0).T.groupby(n.storage_units.carrier).sum().T
    allg = pd.concat([g, s], axis=1)
    allg = allg.T.groupby(allg.columns.map(lambda c: GRP.get(c, "drop"))).sum().T.drop(columns="drop", errors="ignore")
    mon = allg.groupby(allg.index.month).sum() / 1e6
    lk = n.links[(n.links.bus0.isin(NORTH) ^ n.links.bus1.isin(NORTH)) & (n.links.carrier == "AC")]
    sign = np.where(lk.bus1.isin(NORTH), 1.0, -1.0)
    flow = (n.links_t.p0[lk.index] * sign).sum(axis=1)
    for c in ["coal", "gas", "hydro", "onwind", "solar+rooftop", "other"]:
        mod_m = mon.get(c, pd.Series(0.0, index=range(1, 13)))
        emb_m = VAL[("ember", c)].astype(float)
        nod_m = VAL[("model", c)].astype(float)
        rows.append({"case": lab, "carrier": c, "model_TWh": float(mod_m.sum()), "nodal_TWh": float(nod_m.sum()),
                     "ember_TWh": float(emb_m.sum()), "diff_pct": 100 * (mod_m.sum() / emb_m.sum() - 1),
                     "monthly_corr": float(np.corrcoef(mod_m.reindex(range(1, 13)).fillna(0), emb_m)[0, 1])
                     if mod_m.std() > 0 else np.nan,
                     "north_import_max_GW": float(flow.max() / 1e3), "north_import_TWh": float((flow.clip(lower=0) * w).sum() / 1e6),
                     "shed_TWh": float(n.generators_t.p[n.generators.index[n.generators.carrier == "load shedding"]]
                                       .mul(w, axis=0).sum().sum() / 1e6)})
T = pd.DataFrame(rows)
T.round(3).to_csv(OUT / "benchmark_2024.csv", index=False)
print(T.round(2).to_string(index=False))
