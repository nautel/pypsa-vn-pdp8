#!/usr/bin/env python3
"""Run set of the paper: every model run with its settings and dependencies (289 runs).

Importable without side effects except creating the results directory and the Monte Carlo sample file:
`jobs` is a list of (year, scenario, tag, env, deps) and `name(job)` the run name
"<year>_<scenario><tag>"; results are <VN_DATA>/expansion/<RES_SUB>/<run>{.nc,_summary.json}.
Used by the Snakemake workflow (workflow/rules/solve.smk). Standalone scheduler without Snakemake:
Run: python workflow/scripts/run_set.py [parallel_jobs=2] [threads_per_job=4]
"""
import itertools
import os
import subprocess
import sys
import time
from pathlib import Path

import mc_samples
import pandas as pd

RES_SUB = os.environ.get("RES_SUB", "results_v6")
RES = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data")) / "expansion" / RES_SUB
RES.mkdir(parents=True, exist_ok=True)
BASE = {"DAY_STEP": "4", "COSTS": "vntc", "ALLOC": "qd1509", "VRE_SRC": "gis", "RES_SUB": RES_SUB, "MODEL_V": "6"}
jobs = []  # (year, scen, tag, env, deps[list of run names])



def J(y, s, t, env=None, deps=()):
    jobs.append((y, s, t, dict(env or {}), list(deps)))


def done(name):
    return (RES / f"{name}_summary.json").exists()


# ---- 1. PDP8 (fixed plan, fast) ----
SENS_BOTH = {"_vn_dc": {"EXTRA": "dc"}, "_vn_hsr": {"EXTRA": "hsr"}, "_vn_dchsr": {"EXTRA": "dc+hsr"},
             "_vn_high": {"PLAN_VARIANT": "high"}, "_vn_co2plan": {"CO2_CAP": "plan"}}
SENS_2035 = {"_vn_lnglow": {"LNG_USD_MMBTU": "12"}, "_vn_dry": {"HYDRO_TWH": "80"}, "_vn_rm115": {"RM": "1.15"},
             "_vn_rm120": {"RM": "1.20"}, "_vn_conn": {"CONN_COST": "100"}, "_vn_corr": {"CORR_DERATE": "0.5"},
             "_vn_nores": {"OPRES": "0"}, "_vn_wacc10": {"DISCOUNT": "0.10"}, "_vn_bat150": {"BAT_CAPEX_X": "1.5"},
             "_vn_off70": {"OFFWIND_CAPEX_X": "0.7"}, "_vn_nuc150": {"NUC_CAPEX_X": "1.5"},
             "_vn_phs150": {"PHS_CAPEX_X": "1.5"}, "_vn_static": {"CRM": "static"},
             "_vn_line2": {"LINE_CAPEX_X": "2"}, "_vn_commit25": {"COMMITTED": "2025"},
             "_vn_hydfree": {"HYDRO_MONTHLY": "0"}}
OPT_ONLY_2035 = {"_vn_pv55": {"BUILD_SOLAR_GW": "5.5"}, "_vn_batbuild": {"BAT_BUILD_GW": "3"},
                 "_vn_planrange": {"PLAN_RANGE": "1", "PDP8_TAG": "_vn"}}
for y in [2035, 2040]:
    J(y, "pdp8", "_vn")
    J(y, "pdp8", "_vn_lngqc", {"LNG_QC": "0.41"})
    for t, e in SENS_BOTH.items():
        J(y, "pdp8", t, e)
for t, e in SENS_2035.items():
    J(2035, "pdp8", t, e)
# ---- 2. least cost: central first ----
for y in [2035, 2040]:
    J(y, "opt", "_vn", {}, [f"{y}_pdp8_vn"])
for y in [2035, 2040]:
    J(y, "opt", "_vn_co2half", {"CO2_CAP": "pdp8*0.5", "PDP8_TAG": "_vn"}, [f"{y}_pdp8_vn"])
    for t, e in SENS_BOTH.items():
        J(y, "opt", t, e, [f"{y}_pdp8{t}"])
    J(y, "opt", "_vn_planrange", {"PLAN_RANGE": "1", "PDP8_TAG": "_vn"}, [f"{y}_pdp8_vn"])
# ---- 3. Shapley decomposition 2035: PDP8 with every subset of five groups released ----
G = ["lng", "offwind", "nuclear", "ac", "rest"]
for k in range(1, len(G)):
    for S in itertools.combinations(G, k):
        J(2035, "pdp8", "_vn_rel_" + "-".join(S), {"RELEASE": ",".join(S), "PDP8_TAG": "_vn"}, ["2035_pdp8_vn"])
