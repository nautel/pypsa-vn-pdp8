#!/usr/bin/env python3
"""Per-substation transformer MVA (500/220 kV and 220/110 kV) for the model's substations.

Sources, by priority:
  1. <DATA>/grid/substation_mva/evn_500kV.csv, evn_220kV_{north,central,south}.csv  (compiled from EVN/EVNNPT/MOIT
     news and plans, one source URL per row)
  2. <DATA>/grid/substation_mva/osm_transformers_rated.json  (OSM power=transformer with rating tag)
Model substation names: OSM name; unnamed 500 kV buses get the nearest vietnamgrid (paper) 500 kV bus name <= 3 km.
Run standalone to write <DATA>/grid/substation_mva/matched.csv and print coverage.
"""
import os
import json
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
SM = DATA / "grid" / "substation_mva"
VG = Path(os.environ.get("VIETNAMGRID_DIR", Path(__file__).resolve().parents[3] / "vietnamgrid")) / "data_model_v2"
STOP = r"tram bien ap|khu bien ap|san phan phoi|tram cat|tram dien|nha may|thuy dien|nhiet dien|dien gio|" \
       r"dien mat troi|tba|tram|\d{2,3}(\s*/\s*\d{2,3})*\s*kv|\bkv\b|\be\d+(\.\d+)?\b|tp\.?|thanh pho|\bmba\b"


