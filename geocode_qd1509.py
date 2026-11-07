#!/usr/bin/env python3
"""Approximate coordinates for planned lines/substations of Decision 1509/QD-BCT (S10) -> map / 2030 model.

Endpoint names are parsed from line names ("A - B", "Mạch 2 A - B", "A - Rẽ B - C" = loop-in of new substation A
into line B-C). Each endpoint is located, in order of preference:
  1. model substation bus with the same normalized name (OSM names, same kV preferred)          [method 'bus']
  2. planned substation already located in an earlier pass (iterate)                           [via 1/3/4]
  3. GEM plant name (for plant connections: LNG/NĐ/TĐ/ĐG/ĐMT ...)                                [method 'gem']
  4. GADM district (level 2) name, then province (level 1) name -> polygon centroid           [method 'district'/'province']
Region of the source table (Bắc/Trung/Nam) restricts candidates by latitude band. All positions are APPROXIMATE
(district/province centroids for new substations); used for illustration and as a first guess for the 2030 model.
Outputs: <DATA>/plans/qd1509_lines_geo.csv, qd1509_substations_geo.csv
"""
import os
import re
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from substation_mva import norm  # noqa: E402

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[0] / "data"))
P = DATA / "plans"
BAND = {"Bắc": (17.6, 24.0), "Trung": (11.5, 18.3), "Nam": (8.0, 12.7)}
PREFIX = (r"^(mạch\s*\d+|mạch kép|mạch đơn|nâng khả năng tải|cải tạo|treo dây mạch \d+|đấu nối|tba|trạm cắt|trạm|"
          r"nmnđ|nmđ|nm|nđ|nhiệt điện|tbkhh|lng|tđ|thủy điện|thuỷ điện|tđtn|đg|điện gió|đmt|điện mặt trời|kcn|"
          r"khu kinh tế|kkt|cảng|cụm|nhà máy|điện hạt nhân|đhn)\s+")

lines = pd.read_csv(P / "qd1509_lines.csv")
subs = pd.read_csv(P / "qd1509_substations.csv")
buses = pd.read_csv(DATA / "grid" / "topology" / "buses.csv")
buses = buses[buses.type.isin(["substation", "line_end"]) & buses.name.notna()].copy()
buses["key"] = buses.name.map(norm)
VG = Path(__file__).resolve().parents[1] / "vietnamgrid" / "data_model_v2" / "buses.csv"
vg = pd.read_csv(VG)  # 79-bus 500 kV paper model: names like 'TayHaNoi' (fills OSM-unnamed 500 kV substations)
vg = pd.DataFrame({"name": vg.name, "x": vg.x, "y": vg.y, "v_nom": 500,
                   "key": vg.name.astype(str).str.replace(r"(?<=[a-z])(?=[A-Z0-9])", " ", regex=True).map(norm)})
buses = pd.concat([buses, vg], ignore_index=True)
g2 = gpd.read_file(DATA / "shapes" / "gadm41_VNM_2.json").to_crs(32648)
g1 = gpd.read_file(DATA / "shapes" / "gadm41_VNM_1.json").to_crs(32648)
for g, col in [(g2, "NAME_2"), (g1, "NAME_1")]:
    c = g.geometry.representative_point().to_crs(4326)
    g["x"], g["y"], g["key"] = c.x.values, c.y.values, g[col].map(norm)
gem = pd.read_csv(DATA / "plants" / "vn_units_gem.csv").dropna(subset=["lat"])
gem = gem.groupby("plant", as_index=False)[["lat", "lon"]].mean()
gem["key"] = gem.plant.str.replace(r"(?i)\b(power station|power plant|wind farm|solar farm|hydroelectric plant|"
                                   r"thermal power plant|lng|combined cycle|power center|project|complex)\b", "", regex=True).map(norm)
NUCLEAR = {"ninhthuan1": (108.98, 11.43), "ninhthuan2": (109.18, 11.70)}  # approximate (also in plot_grid_2030_2035)
# converter areas per QD 1509 Appendix II.2 Bang 1 notes (province-level, schematic); border points (approx.)
SPECIAL = {"bb1": (106.17, 20.42), "bacbo1": (106.17, 20.42), "bb2": (105.55, 21.00), "bacbo2": (105.55, 21.00),
           "bb3": (106.05, 20.85), "bacbo3": (106.05, 20.85), "ttb1": (106.85, 17.15), "trungtrungbo1": (106.85, 17.15),
           "ttb2": (108.80, 15.10), "trungtrungbo2": (108.80, 15.10), "ntb": (108.95, 11.60), "namtrungbo": (108.95, 11.60),
           "samnuea": (104.04, 20.42), "biengioivietnamtrungquoc": (103.96, 22.50), "laocaibtb": (103.97, 22.48)}


