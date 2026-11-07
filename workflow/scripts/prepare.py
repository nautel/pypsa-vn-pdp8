#!/usr/bin/env python3
"""Step A of the expansion study: cluster the 2024 model to K regions, fetch ERA5 (via Open-Meteo archive API,
2024 hourly, local time) at cluster centroids + offshore points, build capacity-factor profiles, and check them
against Ember 2024 solar/wind generation at the 2024 fleet (-> bias-correction factors).

Outputs (<DATA>/expansion/): busmap.csv, clusters.csv, corridors.csv, cf_{solar,rooftop,onwind,offwind}.csv,
  cf_calibration.json
Run: python workflow/scripts/prepare.py [K=30]
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import logging  # noqa: E402

import atlite  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402
import yaml  # noqa: E402
from pypsa.clustering.spatial import busmap_by_kmeans  # noqa: E402

logging.disable(logging.WARNING)
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
OUT = DATA / "expansion"
WX = DATA / "weather"
OUT.mkdir(exist_ok=True)
WX.mkdir(exist_ok=True)
K = int(sys.argv[1]) if len(sys.argv) > 1 else 30

n = pypsa.Network(DATA / "networks" / "vn2024_base.nc")
b = n.buses
# --- spatial clustering: k-means on bus coordinates, weighted by peak load + installed capacity ---
w = pd.Series(1.0, index=b.index)
w = w.add(n.loads_t.p_set.max().groupby(n.loads.bus).sum(), fill_value=0)
gen = n.generators[n.generators.carrier != "load shedding"]
w = w.add(gen.groupby("bus").p_nom.sum(), fill_value=0).add(n.storage_units.groupby("bus").p_nom.sum(), fill_value=0)
busmap = busmap_by_kmeans(n, w.reindex(b.index).fillna(1.0), K, random_state=0, n_init=20)
busmap = "C" + busmap.astype(str).str.zfill(2)
busmap.rename("cluster").to_csv(OUT / "busmap.csv")
c = pd.DataFrame({"x": b.x, "y": b.y, "w": w, "cl": busmap})
cl = c.groupby("cl").apply(lambda d: pd.Series({"x": np.average(d.x, weights=d.w), "y": np.average(d.y, weights=d.w)}))
cl["region"] = np.where(cl.y > 17.9, "Bắc", np.where(cl.y > 11.5, "Trung", "Nam"))
# offshore point: 40 km seaward of the cluster centroid (east, or south-east for the Mekong) if the cluster is coastal
coast = gpd = None
import geopandas as gpd  # noqa: E402

vn = gpd.read_file(DATA / "shapes" / "gadm41_VNM_0.json").to_crs(32648)
land = vn.geometry.union_all()
pts = gpd.GeoSeries(gpd.points_from_xy(cl.x, cl.y), crs=4326).to_crs(32648)
dist_coast = [land.boundary.distance(p) / 1e3 for p in pts]
cl["coast_km"] = np.round(dist_coast, 1)
off = []
for p, y in zip(pts, cl.y):
    best = None
    for ang in [90, 120, 60, 150, 30, 180, 0]:  # prefer east, then SE/NE, S, N
        for dkm in range(20, 160, 10):
            q = p.__class__(p.x + dkm * 1e3 * np.cos(np.radians(90 - ang)), p.y + dkm * 1e3 * np.sin(np.radians(90 - ang)))
            if not land.contains(q) and land.distance(q) > 25e3:
                best = q
                break
        if best is not None:
            break
    off.append(best)
offg = gpd.GeoSeries(off, crs=32648).to_crs(4326)
cl["off_x"], cl["off_y"] = offg.x.values, offg.y.values
cl["offshore_ok"] = (cl.coast_km < 60) & cl.off_x.notna()  # coastal clusters with a sea point
cl.to_csv(OUT / "clusters.csv")

# --- corridors: existing 500/220 kV lines crossing cluster boundaries ---
v = n.lines.bus0.map(b.v_nom)
L = n.lines[v >= 220].assign(c0=lambda d: d.bus0.map(busmap), c1=lambda d: d.bus1.map(busmap))
L = L[L.c0 != L.c1]
key = np.where(L.c0 < L.c1, L.c0 + "|" + L.c1, L.c1 + "|" + L.c0)
cor = L.assign(key=key, mw=L.s_nom * L.s_max_pu.clip(upper=1), mw500=np.where(v[L.index] == 500, L.s_nom, 0)) \
    .groupby("key").agg(mw=("mw", "sum"), mw500=("mw500", "sum"), n_lines=("mw", "size"))
cor[["c0", "c1"]] = cor.index.to_series().str.split("|", expand=True).values
hav = lambda a, d: 111.2 * np.hypot((cl.x[a].values - cl.x[d].values) * np.cos(np.radians((cl.y[a].values + cl.y[d].values) / 2)), cl.y[a].values - cl.y[d].values)  # noqa: E731
cor["km"] = np.round(hav(cor.c0, cor.c1) * 1.2, 1)
cor.to_csv(OUT / "corridors.csv")
print(f"K={K}: corridors {len(cor)}, existing inter-cluster capacity {cor.mw.sum() / 1e3:.0f} GW")


# --- weather: Open-Meteo ERA5 archive (hourly 2024, Asia/Bangkok = UTC+7) ---
def fetch(lat, lon):
    fn = WX / f"openmeteo_era5_2024_{lat:.3f}_{lon:.3f}.json"
    if fn.exists():
        return json.loads(fn.read_text())
    url = ("https://archive-api.open-meteo.com/v1/archive?latitude=%.4f&longitude=%.4f&start_date=2024-01-01"
           "&end_date=2024-12-31&hourly=temperature_2m,shortwave_radiation,direct_normal_irradiance,diffuse_radiation,"
           "wind_speed_100m&wind_speed_unit=ms&timezone=Asia%%2FBangkok&models=era5") % (lat, lon)
    for k in range(5):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                d = json.loads(r.read())
            fn.write_text(json.dumps(d))
            time.sleep(1.0)
            return d
        except Exception as e:  # rate limit / transient
            print("retry", lat, lon, e)
            time.sleep(10 * (k + 1))
    raise RuntimeError(f"Open-Meteo failed for {lat},{lon}")


def frame(d):
    h = d["hourly"]
    return pd.DataFrame({k: h[k] for k in h if k != "time"}, index=pd.to_datetime(h["time"]))


def pv_cf(df, lat, lon, dcac):
    """fixed-tilt (tilt=|lat|, south) PV; isotropic sky; NOCT temperature; 14% losses; AC clipping at dcac."""
    t = df.index - pd.Timedelta(minutes=30)  # radiation = mean of preceding hour
    doy = t.dayofyear.values
    B = np.radians(360 / 365 * (doy - 81))
    eot = 9.87 * np.sin(2 * B) - 7.53 * np.cos(B) - 1.5 * np.sin(B)  # minutes
    dec = np.radians(23.45 * np.sin(np.radians(360 / 365 * (284 + doy))))
    solar_time = t.hour.values + t.minute.values / 60 + (4 * (lon - 105.0) + eot) / 60  # UTC+7 -> 105E meridian
    ha = np.radians(15 * (solar_time - 12))
    phi = np.radians(lat)
    cosz = np.clip(np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.cos(ha), -1, 1)
    z = np.arccos(cosz)
    az = np.arctan2(np.sin(ha), np.cos(ha) * np.sin(phi) - np.tan(dec) * np.cos(phi)) + np.pi  # 0=N, pi=S
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
prof = {k: {} for k in ["solar", "rooftop", "onwind", "offwind"]}
for cid, r in cl.iterrows():
    df = frame(fetch(round(r.y, 3), round(r.x, 3)))
    prof["solar"][cid] = pv_cf(df, r.y, r.x, dcac=1.25)
    prof["rooftop"][cid] = pv_cf(df, r.y, r.x, dcac=1.0)
    prof["onwind"][cid] = np.interp(df.wind_speed_100m.values * (110 / 100) ** 0.14, V4, P4) * 0.88
    if r.offshore_ok:
        do = frame(fetch(round(r.off_y, 3), round(r.off_x, 3)))
        prof["offwind"][cid] = np.interp(do.wind_speed_100m.values * (150 / 100) ** 0.11, V15, P15) * 0.90
idx = df.index
for k in prof:
    pd.DataFrame(prof[k], index=idx).to_csv(OUT / f"cf_{k}.csv")

# --- calibration vs Ember 2024 at the 2024 fleet ---
cap = gen.assign(cl=gen.bus.map(busmap)).groupby(["cl", "carrier"]).p_nom.sum().unstack(fill_value=0)
E = {}
for car, k in [("solar", "solar"), ("solar rooftop", "rooftop"), ("onwind", "onwind")]:
    cf = pd.DataFrame(prof[k], index=idx)
    E[car] = float((cf * cap[car].reindex(cf.columns).fillna(0)).sum().sum() / 1e6)
ember = {"solar_total": 26.9, "wind": 12.7}  # TWh 2024 (D-08)
f_solar = ember["solar_total"] / (E["solar"] + E["solar rooftop"])
f_wind = ember["wind"] / E["onwind"]
calib = {"model_TWh_raw": E, "ember_TWh": ember, "factor_solar": round(f_solar, 3), "factor_wind": round(f_wind, 3),
         "cf_raw": {k: round(float(pd.DataFrame(prof[k]).values.mean()), 3) for k in prof},
         "note": "Ember solar includes grid-metered rooftop; wind incl. nearshore. Factors applied as bias correction."}
(OUT / "cf_calibration.json").write_text(json.dumps(calib, indent=1, ensure_ascii=False))
print(json.dumps(calib, indent=1, ensure_ascii=False))
