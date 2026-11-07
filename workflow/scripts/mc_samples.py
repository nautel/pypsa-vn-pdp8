#!/usr/bin/env python3
"""Monte Carlo samples of nine jointly varied inputs (Latin hypercube, scipy.stats.qmc, as in PyPSA-Earth).

Two optimised Latin hypercubes of 16 samples each (seeds 42 and 43) are combined to 32 samples; values are uniform in
RANGES (environment variables of model.py). Written to <VN_DATA>/expansion/<RES_SUB>/mc_samples.csv by run_set.py.
Run: python workflow/scripts/mc_samples.py <output.csv>
"""
import sys

import pandas as pd
from scipy.stats import qmc

RANGES = {"LNG_USD_MMBTU": (10.0, 20.0), "SOLAR_CAPEX_X": (0.8, 1.2), "ONWIND_CAPEX_X": (0.85, 1.25),
          "BAT_CAPEX_X": (0.7, 1.5), "OFFWIND_CAPEX_X": (0.7, 1.2), "NUC_CAPEX_X": (0.9, 1.6), "DISCOUNT": (0.06, 0.10),
          "DEMAND_X": (0.95, 1.10), "HYDRO_TWH": (80.0, 110.0)}


def samples(seeds=(42, 43), n=16):
    lo, hi = zip(*RANGES.values())
    parts = [pd.DataFrame(qmc.scale(qmc.LatinHypercube(d=len(RANGES), seed=s, optimization="random-cd").random(n), lo, hi),
                          columns=list(RANGES)).round(4) for s in seeds]
    df = pd.concat(parts, ignore_index=True)
    df.index.name = "sample"
    return df


if __name__ == "__main__":
    samples().to_csv(sys.argv[1])