def norm(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFD", s.replace("Đ", "D").replace("đ", "d"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(STOP, " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def key(name, v):
    """normalized name; at 220 kV, tag yards that must not take a 220/110 kV substation's MVA."""
    k = norm(name)
    if not k or v != 220:
        return k
    low = unicodedata.normalize("NFC", str(name)).lower()
    if re.search(r"500\s*(/\s*220\s*)?kv|500\s*kv", low):
        return "s500" + k  # 220 kV yard of a 500 kV substation
    if re.search(r"trạm cắt|tram cat", low):
        return "cat" + k
    if re.search(r"sân phân phối|nhà máy|nmđ|thủy điện|thuỷ điện|nhiệt điện|điện gió|điện mặt trời", low):
        return "plant" + k
    return k


def to_xy(lon, lat):
    import geopandas as gpd
    g = gpd.GeoSeries(gpd.points_from_xy(np.asarray(lon), np.asarray(lat)), crs=4326).to_crs(32648)
    return np.c_[g.x, g.y]


def model_names(buses):
    """buses: index bus, cols v_nom, x, y, substation, name (topology buses.csv)."""
    b = buses[buses.v_nom.isin([500, 220]) & buses.substation.notna()].copy()
    b["key"] = [key(n, v) for n, v in zip(b.name, b.v_nom)]
    vg = pd.read_csv(VG / "buses.csv")
    m = (b.v_nom == 500) & (b.key == "")
    if m.any():
        d, i = cKDTree(to_xy(vg.x, vg.y)).query(to_xy(b[m].x, b[m].y))
        b.loc[m, "key"] = np.where(d <= 3000, vg.name.values[i].astype(str), "")
        b.loc[m, "key"] = b.loc[m, "key"].map(lambda s: norm(re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", s)))
        b.loc[m, "name_src"] = np.where(d <= 3000, "vietnamgrid<=3km", "")
        b.loc[m, "d_vg"] = d
        # don't reuse a name already carried by an OSM-named 500 kV bus; among unnamed, only the nearest keeps it
        taken = set(b[(b.v_nom == 500) & ~m].key)
        mm = m & b.key.isin(taken)
        b.loc[mm, ["key", "name_src"]] = ""
        dup = b[m & (b.key != "")].sort_values("d_vg").duplicated("key")
        b.loc[dup[dup].index, ["key", "name_src"]] = ""
        # 220 kV yard of a 500 kV substation named this way -> 's500' + name (matches '<500kV X> (220/110 part)')
        nm = b[(b.v_nom == 500) & (b.name_src == "vietnamgrid<=3km") & (b.key != "")].set_index("substation").key
        m2 = (b.v_nom == 220) & (b.key == "") & b.substation.isin(nm.index)
        b.loc[m2, "key"] = "s500" + b.loc[m2, "substation"].map(nm)
    return b


def load_tables():
    """compiled tables -> rows with key, mva_total, status ('mva' | 'off' = not in service end-2024 or no
    step-down transformer | 'unknown'), node (model substation id given in notes for unnamed OSM nodes)."""
    fs = {500: ["evn_500kV.csv"], 220: ["evn_220kV_north.csv", "evn_220kV_central.csv", "evn_220kV_south.csv"]}
    out = []
    for v, names in fs.items():
        for f in names:
            if (SM / f).exists():
                t = pd.read_csv(SM / f)
                t["v"], t["file"] = v, f
                out.append(t)
    cols = ["name", "mva_total", "v", "key", "source_url", "in_service_2024", "status", "node"]
    if not out:
        return pd.DataFrame(columns=cols)
    t = pd.concat(out, ignore_index=True)
    t["mva_total"] = pd.to_numeric(t.mva_total, errors="coerce")
    off = t.in_service_2024.astype(str).str.lower().str.startswith("no") | (t.mva_total == 0)
    t["status"] = np.select([off, t.mva_total > 0], ["off", "mva"], "unknown")
    t["key"] = [key(n, v) for n, v in zip(t.name, t.v)]
    ids = t.get("notes", pd.Series("", index=t.index)).astype(str).str.findall(r"\b(S\d{6,})(?=_|\b)")
    t["node"] = ids.map(lambda x: x[0] if len(set(x)) == 1 else None)
    return t


def osm_ratings(buses_hv):
    """OSM power=transformer ratings summed per model substation (nearest HV bus <= 1.5 km).
    VN practice seen in OSM: 500/220 kV banks = single-phase units (phases=1, 150-300 MVA each);
    220/110 kV = three-phase 125-250 MVA units. Larger 3-phase units (e.g. 984 MVA) are generator step-ups -> skipped.
    Plant yards are excluded via the caller's keys."""
    fn = SM / "osm_transformers_rated.json"
    if not fn.exists() or fn.read_bytes()[:1] != b"{":
        return pd.Series(dtype=float), pd.Series(dtype=float)
    rows = []
    for e in json.loads(fn.read_text())["elements"]:
        t = e.get("tags", {})
        m = re.match(r"\s*([\d.]+)\s*MVA", t.get("rating", ""), re.I)
        if not m:
            continue
        mva, ph = float(m.group(1)), str(t.get("phases", "3"))
        v = 500 if (ph == "1" and mva >= 100) else (220 if (ph != "1" and 100 <= mva <= 250) else None)
        if v:
            rows.append({"mva": mva, "v": v, "lat": e.get("lat", e.get("center", {}).get("lat")),
                         "lon": e.get("lon", e.get("center", {}).get("lon"))})
    r = pd.DataFrame(rows)
    res = {}
    for v in [500, 220]:
        rv = r[r.v == v]
        bv = buses_hv[(buses_hv.v_nom == v) & ~buses_hv.key.str.startswith(("plant", "cat"))]
        if rv.empty or bv.empty:
            res[v] = pd.Series(dtype=float)
            continue
        d, i = cKDTree(to_xy(bv.x, bv.y)).query(to_xy(rv.lon, rv.lat))
        rv = rv.assign(sub=np.where(d <= 1500, bv.substation.values[i], None)).dropna(subset=["sub"])
        res[v] = rv.groupby("sub").mva.sum()
    return res[500], res[220]


def match(buses):
    """-> DataFrame per model HV substation bus: substation, v_nom, key, mva, status, source."""
    b = model_names(buses)
    t = load_tables()
    b["mva"], b["status"], b["source"] = np.nan, "", ""
    for v in [500, 220]:
        tv = t[(t.v == v) & (t.status != "unknown")]
        lut = {k: r for k, r in tv.drop_duplicates("key").set_index("key").iterrows() if k}
        for ix, row in b[b.v_nom == v].iterrows():
            k, hit = row.key, None
            r = tv[tv.node == row.substation]  # compiler identified the OSM node (notes) -> trust it first
            if len(r):
                hit = r.iloc[0]
            elif k:
                hit = lut.get(k)
                if hit is None:  # unique prefix match ('thuannam' vs 'thuannam500'), never across numbered names
                    cand = [kk for kk in lut if len(kk) >= 4 and k.startswith(kk) and not re.search(r"\d$", k)]
                    hit = lut[cand[0]] if len(cand) == 1 else None
            if hit is not None:
                b.loc[ix, ["mva", "status", "source"]] = (hit.mva_total if hit.status == "mva" else 0.0), hit.status, \
                    f"EVN-compiled: {hit['name']} [{hit.get('confidence', '')}] | {hit.source_url}"
    # same name on several model buses (OSM duplicates): MVA only on the first, others flagged
    dup = b.mva.notna() & b.duplicated(["v_nom", "key"]) & (b.key != "")
    b.loc[dup, ["mva", "status", "source"]] = np.nan, "", "duplicate name (MVA on other bus)"
    o500, o220 = osm_ratings(b)
    for v, o in [(500, o500), (220, o220)]:
        m = (b.v_nom == v) & b.mva.isna() & b.substation.isin(o.index)
        b.loc[m, "mva"] = b.loc[m, "substation"].map(o)
        b.loc[m, ["status", "source"]] = "mva", "OSM transformer rating"
    return b


if __name__ == "__main__":
    buses = pd.read_csv(DATA / "grid" / "topology" / "buses.csv").set_index("bus")
    b = match(buses)
    b.to_csv(SM / "matched.csv")
    for v in [500, 220]:
        x = b[b.v_nom == v]
        print(f"{v} kV: {len(x)} model substation buses, named {int((x.key != '').sum())}, MVA found "
              f"{int((x.status == 'mva').sum())} (sum {x.mva.sum():.0f} MVA), off {int((x.status == 'off').sum())}; by source "
              f"{x.source.str.split(':').str[0].value_counts().to_dict()}")
    t = load_tables()
    if len(t):
        un = t[~t.key.isin(b.key) & ~t.node.isin(b.substation) & (t.status != "unknown")]
        print("table rows (with MVA/off) not matched to model:", len(un), un[["name", "v", "status"]].values.tolist())
