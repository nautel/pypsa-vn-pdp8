#!/usr/bin/env python3
"""Vietnam generating units from GEM trackers -> <DATA>/plants/vn_units_gem.csv

Unified columns: source, plant, unit, carrier, tech, capacity_mw, status, start_year, retired_year, lat, lon
carrier in {coal, gas, oil, hydro, ror, PHS, onwind, offwind, solar, solar_rooftop, biomass}
Run (env pypsa-earth): python build_vn_plants.py [year]   -> also prints capacity in operation at end of <year>
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[0] / "data"))
GEM = DATA / "plants" / "gem"
YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
VN = ("Vietnam", "Viet Nam")


def read(fn, sheets, ren, src):
    out = []
    for s in sheets:
        df = pd.read_excel(GEM / fn, sheet_name=s)
        ccol = next(c for c in df.columns if str(c).startswith("Country/Area"))
        df = df[df[ccol].isin(VN)].rename(columns=ren)
        df["source"] = f"{src}:{s}"
        out.append(df)
    return pd.concat(out, ignore_index=True)


cols = ["source", "plant", "unit", "carrier", "tech", "capacity_mw", "status", "start_year", "retired_year", "lat", "lon"]
base = {"Capacity (MW)": "capacity_mw", "Status": "status", "Latitude": "lat", "Longitude": "lon"}
parts = []

# coal
d = read("Global-Coal-Plant-Tracker-July-2026.xlsx", ["Units"],
         {**base, "Plant name": "plant", "Unit name": "unit", "Start year": "start_year",
          "Retired year": "retired_year", "Combustion technology": "tech"}, "GCPT")
d["carrier"] = "coal"
parts.append(d)

# oil & gas
d = read("Global-Oil-and-Gas-Plant-Tracker-GOGPT-January-2026.xlsx", ["Gas & Oil Units", "sub-threshold units"],
         {**base, "Plant name": "plant", "Unit name": "unit", "Start year": "start_year",
          "Retired year": "retired_year", "Turbine/Engine Technology": "tech"}, "GOGPT")
fuel = d["Fuel"].astype(str).str.lower()
d["carrier"] = np.where(fuel.str.contains("gas|lng"), "gas", "oil")
parts.append(d)

# hydro (storage / run-of-river / pumped storage)
d = read("Global-Hydropower-Tracker-March-2026.xlsx", ["Data", "Below Threshold"],
         {**base, "Project Name": "plant", "Start Year": "start_year", "Retired Year": "retired_year",
          "Technology Type": "tech"}, "GHPT")
# cross-border projects: keep only the Vietnam share
c1 = d["Country/Area 1"].isin(VN)
d["capacity_mw"] = np.where(d["Country/Area 2"].notna(),
                            np.where(c1, d["Country/Area 1 Capacity (MW)"], d["Country/Area 2 Capacity (MW)"]),
                            d["capacity_mw"])
t = d["tech"].astype(str).str.lower()
d["carrier"] = np.select([t.str.contains("pumped"), t.str.contains("run-of-river")], ["PHS", "ror"], "hydro")
d["unit"] = ""
parts.append(d)

# wind
d = read("Global-Wind-Power-Tracker-February-2026.xlsx", ["Data", "Below Threshold"],
         {**base, "Project Name": "plant", "Phase Name": "unit", "Start year": "start_year",
          "Retired year": "retired_year", "Installation Type": "tech"}, "GWPT")
d["carrier"] = np.where(d["tech"].astype(str).str.lower().str.contains("offshore"), "offwind", "onwind")
parts.append(d)

# solar utility + distributed (<1 MW, no coordinates)
d = read("Global-Solar-Power-Tracker-February-2026.xlsx", ["Utility-Scale (1 MW+)"],
         {**base, "Project Name": "plant", "Phase Name": "unit", "Start year": "start_year",
          "Retired year": "retired_year", "Technology Type": "tech"}, "GSPT")
d["carrier"] = "solar"
parts.append(d)
d = read("Global-Solar-Power-Tracker-February-2026.xlsx", ["Distributed (<1 MW)"], base, "GSPT")
d["carrier"], d["plant"] = "solar_rooftop", "distributed <1MW (aggregate)"
parts.append(d)

# bioenergy
d = read("Global-Bioenergy-Power-Tracker-GBPT-V3.xlsx", ["Data"],
         {**base, "Project Name": "plant", "Unit Name": "unit", "Start Year": "start_year",
          "Retired Year": "retired_year", "Fuel": "tech"}, "GBPT")
d["carrier"] = "biomass"
parts.append(d)

u = pd.concat([p.reindex(columns=cols) for p in parts], ignore_index=True)
u["status"] = u["status"].astype(str).str.strip().str.lower()
for c in ["capacity_mw", "start_year", "retired_year", "lat", "lon"]:
    u[c] = pd.to_numeric(u[c], errors="coerce")
u = u[u.capacity_mw > 0]
out = DATA / "plants" / "vn_units_gem.csv"
u.to_csv(out, index=False)
print(f"{len(u)} units -> {out}")
print(pd.crosstab(u.carrier, u.status, values=u.capacity_mw, aggfunc="sum").round(0).fillna(0).astype(int).to_string())

# in operation at end of YEAR
built = u.status.isin(["operating", "retired", "mothballed"]) & (u.start_year.isna() | (u.start_year <= YEAR))
alive = u.retired_year.isna() | (u.retired_year > YEAR)
op = u[built & alive]
s = op.groupby("carrier").agg(units=("capacity_mw", "size"), MW=("capacity_mw", "sum"),
                              no_start_year=("start_year", lambda x: int(x.isna().sum())),
                              no_coords=("lat", lambda x: int(x.isna().sum())))
s.loc["TOTAL"] = s.sum()
print(f"\nIn operation end-{YEAR} (start_year<={YEAR} or missing; not retired):")
print(s.round(0).astype(int).to_string())
s.to_csv(DATA / "plants" / f"vn_capacity_gem_{YEAR}.csv")
