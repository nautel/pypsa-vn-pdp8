#!/usr/bin/env python3
"""Substation-anchored 500/220/110 kV topology of Vietnam from raw OSM (earth-osm, Overpass).

Method
- Lines: OSM ways with voltage >=110 kV; multi-voltage ways (e.g. '500000;220000') split per voltage.
  circuits = tags.circuits, else tags.cables/3, else 1.
- Connectivity from shared OSM node ids (exact): ways are split at every node shared by >=2 ways
  (T-taps at interior nodes included) and at their ends.
- A node lying inside a substation polygon (+100 m) / near a substation point (300 m) whose voltage set
  contains the line voltage (or is untagged) becomes that substation's bus <sub>_<kV>.
- Chains through non-substation degree-2 nodes are merged into one line between real buses.
  Series merge keeps exact impedance: num_parallel = min(circuits), length_eq = c_min * sum(len_i / c_i).
- Dangling ends (non-substation degree-1) snapped to nearest same-voltage substation within SNAP_KM, else
  the stub is pruned.
- Transformers at substations with several modelled voltage levels (500/220, 220/110, 500/110 if no 220).
Outputs: <DATA>/grid/topology/{buses,lines,transformers}.csv (+ lines.geojson)
Run (env pypsa-earth): python build_vn_topology.py
"""
import os
import re
from collections import defaultdict
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import geopandas as gpd  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[0] / "data"))
OUT = DATA / "grid" / "topology"
OUT.mkdir(parents=True, exist_ok=True)
LEVELS = (500, 220, 110)
VMAP = {500: 500, 230: 220, 220: 220, 115: 110, 111: 110, 110: 110}
SUB_BUF_POLY, SUB_BUF_PT = 100, 300
DEFAULT_CIRCUITS = {500: 1, 220: 2, 110: 1}  # km-weighted mode of tagged OSM ways (2026-11 extract)
SNAP_KM = {500: 5.0, 220: 3.0, 110: 2.0}  # switchyards of large plants are wide
UTM = 32648  # metric CRS for Vietnam
geod = pyproj.Geod(ellps="WGS84")


