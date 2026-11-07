#!/usr/bin/env python3
"""Compare built OSM topology with official EVN/MOIT grid statistics (end-2024).

Official (EVN Annual Report 2024-25 p8; MOIT/Cục Điện lực 1/2026 p7):
  500 kV: 11,752 km, 48,750 MVA, ~42-43 substations (end-2025)
  220 kV: 20,478 km (EVN) / 21,193 km (MOIT), 82,375 / 84,565 MVA, 161 EVNNPT substations
  110 kV: 23,725 km, 84,088 MVA
EVN 'km' is likely circuit-km (inferred), so OSM is compared both as route-km and circuit-km.
Run: python check_grid_vs_official.py [tol]
"""
import os
import sys
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import networkx as nx  # noqa: E402
import pandas as pd  # noqa: E402

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[0] / "data"))
TOL = sys.argv[1] if len(sys.argv) > 1 else "1000"
B = DATA / "grid" / f"tol{TOL}" / "base"
OFFICIAL = pd.DataFrame(
    {"km_official": [11752, 20478, 23725], "MVA_official": [48750, 82375, 84088], "subs_official": [43, 161, None]},
    index=[500, 220, 110],
)

buses = pd.read_csv(B / "all_buses_build_network.csv")
lines = pd.read_csv(B / "all_lines_build_network.csv")
trafo = pd.read_csv(B / "all_transformers_build_network.csv")
print("bus cols:", list(buses.columns)[:20])
print("line cols:", list(lines.columns)[:20])

buses["kV"] = (buses.voltage / 1000).round().astype(int)
lines["kV"] = (lines.voltage / 1000).round().astype(int)
lines["km"] = lines.length / 1000 if lines.length.max() > 5000 else lines.length
lines["circuit_km"] = lines.km * lines.circuits

rows = []
for kv in [500, 220, 110]:
    b, l = buses[buses.kV == kv], lines[lines.kV == kv]
    rows.append({"kV": kv, "buses": len(b), "substation_buses": int((b.symbol == "substation").sum()) if "symbol" in b else None,
                 "lines": len(l), "route_km": round(l.km.sum()), "circuit_km": round(l.circuit_km.sum())})
r = pd.DataFrame(rows).set_index("kV").join(OFFICIAL)
r["circuit_km/official"] = (r.circuit_km / r.km_official).round(2)
r["route_km/official"] = (r.route_km / r.km_official).round(2)
print("\n", r.to_string())
print("\nother voltages (kV: lines/km):", lines[~lines.kV.isin([500, 220, 110])].groupby("kV").km.agg(["size", "sum"]).round(0).to_dict("index"))
print("transformers:", len(trafo), trafo.assign(p=(trafo.voltage_bus0 / 1e3).round().astype(int).astype(str) + "/" +
                                                 (trafo.voltage_bus1 / 1e3).round().astype(int).astype(str)).p.value_counts().head(8).to_dict())

G = nx.Graph()
G.add_nodes_from(buses.bus_id)
G.add_edges_from(zip(lines.bus0, lines.bus1))
G.add_edges_from(zip(trafo.bus0, trafo.bus1))
comps = sorted(nx.connected_components(G), key=len, reverse=True)
print(f"\nconnected components: {len(comps)}; largest {len(comps[0])} of {G.number_of_nodes()} buses;"
      f" sizes of next 10: {[len(c) for c in comps[1:11]]}")
main = comps[0]
for kv in [500, 220, 110]:
    ids = set(buses[buses.kV == kv].bus_id)
    print(f"  {kv} kV buses in main component: {len(ids & main)}/{len(ids)}")
