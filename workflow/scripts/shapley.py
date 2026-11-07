#!/usr/bin/env python3
"""Shapley decomposition of the PDP8 - least-cost gap.

Players: lng, offwind, nuclear, ac, rest (plan groups released to optimisation). v(S) = cost of PDP8 with the groups in
S released (results_v5/2035_pdp8_vn_rel_<S>), v(empty) = PDP8, v(all) = least cost. Saving of releasing S:
d(S) = v(empty) - v(S). Shapley value phi_i = sum_S |S|!(n-|S|-1)!/n! [d(S+i) - d(S)]; also min/max of the marginal
contribution of each group over all 120 release orders, and the sequential (v4-style) attribution for 2035 and 2040.
Output: <FIG_DIR>/shapley_2035.csv, decomposition_seq_<year>.csv
Run: RES_DIR=.../results_v6 python workflow/scripts/shapley.py
"""
import itertools
import json
import math
import os
from pathlib import Path

import pandas as pd

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
RES = Path(os.environ.get("RES_DIR", DATA / "expansion" / "results_v6"))
OUT = Path(os.environ.get("FIG_DIR", DATA / "figures" / "expansion_v5"))
OUT.mkdir(parents=True, exist_ok=True)
G = ["lng", "offwind", "nuclear", "ac", "rest"]


def cost(y, run):
    f = RES / f"{y}_{run}_summary.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    return d["cost_bnUSD_per_year"]["total_excl_VOLL"] + d["cost_bnUSD_per_year"].get("unserved_energy_at_VOLL", 0.0)


def v(y, S):
    S = [g for g in G if g in S]
    if not S:
        return cost(y, "pdp8_vn")
    if len(S) == len(G):
        return cost(y, "opt_vn")
    return cost(y, "pdp8_vn_rel_" + "-".join(S))


rows = []
y = 2035
V = {frozenset(S): v(y, S) for k in range(len(G) + 1) for S in itertools.combinations(G, k)}
missing = [sorted(S) for S, c in V.items() if c is None]
if missing:
    print(f"{len(missing)} subsets missing, e.g. {missing[:3]}")
else:
    base = V[frozenset()]
    d = {S: base - c for S, c in V.items()}
    n = len(G)
    for i in G:
        phi, margs = 0.0, []
        for k in range(n):
            for S in itertools.combinations([g for g in G if g != i], k):
                S = frozenset(S)
                mc = d[S | {i}] - d[S]
                phi += math.factorial(len(S)) * math.factorial(n - len(S) - 1) / math.factorial(n) * mc
                margs.append(mc)
        rows.append({"group": i, "shapley_bnUSD": phi, "share_pct": 100 * phi / d[frozenset(G)],
                     "min_marginal_bnUSD": min(margs), "max_marginal_bnUSD": max(margs),
                     "alone_bnUSD": d[frozenset({i})], "last_bnUSD": d[frozenset(G)] - d[frozenset(G) - {i}]})
    T = pd.DataFrame(rows)
    T["gap_bnUSD"] = d[frozenset(G)]
    T.round(3).to_csv(OUT / "shapley_2035.csv", index=False)
    print(T.round(2).to_string(index=False))
for y in [2035, 2040]:
    seq, prev, out = [], v(y, []), []
    for k in range(1, len(G) + 1):
        c = v(y, G[:k])
        if c is None or prev is None:
            break
        out.append({"year": y, "group": G[k - 1], "saving_bnUSD": prev - c})
        prev = c
    if out:
        S = pd.DataFrame(out)
        S["share_pct"] = 100 * S.saving_bnUSD / S.saving_bnUSD.sum()
        S.round(3).to_csv(OUT / f"decomposition_seq_{y}.csv", index=False)
        print(S.round(2).to_string(index=False))

# v6: first/last release bounds (2040; 2035 under the plan's emission ceiling)
rows = []
for y, base_, full_, pre in [(2040, "pdp8_vn", "opt_vn", "_vn"), (2035, "pdp8_vn_co2plan", "opt_vn_co2plan", "_vn_ceil")]:
    v0, vN = cost(y, base_), cost(y, full_)
    if v0 is None or vN is None:
        continue
    for g in G:
        f_, l_ = cost(y, f"pdp8{pre}_first_{g}"), cost(y, f"pdp8{pre}_last_{g}")
        if f_ is None or l_ is None:
            continue
        rows.append({"case": "2040" if y == 2040 else "2035 ceiling", "group": g, "first_bnUSD": v0 - f_,
                     "last_bnUSD": l_ - vN, "gap_bnUSD": v0 - vN})
if rows:
    B = pd.DataFrame(rows)
    B.round(3).to_csv(OUT / "bounds.csv", index=False)
    print(B.round(2).to_string(index=False))
