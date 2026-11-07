#!/usr/bin/env python3
"""GIS inputs for VRE land eligibility (vre_gis.py), Vietnam only, minimal downloads (D-21..D-23):
 1. ESA WorldCover 2021 v200 (10 m COG, AWS open data) read at overview x8 (~74 m) via HTTP range requests
    -> <DATA>/gis/worldcover2021_vn_74m.tif  (full 10 m tiles are not downloaded)
 2. Copernicus GLO-90 DEM (COG, AWS open data), 1-degree tiles over Vietnam -> slope [deg]
    -> <DATA>/gis/slope_vn_deg_90m.tif  (DEM tiles are streamed, not stored)
 3. WDPA/WDOECM Nov 2026, Vietnam (Protected Planet) -> <DATA>/gis/wdpa/ (zip as downloaded)
    -> <DATA>/gis/wdpa_vn_terrestrial.gpkg (status designated/inscribed/established, not marine-only)
Run: python -I workflow/scripts/gis_inputs.py
"""
import os
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
GIS = DATA / "gis"
GIS.mkdir(exist_ok=True)
X0, X1, Y0, Y1 = 102.0, 110.0, 8.0, 24.0  # mosaic extent (deg)
vn = gpd.read_file(DATA / "shapes" / "gadm41_VNM_0.json").to_crs(4326).geometry.union_all().buffer(0.05)
UA = "pypsa-vn-research"


def write(fn, arr, res, nodata):
    with rasterio.open(fn, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype=arr.dtype,
                       crs="EPSG:4326", transform=from_origin(X0, Y1, res, res), nodata=nodata, compress="deflate",
                       tiled=True, predictor=1) as d:
        d.write(arr, 1)
    print("->", fn, f"{fn.stat().st_size / 1e6:.0f} MB")


# 1. WorldCover at overview level index 2 (factor 8): 36000 px / 3 deg -> 4500 px / 3 deg
WC = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{t}_Map.tif"
fn_wc = GIS / "worldcover2021_vn_74m.tif"
if not fn_wc.exists():
    ppd = 1500
    wc = np.zeros((int((Y1 - Y0) * ppd), int((X1 - X0) * ppd)), dtype="uint8")
    tiles = [(la, lo) for la in range(6, 24, 3) for lo in range(102, 111, 3) if box(lo, la, lo + 3, la + 3).intersects(vn)]

    def read_wc(t):
        la, lo = t
        url = "/vsicurl/" + WC.format(t=f"N{la:02d}E{lo:03d}")
        try:
            with rasterio.open(url, OVERVIEW_LEVEL=2) as r:
                return t, r.read(1)
        except rasterio.errors.RasterioIOError:
            return t, None

    with ThreadPoolExecutor(6) as ex:
        for (la, lo), a in ex.map(read_wc, tiles):
            if a is None:
                print("worldcover tile missing (sea):", la, lo)
                continue
            assert a.shape == (3 * ppd, 3 * ppd), a.shape
            r0, c0 = int((Y1 - (la + 3)) * ppd), int((lo - X0) * ppd)
            rs, cs = slice(max(r0, 0), min(r0 + 3 * ppd, wc.shape[0])), slice(max(c0, 0), min(c0 + 3 * ppd, wc.shape[1]))
            wc[rs, cs] = a[rs.start - r0:rs.stop - r0, cs.start - c0:cs.stop - c0]
            print("worldcover", la, lo, "ok")
    write(fn_wc, wc, 1 / ppd, 0)

# 2. slope from GLO-90 (3 arcsec = 1200 px/deg at these latitudes)
DEM = "https://copernicus-dem-90m.s3.amazonaws.com/{n}/{n}.tif"
fn_sl = GIS / "slope_vn_deg_90m.tif"
if not fn_sl.exists():
    ppd = 1200
    sl = np.full((int((Y1 - Y0) * ppd), int((X1 - X0) * ppd)), 255, dtype="uint8")
    cells = [(la, lo) for la in range(int(Y0), int(Y1)) for lo in range(int(X0), int(X1))
             if box(lo, la, lo + 1, la + 1).intersects(vn)]

    def slope(t):
        la, lo = t
        nm = f"Copernicus_DSM_COG_30_N{la:02d}_00_E{lo:03d}_00_DEM"
        try:
            with rasterio.open("/vsicurl/" + DEM.format(n=nm)) as r:
                z = r.read(1).astype("float32")
        except rasterio.errors.RasterioIOError:
            return t, None
        dy = 3 / 3600 * 110_574.0
        dx = 3 / 3600 * 111_320.0 * np.cos(np.radians(la + 0.5))
        gy, gx = np.gradient(z, dy, dx)
        return t, np.degrees(np.arctan(np.hypot(gx, gy))).round().clip(0, 90).astype("uint8")

    with ThreadPoolExecutor(8) as ex:
        for (la, lo), a in ex.map(slope, cells):
            if a is None:
                continue
            assert a.shape == (ppd, ppd), (la, lo, a.shape)
            r0, c0 = int((Y1 - (la + 1)) * ppd), int((lo - X0) * ppd)
            sl[r0:r0 + ppd, c0:c0 + ppd] = a
    print("DEM tiles used:", int((sl != 255).sum() / ppd ** 2), "of", len(cells))
    write(fn_sl, sl, 1 / ppd, 255)

# 3. WDPA Vietnam
WD = GIS / "wdpa"
fn_pa = GIS / "wdpa_vn_terrestrial.gpkg"
if not fn_pa.exists():
    WD.mkdir(exist_ok=True)
    z = WD / "WDPA_WDOECM_Nov2026_Public_VNM_shp.zip"
    if not z.exists():
        subprocess.run(["curl", "-sSfL", "-A", UA, "-o", str(z),
                        "https://d1gam3xoknrgr2.cloudfront.net/current/WDPA_WDOECM_Nov2026_Public_VNM_shp.zip"], check=True)
    ex_dir = WD / "extract"
    ex_dir.mkdir(exist_ok=True)

    def safe_extract(zf, dest):
        for m in zf.namelist():
            p = (dest / m).resolve()
            assert str(p).startswith(str(dest.resolve())), f"unsafe path {m}"
        zf.extractall(dest)

    with zipfile.ZipFile(z) as zf:
        safe_extract(zf, ex_dir)
    for inner in sorted(ex_dir.glob("*.zip")):
        with zipfile.ZipFile(inner) as zf:
            safe_extract(zf, ex_dir / inner.stem)
    polys = [gpd.read_file(f) for f in sorted(ex_dir.rglob("*polygons.shp"))]
    pa = pd.concat(polys, ignore_index=True)
    n0 = len(pa)
    pa = pa[pa.STATUS.isin(["Designated", "Inscribed", "Established"]) & (pa.REALM != "Marine")]  # 2026 schema: REALM
    pa[["SITE_ID", "NAME", "DESIG_ENG", "IUCN_CAT", "STATUS", "REALM", "GIS_AREA", "geometry"]].to_file(fn_pa)
    print(f"WDPA polygons {n0} -> {len(pa)} terrestrial/coastal designated, {pa.GIS_AREA.astype(float).sum():.0f} km2 ->", fn_pa)