# all five released = the least-cost system (2035_opt_vn)
# 2040: first/last bounds (section 8)
# ---- 4. sensitivities (2035) ----
J(2035, "opt", "_vn_co2zero", {"CO2_CAP": "0", "PDP8_TAG": "_vn"}, ["2035_pdp8_vn"])
for y in [2035, 2040]:
    J(y, "opt", "_vn_co2zero_nolim", {"CO2_CAP": "0", "BUILD_LIMIT": "0", "PDP8_TAG": "_vn"}, [f"{y}_pdp8_vn"])
for t, e in SENS_2035.items():
    J(2035, "opt", t, e, [f"2035_pdp8{t}"])
for t, e in OPT_ONLY_2035.items():
    if t != "_vn_planrange":
        J(2035, "opt", t, dict(e, PDP8_TAG="_vn"), ["2035_pdp8_vn"])
# ---- 5. near-optimal (MGA, +5 % cost), pathway 2040, temporal resolution, crossover ----
for grp in ["offwind", "lng", "nuclear", "ac"]:
    J(2035, "opt", f"_vn_mga_{grp}", {"MGA": f"{grp}:0.05", "MGA_REF": str(RES / "2035_opt_vn_summary.json"),
                                      "PDP8_TAG": "_vn"}, ["2035_opt_vn"])
J(2040, "opt", "_vn_path", {"PATH_FROM": "2035_opt_vn", "PDP8_TAG": "_vn"}, ["2035_opt_vn", "2040_pdp8_vn"])
J(2040, "pdp8", "_vn_path", {"PATH_FROM": "2035_pdp8_vn", "PDP8_TAG": "_vn"}, ["2035_pdp8_vn"])
J(2035, "pdp8", "_vn_ds2", {"DAY_STEP": "2"})
J(2035, "opt", "_vn_ds2", {"DAY_STEP": "2"}, ["2035_pdp8_vn_ds2"])
J(2035, "opt", "_vn_xo", {"CROSSOVER": "1", "PDP8_TAG": "_vn"}, ["2035_pdp8_vn"])
# ---- 6. adequacy of the fixed 2035 portfolios over weather years (full year, 3 h), regret ----
for s in ["pdp8", "opt"]:
    for wy in range(2015, 2025):
        for hy, htag in [("100", ""), ("80", "d")]:
            deps = [f"2035_{s}_vn"]  # weather years: <VN_DATA>/expansion/weather_years (weather_years.py)
            J(2035, s, f"_vn_fix_w{wy}{htag}", {"FIX_FROM": f"2035_{s}_vn", "NO_RESERVE": "1", "DAY_STEP": "1", "KEEP_OPRES": "0",
                                                "WEATHER_YEAR": str(wy), "HYDRO_TWH": hy, "OUTAGE_SEED": str(wy),
                                                "PDP8_TAG": "_vn"}, deps)


# ---- 7. Monte Carlo samples (mc_samples.py) ----
fs = RES / "mc_samples.csv"
if not fs.exists():
    mc_samples.samples().to_csv(fs)
for i, r in pd.read_csv(fs, index_col=0).iterrows():
    e = {k: str(v) for k, v in r.items()}
    J(2035, "pdp8", f"_vn_mc{i}", e)
    J(2035, "opt", f"_vn_mc{i}", e, [f"2035_pdp8_vn_mc{i}"])
# ---- 8. storage siting, plan range with the plan's lines, attribution bounds, near-optimal slacks, regret ----
J(2035, "pdp8", "_vn_storsite", {"RELEASE": "storage", "PDP8_TAG": "_vn"}, ["2035_pdp8_vn"])
for y in [2035, 2040]:
    J(y, "pdp8", "_vn_prgrid", {"RELEASE": "offwind,nuclear,rest", "PLAN_RANGE": "1", "PDP8_TAG": "_vn"}, [f"{y}_pdp8_vn"])
for g in G:  # first/last release bounds: 2040, and 2035 under the plan's emission ceiling
    rest_ = [x for x in G if x != g]
    J(2040, "pdp8", f"_vn_first_{g}", {"RELEASE": g, "PDP8_TAG": "_vn"}, ["2040_pdp8_vn"])
    J(2040, "pdp8", f"_vn_last_{g}", {"RELEASE": ",".join(rest_), "PDP8_TAG": "_vn"}, ["2040_pdp8_vn"])
    J(2035, "pdp8", f"_vn_ceil_first_{g}", {"RELEASE": g, "CO2_CAP": "plan", "PDP8_TAG": "_vn"}, ["2035_pdp8_vn"])
    J(2035, "pdp8", f"_vn_ceil_last_{g}", {"RELEASE": ",".join(rest_), "CO2_CAP": "plan", "PDP8_TAG": "_vn"}, ["2035_pdp8_vn"])
for grp in ["offwind", "lng", "nuclear", "ac"]:
    for eps, et in [("0.02", "2"), ("0.10", "10")]:
        J(2035, "opt", f"_vn_mga{et}_{grp}", {"MGA": f"{grp}:{eps}", "MGA_REF": str(RES / "2035_opt_vn_summary.json"),
                                             "PDP8_TAG": "_vn"}, ["2035_opt_vn"])
