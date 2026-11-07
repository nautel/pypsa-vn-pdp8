#!/usr/bin/env python3
"""GIS-based VRE potentials and capacity-factor profiles per expansion region (PyPSA-ZA / PyPSA-Eur style; D-21..D-23).

Regions: GADM level-2 districts assigned to the nearest cluster centroid (same rule as model.py).
Land eligibility (atlite ExclusionContainer, UTM 48N, 100 m):
  solar  : ESA WorldCover 2021 classes shrubland 20, grassland 30, cropland 40, bare/sparse 60 only; slope <= SLOPE_PV;
           outside WDPA (designated, terrestrial/coastal)
  onwind : same land classes (tree cover, built-up, water, wetland, mangrove excluded); slope <= SLOPE_WIND;
           >= 500 m from built-up; outside WDPA; and only ERA5 cells whose bias-corrected new-turbine CF >= CF_MIN_WIND
Potentials: national technical potentials of Decision 768/QD-TTg (ground PV 837 GW, onshore wind 221 GW) distributed
  over regions in proportion to eligible area (the GIS sets the regional split, the official figure the total).
Profiles (ERA5 2024 cutout, UTC -> local UTC+7, eligible-area-weighted mean over cells of each region):
  solar      : atlite pv (CSi, latitude-optimal) x f, f such that the 2024 solar-farm fleet (plants_mapped.csv, cell CF)
               produces the v2 calibrated farm energy (Ember 2024 solar minus rooftop)
  onwind     : 2024-fleet turbine (NREL 2020ATB 4 MW, 110 m), ERA5 100 m speed x s, shear 0.14, 12 % losses; s such
               that the fleet at its cells produces Ember 2024 wind (12.7 TWh)
  onwind_new : NREL 2020ATB 5.5 MW, 160 m hub, same s (VN Technology Catalogue 2026 low-wind turbine)
Outputs: <DATA>/expansion/gis/{cf_solar,cf_onwind,cf_onwind_new}.csv (calibrated), potentials.csv, calib.json,
         <DATA>/figures/expansion/vre_potentials_gis.png
Run: python workflow/scripts/vre_gis.py
"""
import json
import os
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import logging  # noqa: E402

import atlite  # noqa: E402
import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
import rasterio  # noqa: E402
from atlite.gis import ExclusionContainer, shape_availability  # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from rasterio.warp import Resampling, reproject  # noqa: E402

logging.disable(logging.WARNING)
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
EXP, GIS = DATA / "expansion", DATA / "gis"
OUT = EXP / "gis"
OUT.mkdir(exist_ok=True)
FIG = DATA / "figures" / "expansion"
TZ_H = 7
SLOPE_PV, SLOPE_WIND = 10, 20  # deg, ASSUMPTION (typical utility-PV / onshore-wind siting limits, cf. Ryberg et al. 2018)
CLASSES = {"w1": (0.30, 1.01), "w2": (0.20, 0.30), "w3": (0.0, 0.20)}  # onwind resource classes: cell mean new-turbine CF
POT = {"solar": 837e3, "onwind": 221e3}  # MW, Decision 768/QD-TTg technical potentials
LAND_OK = [20, 30, 40, 60]
# cropland (WorldCover 40) for utility PV (S21): all | nodelta (excluded in the Red River and Mekong deltas, where
# cropland is mostly two-/three-crop paddy protected by Land Law 2024 Art. 182 / Resolution 39/2021 3.5 Mha target)
# | none (no cropland anywhere). Wind keeps cropland in all cases (turbines use ~2-5 % of the land).
CROP_RULE = os.environ.get("CROP_RULE", "nodelta")
DELTAS = ["HàNội", "HảiPhòng", "HảiDương", "HưngYên", "TháiBình", "NamĐịnh", "NinhBình", "HàNam", "BắcNinh", "VĩnhPhúc",
          "LongAn", "TiềnGiang", "BếnTre", "TràVinh", "VĩnhLong", "ĐồngTháp", "AnGiang", "KiênGiang", "CầnThơ",
          "HậuGiang", "SócTrăng", "BạcLiêu", "CàMau"]
EMBER_WIND_TWH = 12.7
LOSS = 0.88
RBIN = 0.05  # GWA/ERA5 speed-ratio bin width

cutout = atlite.Cutout(DATA / "cutouts" / "vietnam-2024-era5.nc")
cl = pd.read_csv(EXP / "clusters.csv", index_col=0)

