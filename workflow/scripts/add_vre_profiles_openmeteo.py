#!/usr/bin/env python3
"""Wind / solar / rooftop p_max_pu for the VN 2024 nodal network from Open-Meteo ERA5 point data (D-17) at the 30
expansion-region centroids (stand-in until the full ERA5 cutout arrives; add_vre_profiles.py is the cutout version).

solar / rooftop: expansion/cf_{solar,rooftop}.csv x factor_solar (cf_calibration.json, Ember 2024 annual match)
onwind (2024 fleet): NREL 2020ATB 4 MW, 110 m hub, ERA5 speed x s (onwind_new_cf.json, Ember 2024 annual match)
=> annual VRE totals are calibrated to Ember 2024 by construction; the monthly/hourly shape is NOT -> validation target.
Each generator takes its region's profile (busmap). Output: <DATA>/networks/vre_p_max_pu_2024.csv (local time UTC+7)
Run: python workflow/scripts/add_vre_profiles_openmeteo.py
"""
import os
import json
from pathlib import Path

import atlite
import numpy as np
import pandas as pd
import pypsa
import yaml

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
EXP, NET, WX = DATA / "expansion", DATA / "networks", DATA / "weather"
cal = json.loads((EXP / "cf_calibration.json").read_text())
s = json.loads((EXP / "cf_onwind_new.json").read_text())["speed_factor_s"]
cl = pd.read_csv(EXP / "clusters.csv", index_col=0)
bm = pd.read_csv(EXP / "busmap.csv", index_col=0).cluster
d = yaml.safe_load(open(Path(atlite.__file__).parent / "resources" / "windturbine" / "NREL_ReferenceTurbine_2020ATB_4MW.yaml"))
V4, P4 = np.array(d["V"]), np.array(d["POW"]) / max(d["POW"])
ws = {}
for cid, r in cl.iterrows():
    h = json.loads((WX / f"openmeteo_era5_2024_{round(r.y, 3):.3f}_{round(r.x, 3):.3f}.json").read_text())["hourly"]
    ws[cid] = pd.Series(h["wind_speed_100m"], index=pd.to_datetime(h["time"]), dtype=float).fillna(0)
W = pd.DataFrame(ws)
prof = {"onwind": pd.DataFrame(np.interp(W.values * s * (110 / 100) ** 0.14, V4, P4) * 0.88, index=W.index, columns=W.columns),
        "solar": pd.read_csv(EXP / "cf_solar.csv", index_col=0, parse_dates=True) * cal["factor_solar"],
        "solar rooftop": pd.read_csv(EXP / "cf_rooftop.csv", index_col=0, parse_dates=True) * cal["factor_solar"]}
n = pypsa.Network(NET / "vn2024_base.nc")
vre = n.generators[n.generators.carrier.isin(prof)]
out = pd.DataFrame({g: prof[r.carrier][bm[r.bus]].values for g, r in vre.iterrows()}, index=W.index).clip(0, 1)
out = out.reindex(n.snapshots).ffill().fillna(0)
out.to_csv(NET / "vre_p_max_pu_2024.csv")
e = (out * vre.p_nom).sum().groupby(vre.carrier).sum() / 1e6
print("annual TWh (calibrated):", e.round(2).to_dict(), "| Ember 2024: wind 12.7, solar incl. rooftop 26.9")
