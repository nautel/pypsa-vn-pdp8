#!/usr/bin/env python3
"""Capacity factors for NEW onshore wind (2030s turbines) per expansion region.
Method (replaces the energy multiplier factor_wind=1.46 for new builds):
 1. ERA5 100 m wind speed (Open-Meteo, D-17, cached in <DATA>/weather) is bias-corrected with ONE speed factor s so that
    the 2024 fleet (NREL 2020ATB 4 MW curve, 110 m hub, 12 % losses) reproduces Ember 2024 wind generation (12.7 TWh, D-08).
 2. New turbines: NREL 2020ATB 5.5 MW power curve (low specific power ~229 W/m2), hub 160 m — VN Technology Catalogue
    2026 (D-20): low-wind-speed onshore turbine hub 150 m (2025) -> 160 m (2030), specific power ~170 W/m2.
    Shear exponent 0.14, 12 % losses (wake + availability).
Outputs: <DATA>/expansion/cf_onwind_new.csv, cf_onwind_new.json (s, fleet check, mean CF / full-load hours by region)
Run: python expansion/onwind_new_cf.py
"""
import json
import os
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import logging  # noqa: E402

import atlite  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402
import yaml  # noqa: E402

logging.disable(logging.WARNING)
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[1] / "data"))
EXP, WX = DATA / "expansion", DATA / "weather"
EMBER_WIND_TWH = 12.7  # 2024 (D-08)
LOSS = 0.88


def curve(name):
    d = yaml.safe_load(open(Path(atlite.__file__).parent / "resources" / "windturbine" / name))
    return np.array(d["V"]), np.array(d["POW"]) / max(d["POW"])


V4, P4 = curve("NREL_ReferenceTurbine_2020ATB_4MW.yaml")
V55, P55 = curve("NREL_ReferenceTurbine_2020ATB_5.5MW.yaml")
cl = pd.read_csv(EXP / "clusters.csv", index_col=0)
ws = {}
for cid, r in cl.iterrows():
    fn = WX / f"openmeteo_era5_2024_{round(r.y, 3):.3f}_{round(r.x, 3):.3f}.json"
    h = json.loads(fn.read_text())["hourly"]
    ws[cid] = pd.Series(h["wind_speed_100m"], index=pd.to_datetime(h["time"]), dtype=float).fillna(0)
W = pd.DataFrame(ws)

base = pypsa.Network(DATA / "networks" / "vn2024_base.nc")
bm = pd.read_csv(EXP / "busmap.csv", index_col=0).cluster
g = base.generators[base.generators.carrier == "onwind"]
fleet = g.groupby(g.bus.map(bm)).p_nom.sum().reindex(W.columns, fill_value=0)


def fleet_twh(s):
    cf = np.interp(W.values * s * (110 / 100) ** 0.14, V4, P4) * LOSS
    return float((cf * fleet.values).sum() / 1e6)


lo, hi = 0.8, 2.5
for _ in range(60):
    mid = (lo + hi) / 2
    lo, hi = (mid, hi) if fleet_twh(mid) < EMBER_WIND_TWH else (lo, mid)
s = (lo + hi) / 2
cf_new = pd.DataFrame(np.interp(W.values * s * (160 / 100) ** 0.14, V55, P55) * LOSS, index=W.index, columns=W.columns)
cf_new.to_csv(EXP / "cf_onwind_new.csv")
flh = (cf_new.sum() * 8760 / len(cf_new)).round(0)
info = {"speed_factor_s": round(s, 4), "fleet_TWh_at_s": round(fleet_twh(s), 2), "ember_TWh": EMBER_WIND_TWH,
        "fleet_raw_TWh_s1": round(fleet_twh(1.0), 2), "mean_cf_new_all_regions": round(float(cf_new.values.mean()), 3),
        "full_load_hours_top5": flh.sort_values(ascending=False).head(5).to_dict(),
        "full_load_hours_median": float(flh.median()),
        "catalogue_reference_FLH": "3066-3504 (D-20, generic site)",
        "fleet_weighted_cf_new_turbine": round(float((cf_new.mean() * fleet).sum() / fleet.sum()), 3)}
(EXP / "cf_onwind_new.json").write_text(json.dumps(info, indent=1, ensure_ascii=False))
print(json.dumps(info, indent=1, ensure_ascii=False))
