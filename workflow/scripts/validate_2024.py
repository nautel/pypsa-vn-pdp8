#!/usr/bin/env python3
"""Full-year 2024 validation of the nodal model (2,175 buses, DC-OPF) against Ember 2024 monthly generation (D-08).
Combines the solved weekly chunks from solve_vn.py (<DATA>/networks/solved/vn2024_2024-MM-DD_2024-MM-DD.nc,
run_validation_2024.sh), aggregated by snapshot month.
Outputs: <DATA>/figures/validation/validation_2024_{monthly.csv,annual.csv,monthly.png}
Run: python workflow/scripts/validate_2024.py
"""
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plot_vn import INK, SLOTS, ember_monthly, model_monthly, save, vnum  # noqa: E402

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
OUT = DATA / "figures" / "validation"
OUT.mkdir(parents=True, exist_ok=True)
SOL = DATA / "networks" / "solved"
parts, shed, hits, hrs = [], [], {}, []  # hits: (month, kV) -> lines at >=99 % for >=1 h
files = sorted(f for f in SOL.glob("vn2024_2024-??-??_2024-??-??.nc"))  # weekly chunks (run_validation_2024.sh)
for fn in files:
    n = pypsa.Network(fn)
    P, _ = model_monthly(n)
    parts.append(P)
    hrs.append(pd.Series(1, index=n.snapshots))
    g = n.generators.index[n.generators.carrier == "load shedding"]
    shed.append(n.generators_t.p[g].sum(axis=1).groupby(n.snapshots.month).sum() / 1e6)
    ld = n.lines_t.p0.abs().div(n.lines.s_nom * n.lines.s_max_pu.clip(upper=1), axis=1)
    hit = (ld >= 0.99).groupby(n.snapshots.month).any()
    v = n.lines.bus0.map(n.buses.v_nom).reindex(hit.columns).values
    for m, row in hit.iterrows():
        for kv in [500, 220]:
            hits.setdefault((m, kv), set()).update(row.index[(v == kv) & row.values])
H = pd.concat(hrs)
assert H.index.is_unique, "overlapping chunks"
print(f"{len(files)} chunks, {len(H)} of 8784 hours")
shed = pd.concat(shed).groupby(level=0).sum().to_dict()
maxload = {m: {kv: len(hits.get((m, kv), ())) for kv in [500, 220]} for m in sorted({m for m, _ in hits})}
M = pd.concat(parts).groupby(level=0).sum()
E = ember_monthly().reindex(M.index)
cols = [c for c in ["coal", "gas", "hydro", "onwind", "solar+rooftop", "other"] if c in M.columns and c in E.columns]
T = pd.concat({"model": M[cols], "ember": E[cols]}, axis=1).round(2)
T["shed_TWh"] = pd.Series(shed)
T.to_csv(OUT / "validation_2024_monthly.csv")
A = pd.DataFrame({"model_TWh": M[cols].sum(), "ember_TWh": E[cols].sum()})
A["diff_pct"] = (100 * (A.model_TWh / A.ember_TWh - 1)).round(1)
A["monthly_corr"] = [float(np.corrcoef(M[c], E[c])[0, 1]) for c in cols]
A["monthly_MAPE_pct"] = [float((100 * (M[c] - E[c]).abs() / E[c]).mean()) for c in cols]
A.round(3).to_csv(OUT / "validation_2024_annual.csv")
print(A.round(2).to_string(), "\nunserved TWh by month:", {k: round(v, 3) for k, v in shed.items()},
      "\nlines at limit (>=1 h) by month:", maxload)

LAB = {"coal": "Coal", "gas": "Gas + oil", "hydro": "Hydro", "onwind": "Wind", "solar+rooftop": "Solar (incl. rooftop)",
       "other": "Imports + biomass"}
fig, axs = plt.subplots(2, 3, figsize=(13, 7.0), sharex=True)
for ax, c in zip(axs.flat, cols):
    ax.plot(M.index, E[c], color=INK, lw=2, marker="o", ms=4, label="Ember 2024")
    ax.plot(M.index, M[c], color=SLOTS[0], lw=2, marker="s", ms=4, label="Model")
    ax.set_title(f"{LAB[c]}\nannual {vnum(A.model_TWh[c], 1)} vs {vnum(A.ember_TWh[c], 1)} TWh ({A.diff_pct[c]:+.1f}%)",
                 loc="left", fontsize=9)
    ax.grid(axis="y")
    ax.set_xticks(range(1, 13))
axs[0][0].legend(fontsize=9, frameon=False)
for ax in axs[:, 0]:
    ax.set_ylabel("TWh / month")
fig.text(0.01, -0.02, "Nodal DC-OPF of the 2024 network (2,175 buses, 500/220/110 kV), hourly, solved in 48 windows of 6-8 days.\n"
         "Calibrated: annual wind/solar totals, national monthly hydro budgets, monthly imports. Not calibrated: coal/gas split, "
         "regional hydro, network flows.",
         fontsize=8.5, color=INK)
save(fig, OUT, "validation_2024_monthly")
