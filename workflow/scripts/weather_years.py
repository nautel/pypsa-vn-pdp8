#!/usr/bin/env python3
"""Multi-year weather for adequacy and regret tests of fixed portfolios.

1. Fetch hourly ERA5 (Open-Meteo Historical API, models=era5; D-25) 2015-2023 at the 30 region centroids (same points
   and variables as the 2024 files of prepare.py, D-17). Raw JSON -> <DATA>/weather/openmeteo_multiyear/ (untrusted
   download directory, read with python -I).
2. Point capacity factors with the conversions of prepare.py (fixed-tilt PV, NREL 2020ATB 4 MW onshore, 15 MW
   offshore), calibrated per region and profile to the model's 2024 profiles. PV: energy factor
       CF_y,r(t) = clip(CFpoint_y,r(t) * mean(CFmodel_2024,r) / mean(CFpoint_2024,r), 0, 1)
   Wind: a wind-speed factor s_r (bisection) such that mean(curve(s_r * v_2024,r)) = mean(CFmodel_2024,r); then
       CF_y,r(t) = curve(s_r * v_y,r(t))   (a multiplicative CF factor would be clipped at 1 and lose energy)
   so that every weather year keeps the model's resource level (GIS eligibility, GWA downscaling, Ember calibration)
   while hourly, daily and seasonal variability, including low-wind/low-sun spells, comes from that year's ERA5.
   Offshore wind uses the centroid wind of the coastal region (2024: centroid vs offshore point, scaled likewise).
3. Output <DATA>/expansion/weather_years/cf_<profile>_<year>.csv on the 2024 hourly index (non-leap years: 29 Feb =
   28 Feb). model.py reads them with WEATHER_YEAR=<year>.
Run: python -I workflow/scripts/weather_years.py [fetch|build]
"""
import os
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import atlite
import numpy as np
import pandas as pd
import yaml

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
EXP, WX = DATA / "expansion", DATA / "weather"
RAW = WX / "openmeteo_multiyear"
OUT = EXP / "weather_years"
Y0, Y1 = 2015, 2023
VARS = "temperature_2m,shortwave_radiation,direct_normal_irradiance,diffuse_radiation,wind_speed_100m"
cl = pd.read_csv(EXP / "clusters.csv", index_col=0)


def fetch(lat, lon):
    RAW.mkdir(parents=True, exist_ok=True)
    fn = RAW / f"openmeteo_era5_{Y0}_{Y1}_{lat:.3f}_{lon:.3f}.json"
    if fn.exists():
        return fn
    url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={lat:.4f}&longitude={lon:.4f}"
           f"&start_date={Y0}-01-01&end_date={Y1}-12-31&hourly={VARS}&wind_speed_unit=ms"
           f"&timezone=Asia%2FBangkok&models=era5")
    for k in range(10):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pypsa-vn-research/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r:
                fn.write_bytes(r.read())
            time.sleep(2.0)
            return fn
        except urllib.error.HTTPError as e:
            wait = 900 if e.code == 429 else 30 * (k + 1)  # 429: hourly/daily request weight exhausted
            print("HTTP", e.code, lat, lon, "-> wait", wait, "s", flush=True)
            time.sleep(wait)
        except Exception as e:  # transient
            print("retry", lat, lon, e, flush=True)
            time.sleep(30 * (k + 1))
    raise RuntimeError(f"Open-Meteo failed for {lat},{lon}")


def frame(path):
    h = json.loads(Path(path).read_text())["hourly"]
    return pd.DataFrame({k: h[k] for k in h if k != "time"}, index=pd.to_datetime(h["time"])).astype(float).fillna(0)


def pv_cf(df, lat, lon, dcac):  # identical to prepare.py
    t = df.index - pd.Timedelta(minutes=30)
    doy = t.dayofyear.values
    B = np.radians(360 / 365 * (doy - 81))
    eot = 9.87 * np.sin(2 * B) - 7.53 * np.cos(B) - 1.5 * np.sin(B)
    dec = np.radians(23.45 * np.sin(np.radians(360 / 365 * (284 + doy))))
    solar_time = t.hour.values + t.minute.values / 60 + (4 * (lon - 105.0) + eot) / 60
    ha = np.radians(15 * (solar_time - 12))
    phi = np.radians(lat)
    cosz = np.clip(np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.cos(ha), -1, 1)
    z = np.arccos(cosz)
    az = np.arctan2(np.sin(ha), np.cos(ha) * np.sin(phi) - np.tan(dec) * np.cos(phi)) + np.pi
    beta = np.radians(abs(lat))
    cos_aoi = np.cos(z) * np.cos(beta) + np.sin(z) * np.sin(beta) * np.cos(az - np.pi)
    ghi, dni, dhi = df.shortwave_radiation.values, df.direct_normal_irradiance.values, df.diffuse_radiation.values
    poa = dni * np.clip(cos_aoi, 0, None) * (cosz > 0.01) + dhi * (1 + np.cos(beta)) / 2 + ghi * 0.2 * (1 - np.cos(beta)) / 2
    tc = df.temperature_2m.values + poa / 800 * 25
    dc = poa / 1000 * (1 - 0.004 * (tc - 25)) * 0.86
    return np.clip(dc * dcac, 0, 1)


