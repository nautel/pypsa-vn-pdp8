"""Consistency of the run set (workflow/scripts/run_set.py)."""

import re
from graphlib import TopologicalSorter

N_RUNS = 289
GROUPS = ["lng", "offwind", "nuclear", "ac", "rest"]


def names(run_set):
    return [run_set.name(j) for j in run_set.jobs]


def test_number_of_runs(run_set):
    assert len(run_set.jobs) == N_RUNS


def test_names_are_unique_and_well_formed(run_set):
    nm = names(run_set)
    assert len(set(nm)) == len(nm)
    pattern = re.compile(r"^(2024|2035|2040)_(pdp8|opt)_[a-z0-9_.\-]+$")
    assert all(pattern.match(n) for n in nm), [n for n in nm if not pattern.match(n)]


def test_dependencies_exist_and_are_acyclic(run_set):
    nm = set(names(run_set))
    graph = {run_set.name(j): set(j[4]) for j in run_set.jobs}
    missing = {d for deps in graph.values() for d in deps} - nm
    assert not missing
    order = list(TopologicalSorter(graph).static_order())  # raises CycleError on a cycle
    assert len(order) == N_RUNS


def test_settings_are_strings(run_set):
    for j in run_set.jobs:
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in j[3].items()), run_set.name(j)


def test_least_cost_runs_depend_on_reference_plan(run_set):
    """Least-cost runs capped at the plan's emissions need the plan run of the same year and tag."""
    for y, s, t, env, deps in run_set.jobs:
        if s == "opt" and env.get("CO2_CAP", "").startswith("pdp8"):
            ref = f"{y}_pdp8{env.get('PDP8_TAG', t)}"
            assert ref in deps, f"{y}_{s}{t}"


def test_shapley_subsets_complete(run_set):
    """Every proper non-empty subset of the five plan groups is released once (2035)."""
    nm = set(names(run_set))
    released = {n.removeprefix("2035_pdp8_vn_rel_") for n in nm if n.startswith("2035_pdp8_vn_rel_")}
    assert len(released) == 2 ** len(GROUPS) - 2
    assert all(set(r.split("-")) <= set(GROUPS) for r in released)
    assert {"2035_pdp8_vn", "2035_opt_vn"} <= nm  # empty and full coalition


def test_monte_carlo_pairs(run_set):
    nm = set(names(run_set))
    mc = sorted(n for n in nm if n.startswith("2035_opt_vn_mc"))
    assert len(mc) == 32
    assert all(n.replace("_opt_", "_pdp8_") in nm for n in mc)


def test_weather_years_and_regret(run_set):
    nm = set(names(run_set))
    assert sum(n.startswith("2035_") and "_vn_fix_w" in n for n in nm) == 2 * 10 * 2  # 2 portfolios x 10 years x 2 hydro
    assert sum("_rg_" in n for n in nm) == 5 * 9  # 5 portfolios x 9 futures
