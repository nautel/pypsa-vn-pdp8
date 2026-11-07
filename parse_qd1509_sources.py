#!/usr/bin/env python3
"""Decision 1509/QĐ-BCT Annex II.1: onshore wind (table 17) and solar (table 18) project lists by province ->
per-province MW and split onto the 30 expansion regions (share of the province's 2024 model buses in each region).
Input: <DATA>/plans/qd1509_bct_2025_caselaw.html (S10); <DATA>/networks/vn2024_base.nc; <DATA>/expansion/busmap.csv
Output: <DATA>/plans/qd1509_sources_by_province.csv, <DATA>/plans/qd1509_sources_by_cluster.csv
Project MW: last number in the cell (ranges "a-b" -> b). Province header rows ("Tỉnh X") start a block.
Run: python parse_qd1509_sources.py
"""
import io
import os
import re
import unicodedata
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import logging  # noqa: E402

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402

logging.disable(logging.WARNING)
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[0] / "data"))
tabs = pd.read_html(io.StringIO((DATA / "plans" / "qd1509_bct_2025_caselaw.html").read_text(encoding="utf-8")))


def num(x):
    m = re.findall(r"\d+(?:\.\d+)?", str(x).replace(".", "").replace(",", "."))
    return float(m[-1]) if m else float("nan")


def key(s):
    s = unicodedata.normalize("NFC", str(s))
    s = re.sub(r"^(Tỉnh|TP\.|Thành phố)\s+", "", s.strip())
    return re.sub(r"[\s\-–]", "", s).lower()


ALIAS = {"huế": "thừathiênhuế", "hồchíminh": "hồchíminh"}
rows = []
for k, car in [(17, "onwind"), (18, "solar")]:
    prov = None
    for _, r in tabs[k].iloc[1:].iterrows():
        name = str(r.iloc[1]).strip()
        if re.match(r"^(Tỉnh|TP\.|Thành phố)\s", name):
            prov = name
            continue
        if prov and re.match(r"^\d+$", str(r.iloc[0]).strip()):
            rows.append({"carrier": car, "province": re.sub(r"^(Tỉnh|TP\.|Thành phố)\s+", "", prov), "key": key(prov),
                         "project": name, "mw": num(r.iloc[2])})
P = pd.DataFrame(rows)
P["key"] = P.key.replace(ALIAS)
byp = P.groupby(["carrier", "province", "key"]).mw.sum().reset_index()
byp.to_csv(DATA / "plans" / "qd1509_sources_by_province.csv", index=False)

# province -> region split by share of 2024 model buses
n = pypsa.Network(DATA / "networks" / "vn2024_base.nc")
bm = pd.read_csv(DATA / "expansion" / "busmap.csv", index_col=0).cluster
prov = gpd.read_file(DATA / "shapes" / "gadm41_VNM_1.json")
prov["key"] = prov.NAME_1.map(key)
b = gpd.GeoDataFrame(geometry=gpd.points_from_xy(n.buses.x, n.buses.y), index=n.buses.index, crs=4326)
j = gpd.sjoin(b, prov[["key", "geometry"]], how="left", predicate="within")
j = j[~j.index.duplicated()]
share = (pd.DataFrame({"key": j.key, "cl": bm.reindex(j.index)}).dropna()
         .groupby(["key", "cl"]).size().groupby(level=0).transform(lambda s: s / s.sum()).rename("share").reset_index())
miss = sorted(set(byp.key) - set(share.key))
print("provinces without match:", miss)
m = byp.merge(share, on="key", how="inner")
m["mw_cl"] = m.mw * m.share
bycl = m.groupby(["carrier", "cl"]).mw_cl.sum().unstack(0).fillna(0).round(1)
bycl.to_csv(DATA / "plans" / "qd1509_sources_by_cluster.csv")
print(byp.groupby("carrier").mw.sum().div(1e3).round(1).to_dict(), "GW listed;",
      "mapped:", bycl.sum().div(1e3).round(1).to_dict())
print(bycl.sort_values("solar", ascending=False).head(8))