def clean(s):
    s = re.sub(r"\(\*\)|\*", "", str(s)).strip()
    s = re.sub(r"\b\d{3}\s*kV\b", "", s, flags=re.I).strip()
    for _ in range(3):
        s = re.sub(PREFIX, "", s.strip(), flags=re.I)
    return s.strip(" -–,.")


def candidates(raw):
    alt = re.findall(r"\(([^)]*)\)", raw)
    base = clean(re.sub(r"\(.*?\)", "", raw))
    out = [base] + [clean(a) for a in alt]
    out += [re.sub(r"\s+(mở rộng|mr|gđ\s*\d+|giai đoạn\s*\d+)$", "", c, flags=re.I) for c in out]
    out += [re.sub(r"\s*(\d+|I{1,3}|IV|V)$", "", c) for c in out]  # 'Hưng Yên 2' -> 'Hưng Yên', 'Quảng Trạch II'
    out += [re.sub(r"\s*(\d+|I{1,3}|IV|V)$", "", c) for c in out]
    return [c for c in dict.fromkeys(out) if c]


located = {}  # planned substation name key -> (x, y, method)


def locate(raw, kv, region):
    lo, hi = BAND[region]
    for c in candidates(raw):
        k = norm(c)
        if not k:
            continue
        if k in NUCLEAR and "hạt nhân" in raw.lower():
            return (*NUCLEAR[k], "nuclear-approx")
        if k in SPECIAL:
            return (*SPECIAL[k], "special-approx")
        b = buses[(buses.key == k) & buses.y.between(lo, hi)]
        if len(b):
            b2 = b[b.v_nom == kv]
            r = (b2 if len(b2) else b).iloc[0]
            return r.x, r.y, "bus"
        if k in located:
            return located[k]
        gm = gem[(gem.key == k) & gem.lat.between(lo, hi)]
        if len(gm):
            return gm.lon.iloc[0], gm.lat.iloc[0], "gem"
        for g, m in [(g2, "district"), (g1, "province")]:
            hit = g[(g.key == k) & g.y.between(lo, hi)]
            if len(hit):
                return hit.x.iloc[0], hit.y.iloc[0], m
    return np.nan, np.nan, ""


# substations first (they anchor line endpoints)
S = subs.copy()
S[["x", "y", "method"]] = [locate(n, kv, r) for n, kv, r in zip(S.name, S.kv, S.region)]
for _, r in S.dropna(subset=["x"]).iterrows():
    for c in candidates(r["name"]):
        located.setdefault(norm(c), (r.x, r.y, r.method))
S.to_csv(P / "qd1509_substations_geo.csv", index=False)


def parse(name):
    s = re.sub(r"\(\*\)", "", str(name))
    m = re.match(r"(.+?)\s*[-–]\s*Rẽ\s+(.+?)\s*[-–]\s*(.+)$", s)
    if m:
        return [m.group(1), m.group(2), m.group(3)], True
    s = re.sub(r"^(Mạch\s*\d+|Mạch kép|Mạch đơn)\s+", "", s.strip(), flags=re.I)
    parts = [p for p in re.split(r"\s+[-–]\s+|\s*[-–]\s*(?=[A-ZĐÂĂÊÔƠƯ])", s) if p.strip()]
    return parts[:2], False


rows = []
for _, r in lines.iterrows():
    parts, loop = parse(r["name"])
    pts = [locate(p, r.kv, r.region) for p in parts]
    rec = r.to_dict() | {"loop_in": loop, "ep": " | ".join(parts)}
    if loop and len(pts) == 3:
        (xa, ya, ma), (xb, yb, mb), (xc, yc, mc) = pts
        if not np.isnan(xb) and not np.isnan(xc):
            xm, ym = (xb + xc) / 2, (yb + yc) / 2  # loop-in drawn to the midpoint of the tapped line
        else:
            xm, ym = (xb, yb) if not np.isnan(xb) else (xc, yc)
        rec |= {"x0": xa, "y0": ya, "x1": xm, "y1": ym, "m0": ma, "m1": f"{mb}/{mc}"}
    elif len(pts) >= 2:
        (xa, ya, ma), (xb, yb, mb) = pts[:2]
        rec |= {"x0": xa, "y0": ya, "x1": xb, "y1": yb, "m0": ma, "m1": mb}
    rows.append(rec)
L = pd.DataFrame(rows)
L["ok"] = L[["x0", "y0", "x1", "y1"]].notna().all(axis=1)
L.to_csv(P / "qd1509_lines_geo.csv", index=False)
print("substations located:", S.x.notna().sum(), "/", len(S), S.method.value_counts().to_dict())
print("lines with both ends:", int(L.ok.sum()), "/", len(L))
print(L.groupby(["kv", "period"]).apply(lambda d: pd.Series({"n": len(d), "ok": int(d.ok.sum()),
      "ckm_ok_share": round(d[d.ok].circuit_km.sum() / d.circuit_km.sum(), 2)})).to_string())
print("unlocated 500 kV examples:", L[(L.kv == 500) & ~L.ok].ep.head(15).tolist())