# ---------------- regions ----------------
g2 = gpd.read_file(DATA / "shapes" / "gadm41_VNM_2.json").to_crs(32648)
cx = gpd.GeoSeries(gpd.points_from_xy(cl.x, cl.y), crs=4326).to_crs(32648)
rp = g2.geometry.representative_point()
g2["cl"] = cl.index[np.argmin(np.hypot(rp.x.values[:, None] - cx.x.values[None], rp.y.values[:, None] - cx.y.values[None]), 1)]
regions = g2.dissolve("cl").geometry.to_crs(4326).reindex(cl.index)
assert regions.notna().all()

# ---------------- eligibility ----------------
pa = gpd.read_file(GIS / "wdpa_vn_terrestrial.gpkg").to_crs(32648)
wc, sl = str(GIS / "worldcover2021_vn_74m.tif"), str(GIS / "slope_vn_deg_90m.tif")
wc_pv = wc
if CROP_RULE == "nodelta":  # recode delta cropland 40 -> 41 (not eligible) in a PV-only copy of the land-cover raster
    wc_pv = str(GIS / "worldcover2021_vn_74m_pv_nodeltacrop.tif")
    if not Path(wc_pv).exists():
        from rasterio.features import geometry_mask
        g1 = gpd.read_file(DATA / "shapes" / "gadm41_VNM_1.json").to_crs(4326)
        with rasterio.open(wc) as src:
            a_, prof = src.read(1), src.profile
            inside = ~geometry_mask(g1[g1.NAME_1.isin(DELTAS)].geometry, out_shape=a_.shape, transform=src.transform)
        a_[(a_ == 40) & inside] = 41
        with rasterio.open(wc_pv, "w", **prof) as dst:
            dst.write(a_, 1)
ex = {}
for k, smax, setback in [("solar", SLOPE_PV, 0), ("onwind", SLOPE_WIND, 500)]:
    e = ExclusionContainer(crs=32648, res=100)
    ok_ = [c_ for c_ in LAND_OK if not (k == "solar" and CROP_RULE == "none" and c_ == 40)]
    e.add_raster(wc_pv if k == "solar" else wc, codes=ok_, invert=True, crs=4326)
    e.add_raster(sl, codes=lambda z, m=smax: (z > m) & (z != 255), crs=4326)
    if setback:
        e.add_raster(wc, codes=[50], buffer=setback, crs=4326)
    e.add_geometry(pa.geometry)
    ex[k] = e
A = {k: cutout.availabilitymatrix(regions, ex[k]) for k in ex}  # (region, y, x) eligible share of cell
I = cutout.availabilitymatrix(regions, ExclusionContainer(crs=32648, res=1000))  # region overlap only
cell_km2 = (0.25 * 111.32) ** 2 * np.cos(np.radians(cutout.data.y))  # (y)
RD = I.dims[0]  # region dimension name
land_mask = (I.sum(RD) > 0)


def local(df):
    """UTC hourly frame of the cutout year -> local UTC+7 (first 7 local hours wrap from year end)."""
    t = df.index + pd.Timedelta(hours=TZ_H)
    df = df.set_axis(t)
    head = df.iloc[-TZ_H:].set_axis(df.index[:TZ_H] - pd.Timedelta(hours=TZ_H))
    return pd.concat([head, df.iloc[:-TZ_H]])


def regional(cf_cells, W):
    """time x region mean of cell CF (time,y,x) weighted by W (region,y,x); fallback to plain overlap weights."""
    w = (W * cell_km2).transpose(RD, "y", "x")
    w = w.where(w.sum(["y", "x"]) > 0, (I * cell_km2).transpose(RD, "y", "x"))
    w = w / w.sum(["y", "x"])
    c = cf_cells.transpose("time", "y", "x")
    r = pd.DataFrame(c.values.reshape(len(c.time), -1) @ w.values.reshape(len(w[RD]), -1).T,
                     index=pd.DatetimeIndex(c.time.values), columns=w[RD].values)
    return local(r)


# ---------------- plants (2024 fleet) at cells ----------------
p = pd.read_csv(DATA / "networks" / "plants_mapped.csv")
xs, ys = cutout.data.x.values, cutout.data.y.values


def cells(df):
    return np.abs(xs[None] - df.lon.values[:, None]).argmin(1), np.abs(ys[None] - df.lat.values[:, None]).argmin(1)


