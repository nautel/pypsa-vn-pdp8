#!/usr/bin/env python3
"""Dispatch (DC-OPF / linear) of the VN 2024 network over a period.

Run (env pypsa-earth):
  python solve_vn.py 2024-05-06 2024-05-12            # needs <DATA>/networks/vre_p_max_pu_2024.csv (from ERA5)
  python solve_vn.py 2024-05-06 2024-05-12 --placeholder   # crude VRE shapes, ONLY to test grid/solver
Output: <DATA>/networks/solved/vn2024_<start>_<end>[_placeholder].nc + printed summary
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[0] / "data"))
NET = DATA / "networks"
start, end = sys.argv[1], sys.argv[2]
placeholder = "--placeholder" in sys.argv

n = pypsa.Network(NET / "vn2024_base.nc")
n.set_snapshots(n.snapshots[(n.snapshots >= start) & (n.snapshots < pd.Timestamp(end) + pd.Timedelta("1D"))])
for c in ["Line", "Transformer"]:  # elements commissioned after the period start (build_vn_network.py ADD_*) -> off
    df = n.static(c)
    if "commissioned" in df:
        late = df.index[pd.to_datetime(df.commissioned.replace("", None), errors="coerce") > pd.Timestamp(start)]
        if len(late):
            n.remove(c, late)
            print(f"{c}: not yet commissioned, removed {list(late)}")
vre = n.generators.index[n.generators.carrier.isin(["onwind", "solar", "solar rooftop"])]
fn = NET / "vre_p_max_pu_2024.csv"
if placeholder:
    h = n.snapshots.hour
    sol = pd.Series(np.clip(np.sin((h - 6) / 12 * np.pi), 0, None) * 0.75, index=n.snapshots)
    prof = {"onwind": pd.Series(0.25, index=n.snapshots), "solar": sol, "solar rooftop": sol * 0.85}
    n.generators_t.p_max_pu[vre] = pd.DataFrame({g: prof[n.generators.at[g, "carrier"]] for g in vre})
elif fn.exists():
    pm = pd.read_csv(fn, index_col=0, parse_dates=True).reindex(n.snapshots)
    n.generators_t.p_max_pu[vre] = pm[vre]
else:
    sys.exit(f"missing {fn}; run add_vre_profiles.py after the ERA5 cutout, or use --placeholder")

out = NET / "solved"
out.mkdir(exist_ok=True)
status, cond = n.optimize(solver_name="highs", solver_options={
    "solver": "ipm", "run_crossover": "off", "threads": int(os.environ.get("THREADS", 8)), "log_to_console": False,
    "log_file": str(out / f"highs_{start}_{end}.log")})
print("status:", status, cond, "objective", round(n.objective / 1e6, 2), "MUSD")
gen = n.generators_t.p.T.groupby(n.generators.carrier).sum().sum(axis=1) / 1e3
sto = n.storage_units_t.p.T.groupby(n.storage_units.carrier).sum().sum(axis=1) / 1e3
print("energy GWh:", pd.concat([gen, sto]).round(1).to_dict())
print("load GWh:", round(n.loads_t.p_set.sum().sum() / 1e3, 1))
ld = n.lines_t.p0.abs() / (n.lines.s_nom * n.lines.s_max_pu)
for v in [500, 220, 110]:
    li = n.lines.index[n.buses.loc[n.lines.bus0, "v_nom"].values == v]
    print(f"{v} kV: max loading {ld[li].max().max():.2f}, lines congested (>=99%) at least once: "
          f"{(ld[li].max() >= 0.99).sum()}/{len(li)}")
tl = n.transformers_t.p0.abs() / n.transformers.s_nom
print(f"trafos congested: {(tl.max() >= 0.99).sum()}/{len(tl.columns)}")
shed = n.generators_t.p[n.generators.index[n.generators.carrier == "load shedding"]].sum()
print("load shedding GWh:", round(shed.sum() / 1e3, 2), "top buses:", (shed[shed > 0].sort_values()[-5:] / 1e3).round(2).to_dict())
n.export_to_netcdf(out / f"vn2024_{start}_{end}{'_placeholder' if placeholder else ''}.nc")