def kv_set(s):
    out = set()
    for x in re.split(r"[;,/]", str(s)):
        x = x.strip().lower().replace("kv", "000")
        try:
            v = VMAP.get(int(float(x)) // 1000)
        except ValueError:
            continue
        if v:
            out.add(v)
    return out


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def glen_km(coords):
    lon, lat = zip(*coords)
    return geod.line_length(lon, lat) / 1e3


# ---------------- load OSM ----------------
L = pd.concat([gpd.read_file(DATA / "osm/out/out/VN_line.geojson"),
               gpd.read_file(DATA / "osm/out/out/VN_cable.geojson")], ignore_index=True)  # + underground/submarine
L = L[L.geom_type == "LineString"].copy()
S = gpd.read_file(DATA / "osm/out/out/VN_substation.geojson")

L["kvs"] = L["tags.voltage"].apply(kv_set)
L["circ_tag"] = L["tags.circuits"].apply(num)
L["cab"] = L["tags.cables"].apply(num)
L = L[L.apply(lambda w: len(w.refs) == len(w.geometry.coords), axis=1)]

# infer voltage of untagged ways from tagged ways sharing their end nodes (iterative)
L["kv_src"] = np.where(L.kvs.apply(len) > 0, "tag", "")
for _ in range(10):
    node_kv = defaultdict(set)
    for w in L[L.kvs.apply(len) > 0].itertuples():
        for r in w.refs:
            node_kv[r] |= w.kvs
    todo = L.kvs.apply(len) == 0
    inf = L[todo].refs.apply(lambda rf: node_kv.get(rf[0], set()) | node_kv.get(rf[-1], set()))
    ok = inf.apply(len) == 1
    if not ok.any():
        break
    L.loc[inf[ok].index, "kvs"] = inf[ok]
    L.loc[inf[ok].index, "kv_src"] = "inferred"
km_of = lambda df: sum(glen_km(list(g.coords)) for g in df.geometry)  # noqa: E731
untagged_km = km_of(L[L.kvs.apply(len) == 0])
inferred_km = km_of(L[L.kv_src == "inferred"])

recs = []  # one record per (way, voltage)
for w in L[L.kvs.apply(len) > 0].itertuples():
    coords, refs = list(w.geometry.coords), list(w.refs)
    nv = len(w.kvs)
    tagged = w.circ_tag == w.circ_tag or (w.cab == w.cab and w.cab >= 3)
    c = w.circ_tag if w.circ_tag == w.circ_tag else (w.cab // 3 if tagged else 1)
    c = max(1.0, c // nv) if nv > 1 else max(1.0, c)
    for v in w.kvs:
        # untagged ways: most common circuit count of tagged OSM ways at that voltage (VN: 220 kV mostly double)
        recs.append((str(w.id), v, c if tagged else DEFAULT_CIRCUITS[v], refs, coords, w._asdict().get("tags.name")))
raw_ckm = defaultdict(float)
for _, v, c, _, coords, _ in recs:
    raw_ckm[v] += glen_km(coords) * c

# ---------------- substations ----------------
S["kvs"] = S["tags.voltage"].apply(kv_set)
name_kv = S["tags.name"].fillna("").str.findall(r"(\d{3})\s*[kK][vV]").apply(lambda xs: {VMAP[int(x)] for x in xs if int(x) in VMAP})
S["kvs"] = [a | b for a, b in zip(S.kvs, name_kv)]  # OSM voltage tag often omits the top level ("TBA 500kV X" tagged 220000)
S["sid"] = "S" + S["id"].astype(str)
S_m = S.to_crs(UTM)
buf = np.where(S_m.geom_type == "Point", SUB_BUF_PT, SUB_BUF_POLY)
S_buf = gpd.GeoDataFrame(S[["sid", "kvs", "tags.name", "tags.substation"]], geometry=S_m.buffer(buf), crs=UTM)
S_cent = S_m.geometry.centroid.to_crs(4326)
S["lon"], S["lat"] = S_cent.x, S_cent.y

# ---------------- node graph per voltage ----------------
node_xy, use = {}, defaultdict(int)
for _, v, _, refs, coords, _ in recs:
    for i, (r, xy) in enumerate(zip(refs, coords)):
        node_xy[r] = xy
        use[(r, v)] += 1 if 0 < i < len(refs) - 1 else 2  # ends always key
key = {k for k, n in use.items() if n >= 2}

kn = pd.DataFrame([(r, v) for r, v in key], columns=["ref", "kv"])
kn_g = gpd.GeoDataFrame(kn, geometry=[Point(node_xy[r]) for r in kn.ref], crs=4326).to_crs(UTM)
j = gpd.sjoin(kn_g, S_buf, how="left", predicate="within")
j = j[j.apply(lambda r: isinstance(r.kvs, set) and (len(r.kvs) == 0 or r.kv in r.kvs), axis=1)]
cent = S_m.set_index(S.sid).geometry.centroid
j["d"] = j.geometry.distance(gpd.GeoSeries(cent.reindex(j.sid).values, index=j.index, crs=UTM))
node2sub = j.sort_values("d").drop_duplicates(["ref", "kv"]).set_index(["ref", "kv"]).sid.to_dict()


def bus_of(r, v):
    s = node2sub.get((r, v))
    return f"{s}_{v}" if s else f"N{r}_{v}"


G = nx.MultiGraph()
for wid, v, c, refs, coords, name in recs:
    cut = [i for i, r in enumerate(refs) if (r, v) in key]
    for a, b in zip(cut[:-1], cut[1:]):
        u, w_ = bus_of(refs[a], v), bus_of(refs[b], v)
        if u == w_:
            continue
        ln = glen_km(coords[a:b + 1])
        G.add_edge(u, w_, kv=v, circuits=c, length=ln, leq=ln / c, ways={wid}, name=name)
for n in G.nodes:
    G.nodes[n]["kv"] = int(n.rsplit("_", 1)[1])
    G.nodes[n]["sub"] = n.startswith("S")


def ref_xy(n):
    return node_xy[int(n[1:].rsplit("_", 1)[0])]


# ---------------- snap dangling ends (OSM gaps) to nearby same-voltage substations ----------------
sub_pts = defaultdict(list)
for s in S.itertuples():
    for v in (s.kvs or set(LEVELS)):
        sub_pts[v].append((s.sid, s.lon, s.lat))
snapped = 0
for n in [n for n in list(G.nodes) if not G.nodes[n]["sub"] and G.degree(n) == 1]:
    v = G.nodes[n]["kv"]
    x, y = ref_xy(n)
    cand = sub_pts.get(v, [])
    if not cand:
        continue
    d = [geod.inv(x, y, lo, la)[2] / 1e3 for _, lo, la in cand]
    i = int(np.argmin(d))
    if d[i] <= SNAP_KM[v]:
        target = f"{cand[i][0]}_{v}"
        if target in G:
            nx.contracted_nodes(G, target, n, self_loops=False, copy=False)
        else:
            nx.relabel_nodes(G, {n: target}, copy=False)
        G.nodes[target].update(kv=v, sub=True)
        snapped += 1


# ---------------- reduce: parallel + series equivalents through non-substation nodes ----------------
def par(edges):
    return {"kv": edges[0]["kv"], "circuits": sum(e["circuits"] for e in edges),
            "leq": 1 / sum(1 / e["leq"] for e in edges), "length": max(e["length"] for e in edges),
            "ways": set().union(*[e["ways"] for e in edges]), "name": next((e["name"] for e in edges if e["name"]), None)}


merged = 0
changed = True
while changed:
    changed = False
    for n in [n for n in list(G.nodes) if not G.nodes[n]["sub"]]:
        if n not in G:
            continue
        nbs = set(G.neighbors(n)) - {n}
        if len(nbs) != 2:
            continue
        a, b = nbs
        ea, eb = par(list(G[n][a].values())), par(list(G[n][b].values()))
        G.add_edge(a, b, kv=ea["kv"], circuits=min(ea["circuits"], eb["circuits"]), leq=ea["leq"] + eb["leq"],
                   length=ea["length"] + eb["length"], ways=ea["ways"] | eb["ways"], name=ea["name"] or eb["name"])
        G.remove_node(n)
        merged += 1
        changed = True

# tiny dangling stubs (< 0.5 km) are digitisation artefacts; longer ones end at unmapped substations -> keep
pruned = 0
while True:
    stubs = [n for n in G.nodes if not G.nodes[n]["sub"] and G.degree(n) == 1
             and next(iter(G.edges(n, data=True)))[2]["length"] < 0.5]
    if not stubs:
        break
    G.remove_nodes_from(stubs)
    pruned += len(stubs)
G.remove_edges_from([(u, v, k) for u, v, k in G.edges(keys=True) if u == v])
G.remove_nodes_from([n for n in list(G.nodes) if G.degree(n) == 0 and not G.nodes[n]["sub"]])

# islands: drop fragments without any substation; connect the rest to the main grid (flagged 'inferred')
ROUTE_FACTOR, MAX_CONNECT_KM = 1.25, 30.0


def islands():
    H = nx.Graph(G)
    sid_lv = defaultdict(list)
    for n in H.nodes:
        if G.nodes[n]["sub"]:
            sid_lv[n.rsplit("_", 1)[0]].append(n)
    for ns in sid_lv.values():  # transformers bind voltage levels of one substation
        H.add_edges_from(zip(ns[:-1], ns[1:]))
    return sorted(nx.connected_components(H), key=len, reverse=True)


dropped_km = 0.0
for c in islands()[1:]:
    if not any(G.nodes[n]["sub"] for n in c):
        dropped_km += sum(d["length"] for _, _, d in G.subgraph(c).edges(data=True))
        G.remove_nodes_from(c)

inferred = []
for _ in range(200):
    comps = islands()
    if len(comps) == 1:
        break
    main = comps[0]
    mxy = {m: (ref_xy(m) if not G.nodes[m]["sub"] else tuple(S.set_index("sid").loc[m.rsplit("_", 1)[0], ["lon", "lat"]]))
           for m in main}
    best = None
    for c in comps[1:]:
        for n in c:
            v = G.nodes[n]["kv"]
            xy = ref_xy(n) if not G.nodes[n]["sub"] else tuple(S.set_index("sid").loc[n.rsplit("_", 1)[0], ["lon", "lat"]])
            cand = [m for m in main if G.nodes[m]["kv"] == v]
            if not cand:
                continue
            d = np.asarray(geod.inv([xy[0]] * len(cand), [xy[1]] * len(cand), [mxy[m][0] for m in cand], [mxy[m][1] for m in cand])[2]) / 1e3
            i = int(np.argmin(d))
            if best is None or d[i] < best[0]:
                best = (d[i], n, cand[i], v)
    if best is None or best[0] > MAX_CONNECT_KM:
        break
    d, n, m, v = best
    ln = max(d * ROUTE_FACTOR, 0.1)
    G.add_edge(n, m, kv=v, circuits=1, length=ln, leq=ln, ways={"inferred"}, name="inferred connection")
    inferred.append((n, m, v, round(ln, 2)))

# ---------------- outputs ----------------
sub_info = S.set_index("sid")
rows = []
for n, d in G.nodes(data=True):
    if d["sub"]:
        sid = n.rsplit("_", 1)[0]
        s = sub_info.loc[sid]
        rows.append((n, d["kv"], s.lon, s.lat, sid, s["tags.name"], s["tags.substation"], "substation"))
    else:
        x, y = ref_xy(n)
        rows.append((n, d["kv"], x, y, "", None, None, "line_end" if G.degree(n) == 1 else "junction"))
buses = pd.DataFrame(rows, columns=["bus", "v_nom", "x", "y", "substation", "name", "osm_substation_tag", "type"])

lines = pd.DataFrame([
    {"bus0": u, "bus1": v, "v_nom": d["kv"], "num_parallel": d["circuits"], "length_km": round(d["length"], 3),
     "length_eq_km": round(d["leq"] * d["circuits"], 3), "inferred": d["ways"] == {"inferred"}, "osm_ways": ";".join(sorted(d["ways"])), "name": d["name"]}
    for u, v, d in G.edges(data=True)])
lines.index = [f"L{i}" for i in range(len(lines))]

tr = []
for sid, g in buses[buses.type == "substation"].groupby("substation"):
    lv = sorted(g.v_nom.unique(), reverse=True)
    for hi, lo in zip(lv[:-1], lv[1:]):
        tr.append({"bus0": f"{sid}_{hi}", "bus1": f"{sid}_{lo}", "v0": hi, "v1": lo})
trafo = pd.DataFrame(tr)

buses.to_csv(OUT / "buses.csv", index=False)
lines.to_csv(OUT / "lines.csv")
trafo.to_csv(OUT / "transformers.csv", index=False)

# ---------------- report ----------------
print(f"voltage inferred for {inferred_km:.0f} km; still untagged (excluded): {untagged_km:.0f} km")
print("raw circuit-km by kV (before topology):", {k: round(v) for k, v in raw_ckm.items()})
print(f"dropped substation-less fragments: {dropped_km:.0f} km; inferred connections: {len(inferred)} "
      f"({sum(x[3] for x in inferred):.0f} km) by kV {pd.Series([x[2] for x in inferred]).value_counts().to_dict() if inferred else {}}")
print(f"snapped dangling ends: {snapped}, pruned stub nodes: {pruned}, merged chain nodes: {merged}")
H = nx.Graph()
H.add_nodes_from(buses.bus)
H.add_edges_from(zip(lines.bus0, lines.bus1))
H.add_edges_from(zip(trafo.bus0, trafo.bus1)) if len(trafo) else None
comps = sorted(nx.connected_components(H), key=len, reverse=True)
main = comps[0]
off = {500: (11752, 43), 220: (20478, 161), 110: (23725, None)}
rep = []
for v in LEVELS:
    b, l = buses[buses.v_nom == v], lines[lines.v_nom == v]
    rep.append({"kV": v, "sub_buses": int((b.type == "substation").sum()), "named": int(b.name.notna().sum()),
                "junctions": int((b.type == "junction").sum()), "line_ends": int((b.type == "line_end").sum()), "lines": len(l), "route_km": round(l.length_km.sum()),
                "circuit_km": round((l.length_km * l.num_parallel).sum()), "official_km": off[v][0],
                "official_subs": off[v][1], "in_main_island": len(set(b.bus) & main)})
rep = pd.DataFrame(rep).set_index("kV")
rep["circuit_km/official"] = (rep.circuit_km / rep.official_km).round(2)
print(rep.to_string())
print(f"transformers: {len(trafo)} {trafo.assign(p=trafo.v0.astype(str) + '/' + trafo.v1.astype(str)).p.value_counts().to_dict() if len(trafo) else ''}")
print(f"islands: {len(comps)}; main island {len(main)}/{len(buses)} buses; next sizes {[len(c) for c in comps[1:12]]}")
rep.to_csv(OUT / "summary_vs_official.csv")