# ---------------- solar ----------------
pv = cutout.pv(panel="CSi", orientation="latitude_optimal", capacity_factor_timeseries=True).load().transpose("time", "y", "x")
farm = p[p.carrier == "solar"]
ix, iy = cells(farm)
raw_farm_twh = float((pv.values[:, iy, ix].mean(0) * farm.p_nom.values).sum() * len(pv.time) / 1e6)
v2 = json.loads((EXP / "cf_calibration.json").read_text())
target_farm_twh = v2["model_TWh_raw"]["solar"] * v2["factor_solar"]  # v2 calibrated farm energy (Ember - rooftop)
f_pv = target_farm_twh / raw_farm_twh
cf_solar = (regional(pv, A["solar"]) * f_pv).clip(upper=1)

# ---------------- wind ----------------
def curve(name):
    d = yaml.safe_load(open(Path(atlite.__file__).parent / "resources" / "windturbine" / name))
    return np.array(d["V"]), np.array(d["POW"]) / max(d["POW"])


V4, P4 = curve("NREL_ReferenceTurbine_2020ATB_4MW.yaml")
V55, P55 = curve("NREL_ReferenceTurbine_2020ATB_5.5MW.yaml")
ws = cutout.data.wnd100m.transpose("time", "y", "x").load()  # raw ERA5 100 m speed (time,y,x)
ws_mean = ws.mean("time").values
T = len(ws.time)
K160, K110 = (160 / 100) ** 0.14, (110 / 100) ** 0.14
# Global Wind Atlas v4 (250 m) mean speed at 100 m -> sub-grid scaling r = GWA / ERA5 cell mean (D-24)
with rasterio.open(GIS / "gwa" / "VNM_wind-speed_100m.tif") as r_:
    gwa, gt, gcrs = r_.read(1).astype("float32"), r_.transform, r_.crs
em, et = shape_availability(gpd.GeoSeries([regions.to_crs(32648).union_all()], crs=32648), ex["onwind"])
elig = np.zeros(gwa.shape, "float32")
reproject(em.astype("float32"), elig, src_transform=et, src_crs="EPSG:32648", dst_transform=gt, dst_crs=gcrs,
          resampling=Resampling.average)
reg_id = rasterize(((g_, i + 1) for i, g_ in enumerate(regions.values)), out_shape=gwa.shape, transform=gt, fill=0,
                   dtype="int16")
rows, cols = np.nonzero((elig > 0) & (reg_id > 0) & np.isfinite(gwa))
plon, plat = (np.asarray(v) for v in rasterio.transform.xy(gt, rows, cols))
pix = pd.DataFrame({"ix": np.abs(xs[None] - plon[:, None]).argmin(1), "iy": np.abs(ys[None] - plat[:, None]).argmin(1),
                    "reg": reg_id[rows, cols] - 1, "km2": elig[rows, cols] * (0.0025 * 111.32) ** 2 * np.cos(np.radians(plat))})
pix["r"] = gwa[rows, cols] / ws_mean[pix.iy, pix.ix]
pix["rb"] = (np.clip(pix.r, 0.2, 5.0) / RBIN).round() * RBIN
wf = p[p.carrier == "onwind"]
jx, jy = cells(wf)
prow, pcol = rasterio.transform.rowcol(gt, wf.lon.values, wf.lat.values)
r_fleet = np.nan_to_num(gwa[np.clip(prow, 0, gwa.shape[0] - 1), np.clip(pcol, 0, gwa.shape[1] - 1)] / ws_mean[jy, jx], nan=1.0)
wsf = ws.values[:, jy, jx] * r_fleet


def fleet_twh(s):
    return float((np.interp(wsf * s * K110, V4, P4) * LOSS * wf.p_nom.values).sum() / 1e6)


lo, hi = 0.4, 2.5
for _ in range(60):
    mid = (lo + hi) / 2
    lo, hi = (mid, hi) if fleet_twh(mid) < EMBER_WIND_TWH else (lo, mid)