def curve(name):
    d = yaml.safe_load(open(Path(atlite.__file__).parent / "resources" / "windturbine" / name))
    return np.array(d["V"]), np.array(d["POW"]) / max(d["POW"])


V4, P4 = curve("NREL_ReferenceTurbine_2020ATB_4MW.yaml")
V15, P15 = curve("NREL_ReferenceTurbine_2020ATB_15MW_offshore.yaml")


def wind_cf(v, kind):
    return (np.interp(v * (110 / 100) ** 0.14, V4, P4) * 0.88 if kind == "on"
            else np.interp(v * (150 / 100) ** 0.11, V15, P15) * 0.90)


def speed_factor(v24, target, kind):
    lo, hi = 0.2, 5.0
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if wind_cf(v24 * mid, kind).mean() < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def point_cf(df, lat, lon):
    return {"pv125": pv_cf(df, lat, lon, 1.25), "pv100": pv_cf(df, lat, lon, 1.0),
            "on": np.interp(df.wind_speed_100m.values * (110 / 100) ** 0.14, V4, P4) * 0.88,
            "off": np.interp(df.wind_speed_100m.values * (150 / 100) ** 0.11, V15, P15) * 0.90}


def to2024(a, idx_y):
    """hourly values of one year on the 2024 (leap-year) index; non-leap years repeat 28 Feb as 29 Feb."""
    vals = np.asarray(a, dtype=float)
    if len(vals) == 8760:
        i = (31 + 28) * 24
        vals = np.r_[vals[:i], vals[i - 24:i], vals[i:]]
    return vals[:8784]


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    if mode == "fetch":
        for cid, r in cl.iterrows():
            print(cid, fetch(round(r.y, 3), round(r.x, 3)).name, flush=True)
        sys.exit(0)
    OUT.mkdir(parents=True, exist_ok=True)
    GISD = EXP / "gis"
    calib = json.loads((EXP / "cf_calibration.json").read_text())
    rd = lambda k: pd.read_csv(GISD / f"cf_{k}.csv", index_col=0, parse_dates=True).reindex(columns=cl.index)  # noqa: E731
    model = {"solar": (rd("solar"), "pv125"), "solar_exist": (rd("solar_exist"), "pv125"), "onwind": (rd("onwind"), "on"),
             "rooftop": (pd.read_csv(EXP / "cf_rooftop.csv", index_col=0, parse_dates=True).reindex(columns=cl.index)
                         * calib["factor_solar"], "pv100"),
             "offwind": (pd.read_csv(EXP / "cf_offwind.csv", index_col=0, parse_dates=True), "off")}
    for p_ in sorted(GISD.glob("cf_onwind_new_w*.csv")):
        model[p_.stem.replace("cf_", "")] = (rd(p_.stem.replace("cf_", "")), "on")
    idx24 = model["solar"][0].index
    pts24, ptsy = {}, {}
    for cid, r in cl.iterrows():
        f24 = WX / f"openmeteo_era5_2024_{round(r.y, 3):.3f}_{round(r.x, 3):.3f}.json"
        pts24[cid] = point_cf(frame(f24), r.y, r.x)
        ptsy[cid] = (frame(RAW / f"openmeteo_era5_{Y0}_{Y1}_{round(r.y, 3):.3f}_{round(r.x, 3):.3f}.json"), r.y, r.x)
    stats, SF = [], {}
    V24 = {cid: frame(WX / f"openmeteo_era5_2024_{round(r.y, 3):.3f}_{round(r.x, 3):.3f}.json").wind_speed_100m.values
           for cid, r in cl.iterrows()}
    for y in range(Y0, Y1 + 1):
        for name, (prof24, kind) in model.items():
            out = pd.DataFrame(0.0, index=idx24, columns=prof24.columns)
            for cid in prof24.columns:
                if cid not in ptsy or prof24[cid].mean() <= 0:
                    continue
                df, lat, lon = ptsy[cid]
                dfy = df[df.index.year == y]
                if kind in ("on", "off"):
                    key = (cid, name)
                    if key not in SF:
                        SF[key] = speed_factor(V24[cid], prof24[cid].mean(), kind)
                    out[cid] = to2024(wind_cf(dfy.wind_speed_100m.values * SF[key], kind), dfy.index)
                else:
                    k = prof24[cid].mean() / max(pts24[cid][kind].mean(), 1e-6)
                    out[cid] = np.clip(to2024(point_cf(dfy, lat, lon)[kind], dfy.index) * k, 0, 1)
            out.round(4).to_csv(OUT / f"cf_{name}_{y}.csv")
            stats.append({"year": y, "profile": name, "mean_cf": float(out[[c for c in out if prof24[c].mean() > 0]].mean().mean())})
        print(y, "done", flush=True)
    pd.DataFrame(stats).pivot(index="profile", columns="year", values="mean_cf").round(3).to_csv(OUT / "mean_cf_by_year.csv")
    print(pd.read_csv(OUT / "mean_cf_by_year.csv", index_col=0))
