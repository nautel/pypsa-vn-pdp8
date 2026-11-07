#!/usr/bin/env python3
"""Wind / solar / rooftop p_max_pu for the VN 2024 network from the ERA5 2024 cutout (atlite).

Per plant: capacity factor of the nearest ERA5 cell; per bus generator: capacity-weighted mean.
ERA5 is UTC -> shifted to local time (UTC+7, network snapshots); first 7 local hours wrap from year end.
Inputs : <DATA>/cutouts/vietnam-2024-era5.nc, <DATA>/networks/{vn2024_base.nc, plants_mapped.csv}
Output : <DATA>/networks/vre_p_max_pu_2024.csv (+ printed annual CF / energy vs Ember 2024)
Run (env pypsa-earth): python add_vre_profiles.py
"""
import os
from pathlib import Path

import atlite
import numpy as np
import pandas as pd
import pypsa

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[0] / "data"))
NET = DATA / "networks"
TZ_H = 7
EMBER_TWH = {"onwind": 12.7, "solar+rooftop": 26.9}  # Ember 2024 (validation only, not used for scaling)
# ASSUMPTIONS: farm PV fixed-tilt latitude-optimal south-facing; rooftop same CF x 0.85 (orientation/soiling);
# wind: atlite 'Vestas_V112_3MW' at its default hub height (VN fleet: 2-4.5 MW turbines)
TURBINE, ROOFTOP_DERATE = "Vestas_V112_3MW", 0.85

cutout = atlite.Cutout(DATA / "cutouts" / "vietnam-2024-era5.nc")
n = pypsa.Network(NET / "vn2024_base.nc")
p = pd.read_csv(NET / "plants_mapped.csv")
p = p[p.carrier.isin(["onwind", "solar", "solar rooftop"])]

cf = {"solar": cutout.pv(panel="CSi", orientation="latitude_optimal", capacity_factor_timeseries=True),
      "onwind": cutout.wind(turbine=TURBINE, capacity_factor_timeseries=True)}
cf["solar rooftop"] = cf["solar"] * ROOFTOP_DERATE


def at_points(da, lon, lat):
    xs, ys = da.x.values, da.y.values
    ix = np.abs(xs[None, :] - np.asarray(lon)[:, None]).argmin(1)
    iy = np.abs(ys[None, :] - np.asarray(lat)[:, None]).argmin(1)
    v = da.transpose("time", "y", "x").values[:, iy, ix]  # time x plants
    t = pd.DatetimeIndex(da.time.values) + pd.Timedelta(hours=TZ_H)
    df = pd.DataFrame(v, index=t)
    df = pd.concat([df.iloc[-TZ_H:].set_axis(df.index[:TZ_H] - pd.Timedelta(hours=TZ_H)), df.iloc[:-TZ_H]])
    return df.set_axis(n.snapshots[: len(df)]) if len(df) == len(n.snapshots) else df.reindex(n.snapshots)


out = {}
for car, g in p.groupby("carrier"):
    prof = at_points(cf[car], g.lon.values, g.lat.values)
    prof.columns = g.index
    for bus, gb in g.groupby("bus"):
        out[f"{bus} {car}"] = (prof[gb.index] * gb.p_nom.values).sum(axis=1) / gb.p_nom.sum()
pm = pd.DataFrame(out).clip(0, 1).fillna(0)
missing = set(n.generators.index[n.generators.carrier.isin(cf)]) - set(pm.columns)
assert not missing, f"generators without profile: {list(missing)[:5]}"
pm.to_csv(NET / "vre_p_max_pu_2024.csv")

gen = n.generators.loc[pm.columns]
E = (pm * gen.p_nom).sum().groupby(gen.carrier).sum() / 1e6
capc = gen.groupby("carrier").p_nom.sum()
print("annual CF:", (E * 1e6 / capc / len(pm)).round(3).to_dict())
print("potential TWh (before curtailment):", E.round(2).to_dict(),
      "| Ember 2024:", EMBER_TWH, "| solar+rooftop model:", round(E.get("solar", 0) + E.get("solar rooftop", 0), 2))
print("->", NET / "vre_p_max_pu_2024.csv")
