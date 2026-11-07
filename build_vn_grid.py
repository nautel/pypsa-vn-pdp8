#!/usr/bin/env python3
"""Vietnam 500/220/110 kV topology from OSM, using PyPSA-Earth's tested OSM cleaning/building functions.

Inputs : <DATA>/osm/out/out/VN_{line,cable,substation,generator}.geojson (earth-osm, Overpass)
         <DATA>/shapes/gadm41_VNM_0.json
Outputs: <DATA>/grid/tol<T>/{clean,base}/...  (buses, lines, transformers as csv/geojson)
Run (env pypsa-earth): python build_vn_grid.py [group_tolerance_m=1000]
"""
import os
import shutil
import sys
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())

import geopandas as gpd  # noqa: E402

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[0] / "data"))
REPO = Path(os.environ.get("PYPSA_EARTH_DIR", Path(__file__).resolve().parents[1] / "pypsa-asean"))
sys.path.insert(0, str(REPO / "scripts"))
os.chdir(REPO)  # PyPSA-Earth helpers resolve configs relative to repo root

from build_osm_network import built_network  # noqa: E402
from clean_osm_data import clean_data  # noqa: E402

class AttrDict(dict):
    """dict with attribute access (mimics snakemake.input/output)."""
    __getattr__ = dict.__getitem__


TOL = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
GEO, DIST = "EPSG:4326", "EPSG:3857"
W = DATA / "grid" / f"tol{TOL}"
for d in ["raw", "clean", "base", "shapes"]:
    (W / d).mkdir(parents=True, exist_ok=True)

# raw OSM (earth-osm output == PyPSA-Earth download_osm_data output, only renamed)
src = DATA / "osm" / "out" / "out"
raw = {}
for a, f in [("lines", "line"), ("cables", "cable"), ("substations", "substation"), ("generators", "generator")]:
    raw[a] = W / "raw" / f"all_raw_{a}.geojson"
    shutil.copy(src / f"VN_{f}.geojson", raw[a])

# shapes: country + extended (land + 30 km sea, for near-shore/offshore assets)
vn = gpd.read_file(DATA / "shapes" / "gadm41_VNM_0.json").to_crs(GEO)
country = gpd.GeoDataFrame({"name": ["VN"]}, geometry=[vn.union_all()], crs=GEO)
country_fn = W / "shapes" / "country_shapes.geojson"
country.to_file(country_fn, driver="GeoJSON")
ext_shape = country.to_crs(DIST).buffer(30_000).to_crs(GEO).iloc[0]

opts = {
    "use_custom_lines": "OSM_only", "path_custom_lines": False,
    "use_custom_substations": "OSM_only", "path_custom_substations": False,
    "use_custom_cables": "OSM_only", "path_custom_cables": False,
}
clean = {
    "generators": W / "clean" / "all_clean_generators.geojson",
    "generators_csv": W / "clean" / "all_clean_generators.csv",
    "lines": W / "clean" / "all_clean_lines.geojson",
    "substations": W / "clean" / "all_clean_substations.geojson",
}
import clean_osm_data  # noqa: E402

clean_osm_data.input_files = {k: str(v) for k, v in raw.items()}  # load_network_data reads module global
clean_data(
    {k: str(v) for k, v in raw.items()},
    {k: str(v) for k, v in clean.items()},
    ext_shape, GEO, DIST, opts,
    ext_country_shapes=None,
    names_by_shapes=False,
    tag_substation="",  # keep ALL substation types (VN 110 kV subs are tagged distribution/industrial/...)
    threshold_voltage=100_000,  # keep 110 kV and above
    add_line_endings=True,
    generator_name_method="OSM",
)

import build_osm_network  # noqa: E402

build_osm_network.geo_crs, build_osm_network.distance_crs = GEO, DIST  # module globals expected by helpers

base = {k: str(W / "base" / f"all_{k}_build_network.csv") for k in ["lines", "converters", "transformers"]}
base["substations"] = str(W / "base" / "all_buses_build_network.csv")
for k in ["lines", "converters", "transformers"]:
    base[f"{k}_geo"] = str(W / "base" / f"all_{k}_build_network.geojson")
base["substations_geo"] = str(W / "base" / "all_buses_build_network.geojson")

built_network(
    AttrDict({"substations": str(clean["substations"]), "lines": str(clean["lines"]),
     "generators": str(clean["generators"]), "country_shapes": str(country_fn)}),
    AttrDict(base),
    {"group_close_buses": True, "group_tolerance_buses": TOL,
     "split_overpassing_lines": True, "overpassing_lines_tolerance": 1, "force_ac": False},
    ["VN"], GEO, DIST, force_ac=False,
)
print("->", W)