FUT = {"_ref": {}, "_dem": {"DEMAND_X": "1.11"}, "_lng": {"LNG_USD_MMBTU": "25"}, "_dry": {"HYDRO_TWH": "80"},
       "_pv": {"SOLAR_NEW_X": "0.5"}, "_coal": {"COAL_PRICE_X": "1.5"}, "_bat": {"BAT_NEW_X": "0.5"},
       "_north": {"NORTH_CORR_X": "0.5"}, "_weak": {"WEATHER_YEAR": "2022", "HYDRO_TWH": "80"}}
for s_, src in [("pdp8", "_vn"), ("opt", "_vn"), ("opt", "_vn_planrange"), ("opt", "_vn_co2plan"), ("pdp8", "_vn_prgrid")]:
    for f_, e in FUT.items():
        rel_ = {"RELEASE": "offwind,nuclear,rest"} if src == "_vn_prgrid" else {}  # rebuild the same network as the source
        J(2035, s_, f"{src}_rg{f_}", dict(e, **rel_, FIX_FROM=f"2035_{s_}{src}", NO_RESERVE="1", PDP8_TAG="_vn"), [f"2035_{s_}{src}"])
# ---- 9. benchmark of the 30-region model against 2024 operation (dispatch of the 2024 fleet) ----
for t_, e_ in {"_bench": {"GAS_QC": "0"}, "_bench_gasqc": {"GAS_QC": "0.35"},
               "_bench_hydmon": {"GAS_QC": "0.35", "HYDRO_MONTHLY": "1"}}.items():
    J(2024, "pdp8", t_, dict(e_, MODEL_V="5", DAY_STEP="1", NO_RESERVE="1", HYDRO_TWH="88.76"))
# priority: central and decomposition first, Monte Carlo before the long tail
PRIO = ["_vn", "_vn_co2plan", "_vn_planrange", "_vn_prgrid", "_vn_storsite", "_vn_co2half", "_vn_high", "_vn_rel_",
        "_vn_first_", "_vn_last_", "_vn_ceil_", "_vn_mc", "_vn_mga", "_vn_dc"]
def _rank(j):
    light = j[1] == "pdp8" and not ({"RELEASE", "FIX_FROM", "PATH_FROM"} & set(j[3]))
    fix = "FIX_FROM" in j[3]
    pr = next((i for i, p_ in enumerate(PRIO) if j[2] == p_ or (p_.endswith("_") and j[2].startswith(p_))
               or (p_ == "_vn_mc" and j[2].startswith("_vn_mc"))), len(PRIO))
    return (0 if light else (2 if fix else 1), pr)


jobs.sort(key=_rank)


def name(j):
    return f"{j[0]}_{j[1]}{j[2]}"


def ready(j):
    return all(done(d) for d in j[4])


if __name__ == "__main__":
    P = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    T = sys.argv[2] if len(sys.argv) > 2 else "4"  # solver threads per job
    log = open(RES / "run_set.log", "a")
    pending = [j for j in jobs if not done(name(j))]
    running, failed = {}, set()
    log.write(f"{time.strftime('%F %H:%M')} start: {len(jobs)} jobs, {len(pending)} pending, P={P}\n")
    log.flush()
    while pending or running:
        for nm, (pr, t0) in list(running.items()):
            if pr.poll() is not None:
                log.write(f"{time.strftime('%H:%M')} {nm} exit {pr.returncode} {(time.time() - t0) / 60:.0f} min\n")
                log.flush()
                del running[nm]
                if not done(nm):
                    failed.add(nm)
        for j in list(pending):  # drop jobs whose dependency failed
            if any(d in failed for d in j[4]):
                pending.remove(j)
                failed.add(name(j))
                log.write(f"{time.strftime('%H:%M')} skip {name(j)} (dependency failed)\n")
        for j in list(pending):
            if len(running) >= P:
                break
            if ready(j):
                env = dict(os.environ, **BASE, RUN_TAG=j[2], PDP8_TAG=j[2], SOLVER=os.environ.get("SOLVER", "gurobi"),
                           THREADS=T)
                env.update(j[3])
                nm = name(j)
                pr = subprocess.Popen([sys.executable, "-W", "ignore", str(Path(__file__).with_name("model.py")), str(j[0]), j[1]], env=env,
                                      stdout=open(RES / f"log_{nm}.txt", "w"), stderr=subprocess.STDOUT)
                running[nm] = (pr, time.time())
                pending.remove(j)
                log.write(f"{time.strftime('%H:%M')} start {nm}\n")
                log.flush()
        if pending and not running and not any(ready(j) for j in pending):
            log.write(f"{time.strftime('%H:%M')} waiting for dependencies: {[name(j) for j in pending][:5]} ...\n")
            log.flush()
            time.sleep(600)
        time.sleep(20)
    log.write(f"{time.strftime('%F %H:%M')} ALL DONE\n")
