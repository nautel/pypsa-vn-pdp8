# Run set

The run set (`workflow/scripts/run_set.py`) defines all 289 runs with their [settings](configuration.md#run-settings)
and dependencies. The Snakemake rule `solve` reads it, so every run is also a Snakemake target.

## Run names

Run names follow `<year>_<scenario><tag>`. The scenario is `pdp8` (the plan, capacities fixed) or `opt` (least
cost).

| Tag | Runs | Content |
|---|---|---|
| `_vn` | 4 | central case, 2035 and 2040 |
| `_vn_co2plan`, `_vn_co2half`, `_vn_co2zero`, `_vn_co2zero_nolim` | 9 | emission ceiling of the plan; half the plan's emissions; zero emissions, with and without build-rate limits |
| `_vn_high`, `_vn_planrange`, `_vn_prgrid` | 8 | high variant of the plan; least cost within the plan's ranges, with optimised lines or with the plan's lines |
| `_vn_lngqc`, `_vn_dc`, `_vn_hsr`, `_vn_dchsr` | 14 | LNG take-or-pay; additional loads of data centres and high-speed rail |
| `_vn_rel_<groups>` | 30 | Shapley attribution: every proper subset of the five groups `lng`, `offwind`, `nuclear`, `ac`, `rest` released to optimisation |
| `_vn_first_<g>`, `_vn_last_<g>`, `_vn_ceil_first_<g>`, `_vn_ceil_last_<g>` | 20 | attribution bounds: a group released first or last (2040; 2035 under the emission ceiling) |
| `_vn_storsite` | 1 | the plan with storage siting optimised |
| `_vn_mga<slack>_<group>` | 12 | near-optimal space: maximum capacity of offshore wind, LNG, nuclear power and transmission at 2, 5 (no slack in the tag) and 10% extra cost |
| `_vn_<sensitivity>` | 34 | one-at-a-time sensitivities (see below) |
| `_vn_mc<i>` | 64 | Monte Carlo: 32 samples, plan and least cost |
| `_vn_fix_w<year>[d]` | 40 | adequacy: the 2035 portfolios dispatched in weather years 2015–2024 with random outages (`d`: dry hydrology) |
| `<portfolio>_rg_<future>` | 45 | regret: five fixed 2035 portfolios under nine stress futures |
| `_vn_path`, `_vn_ds2`, `_vn_xo` | 5 | pathway 2035→2040, temporal resolution (every second day), crossover |
| `_bench`, `_bench_gasqc`, `_bench_hydmon` | 3 | 2024: the 30-region model dispatching the 2024 fleet, for the benchmark against observed operation |

## Sensitivities

One-at-a-time sensitivities of 2035, run for both scenarios unless marked (opt only):

| Tag | Setting | Tag | Setting |
|---|---|---|---|
| `_vn_lnglow` | `LNG_USD_MMBTU=12` | `_vn_off70` | `OFFWIND_CAPEX_X=0.7` |
| `_vn_dry` | `HYDRO_TWH=80` | `_vn_nuc150` | `NUC_CAPEX_X=1.5` |
| `_vn_rm115`, `_vn_rm120` | `RM=1.15`, `1.20` | `_vn_phs150` | `PHS_CAPEX_X=1.5` |
| `_vn_conn` | `CONN_COST=100` | `_vn_static` | `CRM=static` |
| `_vn_corr` | `CORR_DERATE=0.5` | `_vn_line2` | `LINE_CAPEX_X=2` |
| `_vn_nores` | `OPRES=0` | `_vn_commit25` | `COMMITTED=2025` |
| `_vn_wacc10` | `DISCOUNT=0.10` | `_vn_hydfree` | `HYDRO_MONTHLY=0` |
| `_vn_bat150` | `BAT_CAPEX_X=1.5` | `_vn_pv55` (opt only) | `BUILD_SOLAR_GW=5.5` |
| `_vn_batbuild` (opt only) | `BAT_BUILD_GW=3` | | |

## Monte Carlo

`workflow/scripts/mc_samples.py` draws two optimised Latin hypercubes of 16 samples each (`scipy.stats.qmc`, seeds 42
and 43) over nine factors, uniformly within these ranges:

| Factor | Range |
|---|---|
| `LNG_USD_MMBTU` | 10–20 |
| `SOLAR_CAPEX_X` | 0.8–1.2 |
| `ONWIND_CAPEX_X` | 0.85–1.25 |
| `BAT_CAPEX_X` | 0.7–1.5 |
| `OFFWIND_CAPEX_X` | 0.7–1.2 |
| `NUC_CAPEX_X` | 0.9–1.6 |
| `DISCOUNT` | 0.06–0.10 |
| `DEMAND_X` | 0.95–1.10 |
| `HYDRO_TWH` | 80–110 |

The samples are written to `<results>/mc_samples.csv`. The archived run set contains the same file.

## Stress futures (regret)

Five 2035 portfolios are fixed: `pdp8_vn`, `opt_vn`, `opt_vn_planrange`, `opt_vn_co2plan` and `pdp8_vn_prgrid`.
Each is dispatched under nine futures:

| Future | Setting |
|---|---|
| `_ref` | none |
| `_dem` | `DEMAND_X=1.11` |
| `_lng` | `LNG_USD_MMBTU=25` |
| `_dry` | `HYDRO_TWH=80` |
| `_pv` | `SOLAR_NEW_X=0.5` |
| `_coal` | `COAL_PRICE_X=1.5` |
| `_bat` | `BAT_NEW_X=0.5` |
| `_north` | `NORTH_CORR_X=0.5` |
| `_weak` | `WEATHER_YEAR=2022`, `HYDRO_TWH=80` |

## Dependencies

A run that uses the results of another run lists that run as a dependency:

- least-cost runs depend on the plan run of the same year;
- near-optimal runs depend on the optimum;
- fixed-portfolio runs depend on the portfolio they dispatch.

Snakemake resolves these dependencies, so any single run can be requested. The test suite (`tests/test_run_set.py`)
checks the number of runs, the uniqueness of names, the completeness of the Shapley subsets and the absence of
cycles.