s = (lo + hi) / 2
# unique (ERA5 cell, scaling bin) combos -> hourly CF once each; accumulate area-weighted per region x class
pix["combo"] = pix.groupby(["iy", "ix", "rb"]).ngroup()
cmb = pix.groupby("combo")[["iy", "ix", "rb"]].first()
agg = pix.groupby(["combo", "reg"]).km2.sum().reset_index()
R, cls_names = len(cl), list(CLASSES)
acc55 = np.zeros((T, R, len(cls_names)))
acc4 = np.zeros((T, R))
area = np.zeros((R, len(cls_names)))
cmb_cf = np.zeros(len(cmb))
for c0 in range(0, len(cmb), 2000):
    cc = cmb.iloc[c0:c0 + 2000]
    U = ws.values[:, cc.iy.values, cc.ix.values] * cc.rb.values * s  # T x n
    X55 = np.interp(U * K160, V55, P55) * LOSS
    X4 = np.interp(U * K110, V4, P4) * LOSS
    m = X55.mean(0)
    cmb_cf[c0:c0 + len(cc)] = m
    k = np.select([m >= lo_ for lo_, _ in CLASSES.values()], range(len(cls_names)), len(cls_names) - 1)
    a_ = agg[(agg.combo >= c0) & (agg.combo < c0 + len(cc))]
    j = a_.combo.values - c0
    for kk in range(len(cls_names)):
        sel = k[j] == kk
        if sel.any():
            Wm = np.zeros((len(cc), R))
            np.add.at(Wm, (j[sel], a_.reg.values[sel]), a_.km2.values[sel])
            acc55[:, :, kk] += X55 @ Wm
            area[:, kk] += Wm.sum(0)
    W4 = np.zeros((len(cc), R))
    np.add.at(W4, (j, a_.reg.values), a_.km2.values)
    acc4 += X4 @ W4
utc = pd.DatetimeIndex(ws.time.values)
cf_on_new = {}
for kk, nm in enumerate(cls_names):
    with np.errstate(invalid="ignore", divide="ignore"):
        cf_on_new[nm] = local(pd.DataFrame(acc55[:, :, kk] / area[:, kk], index=utc, columns=cl.index)).fillna(0.0)
el_w = {nm: pd.Series(area[:, kk], index=cl.index) for kk, nm in enumerate(cls_names)}
with np.errstate(invalid="ignore", divide="ignore"):
    cf4_all = local(pd.DataFrame(acc4 / area.sum(1), index=utc, columns=cl.index)).fillna(0.0)


def fleet_profile(series, plants, fallback):
    """existing fleet: capacity-weighted CF of the plants' own sites per region; regions without fleet -> fallback."""
    df = pd.DataFrame(series * plants.p_nom.values, index=pd.DatetimeIndex(ws.time.values))
    out = local(df.T.groupby(plants.cl.values).sum().T / plants.groupby("cl").p_nom.sum())
    return out.reindex(columns=fallback.columns).fillna(fallback)


pc = gpd.GeoSeries(gpd.points_from_xy(p.lon, p.lat), crs=4326).to_crs(32648)
p["cl"] = cl.index[np.argmin(np.hypot(pc.x.values[:, None] - cx.x.values[None], pc.y.values[:, None] - cx.y.values[None]), 1)]
farm = p[p.carrier == "solar"]
ix, iy = cells(farm)
cf_solar_exist = (fleet_profile(pv.values[:, iy, ix], farm, cf_solar / f_pv) * f_pv).clip(upper=1)
wf = p[p.carrier == "onwind"]
cf_onwind = fleet_profile(np.interp(wsf * s * K110, V4, P4) * LOSS, wf, cf4_all)
cf_cell = cf_onwind  # for quantile stats below (pixel-level stats reported separately)

# ---------------- potentials ----------------
el = {"solar": (A["solar"] * cell_km2).sum(["y", "x"]).to_pandas(), **el_w}
land = (I * cell_km2).sum(["y", "x"]).to_pandas()
pot = pd.DataFrame({"land_km2": land, "eligible_km2_solar": el["solar"],
                    **{f"eligible_km2_onwind_{k}": el[k] for k in CLASSES}})
wind_km2 = sum(el[k] for k in CLASSES)
pot["pot_solar_MW"] = POT["solar"] * pot.eligible_km2_solar / pot.eligible_km2_solar.sum()
for k in CLASSES:
    pot[f"pot_onwind_{k}_MW"] = POT["onwind"] * el[k] / wind_km2.sum()
    pot[f"cf_onwind_new_{k}"] = cf_on_new[k].mean().where(el[k] > 0).round(3)
pot["cf_solar"] = cf_solar.mean().round(3)
pot.round(3).to_csv(OUT / "potentials.csv")
for k, df in [("solar", cf_solar), ("solar_exist", cf_solar_exist), ("onwind", cf_onwind)] + \
        [(f"onwind_new_{c}", d) for c, d in cf_on_new.items()]:
    df.round(4).to_csv(OUT / f"cf_{k}.csv")

