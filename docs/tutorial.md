# Tutorial

All commands are run from `workflow/` in the activated environment, after [installation](installation.md).

## 1. Summarise the archived results

```bash
cd workflow
snakemake -j1 make_summary
```

The workflow finds all 289 run summaries in `data/expansion/results_v6/`, so no model run is repeated. It writes
the figures, tables and key indicators to `results/summary/` in about ten minutes (see [outputs](outputs.md)).

To check what Snakemake would do without running anything:

```bash
snakemake -n make_summary
```

## 2. Read a result

```python
import json
import pypsa

summary = json.load(open("../data/expansion/results_v6/2035_opt_vn_summary.json"))
print(summary["cost_bnUSD_per_year"]["total_excl_VOLL"], summary["capacity_GW"]["solar"])

n = pypsa.Network("../data/expansion/results_v6/2035_opt_vn.nc")
print(n.statistics.optimal_capacity())
```

## 3. Solve one run

A run is requested through its output file. Snakemake first solves the runs it depends on: for example, a
least-cost run takes the intra-regional grid of the plan run of the same year (and its emissions, where the run is
capped at the plan's emissions). To keep the archived results unchanged, write new runs to a separate results
directory:

```bash
snakemake -j4 ../data/expansion/my_runs/2035_opt_vn_summary.json --config results=my_runs
```

This solves `2035_pdp8_vn` and then `2035_opt_vn`. With Gurobi and four threads each takes a few minutes. The settings
of every run are defined in `scripts/run_set.py` (see [run set](run_set.md)).

## 4. Add a scenario

New scenarios are entries in `scripts/run_set.py`. A run is a tuple of year, scenario (`pdp8` or `opt`), tag,
settings and dependencies, added with `J(...)`. For example, a least-cost run for 2035 with a delivered LNG price of
14 USD/MMBtu:

```python
J(2035, "opt", "_vn_lng14", {"LNG_USD_MMBTU": "14", "PDP8_TAG": "_vn"}, ["2035_pdp8_vn"])
```

```bash
snakemake -j4 ../data/expansion/my_runs/2035_opt_vn_lng14_summary.json --config results=my_runs
```

All settings are described in [configuration](configuration.md#run-settings).

## 5. Solve the full run set

```bash
snakemake -j4 solve_all --config results=my_runs
```

With four threads per run, the full set takes about 30 job-hours (median run 6 min, longest about 2 h). Without
Snakemake, `python scripts/run_set.py <parallel_jobs> <threads>` schedules the same runs.
