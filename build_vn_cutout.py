#!/usr/bin/env python3
"""Minimal ERA5 cutout for Vietnam (atlite) -> <DATA>/cutouts/vietnam-<year>-era5.nc

Only what the grid simulation needs: wind (onshore/near-shore offshore), influx + temperature (PV).
Hydro is calibrated with monthly Ember/EVN generation instead of runoff -> no runoff/basins needed.
Bounds: VN mainland + near-shore sea. 0.25 deg = ERA5 native grid.
Run (env pypsa-earth):  python build_vn_cutout.py 2024
Needs ~/.cdsapirc + accepted ERA5 single-levels licence.
"""
import os
import logging
import sys
from pathlib import Path

import atlite

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[0] / "data"))
YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
OUT = DATA / "cutouts" / f"vietnam-{YEAR}-era5.nc"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

cutout = atlite.Cutout(
    path=OUT,
    module="era5",
    x=slice(101.75, 110.75),
    y=slice(7.75, 23.75),
    dx=0.25,
    dy=0.25,
    time=str(YEAR),
)
cutout.prepare(features=["wind", "influx", "temperature"], monthly_requests=False, concurrent_requests=False,
               tmpdir=DATA / "tmp")
print(cutout)
print("->", OUT)