pw = {k: pot[f"pot_onwind_{k}_MW"] for k in CLASSES}
info = {"crop_rule_pv": CROP_RULE, "factor_pv": round(f_pv, 4), "pv_fleet_raw_TWh": round(raw_farm_twh, 2), "pv_fleet_target_TWh": round(target_farm_twh, 2),
        "wind_speed_factor_s": round(s, 4), "wind_fleet_TWh": round(fleet_twh(s), 2),
        "onwind_classes_cf": CLASSES,
        "eligible_km2": {"solar": round(float(pot.eligible_km2_solar.sum())), "onwind": round(float(wind_km2.sum())),
                         **{f"onwind_{k}": round(float(el[k].sum())) for k in CLASSES}, "land": round(float(land.sum()))},
        "implied_MW_per_km2": {"solar": round(POT["solar"] / float(pot.eligible_km2_solar.sum()), 2),
                               "onwind": round(POT["onwind"] / float(wind_km2.sum()), 2)},
        "pot_GW_by_class": {k: round(float(v.sum()) / 1e3, 1) for k, v in pw.items()},
        "pot_weighted_cf_new_by_class": {k: round(float((pot[f"cf_onwind_new_{k}"].fillna(0) * v).sum() / max(v.sum(), 1)), 3)
                                         for k, v in pw.items()},
        "pot_weighted_cf_solar": round(float((pot.cf_solar * pot.pot_solar_MW).sum() / pot.pot_solar_MW.sum()), 3),
        "fleet_check_TWh": {c_: round(float((prof_ * p[p.carrier == c_].groupby("cl").p_nom.sum()).sum().sum() / 1e6), 2)
                            for c_, prof_ in [("solar", cf_solar_exist), ("onwind", cf_onwind)]},
        "gwa_scaling_r_quantiles_eligible": {q: round(float(pix.r.quantile(q)), 2) for q in [0.1, 0.5, 0.9, 0.99]},
        "cf_new_quantiles_eligible_area": {q: round(float(np.interp(q, (pix.km2.values[np.argsort(cmb_cf[pix.combo])].cumsum()
                                                                        / pix.km2.sum()), np.sort(cmb_cf[pix.combo]))), 3)
                                           for q in [0.5, 0.75, 0.9, 0.95, 0.99]}}
(OUT / "calib.json").write_text(json.dumps(info, indent=1))
print(json.dumps(info, indent=1))
print(pot[["eligible_km2_solar", "pot_solar_MW", "cf_solar"] + [f"pot_onwind_{k}_MW" for k in CLASSES] +
          [f"cf_onwind_new_{k}" for k in CLASSES]].round(2).sort_values("pot_onwind_w1_MW", ascending=False).to_string())
pot["pot_onwind_MW"] = sum(pw.values())

# ---------------- figure ----------------
rg = gpd.GeoDataFrame(pot, geometry=regions.values, crs=4326)
rg["pot_onwind_good_MW"] = rg.pot_onwind_w1_MW + rg.pot_onwind_w2_MW
fig, axs = plt.subplots(1, 2, figsize=(9, 7.2))
for ax, (col, lab) in zip(axs, [("pot_solar_MW", f"Utility PV (total {POT['solar'] / 1e3:.0f} GW)"),
                                ("pot_onwind_good_MW", f"Onshore wind, CF $\\geq$ 0.20 ({rg.pot_onwind_good_MW.sum() / 1e3:.0f} "
                                                       f"of {POT['onwind'] / 1e3:.0f} GW)")]):
    rg.assign(v=rg[col] / 1e3).plot(column="v", ax=ax, cmap="Blues", edgecolor="#9a9a9a", linewidth=0.3, legend=True,
                                    legend_kwds={"label": "Potential [GW]", "shrink": 0.55})
    ax.set_title(lab, loc="left", fontsize=10)
    ax.set_axis_off()
fig.text(0.02, 0.02, "National potentials of Decision 768 split by eligible land (WorldCover shrub/grass/crop/bare, slope "
         "limits, outside WDPA;\nwind >= 500 m from built-up). Wind classes from ERA5 downscaled with the Global Wind Atlas.",
         fontsize=8)
FIG.mkdir(parents=True, exist_ok=True)
fig.savefig(FIG / "vre_potentials_gis.png", dpi=160, bbox_inches="tight")
print("->", OUT, FIG / "vre_potentials_gis.png")
