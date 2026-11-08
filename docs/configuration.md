# Configuration

## Workflow configuration

`workflow/config/config.default.yaml` (paths relative to `workflow/`):

```yaml
data: ../data                 # processed inputs and results (exported to the scripts as VN_DATA)
results: results_v6           # run set: <data>/expansion/<results>/<run>{.nc,_summary.json}
summary: ../results/summary   # figures, tables and key indicators
solver:
  name: gurobi                # gurobi (archived results) or highs
  threads: 4                  # solver threads per run
external:                     # only to rebuild the 2024 nodal model from raw data
  vietnamgrid_dir: ../../vietnamgrid
  pypsa_vn_file: ../../pypsa-vn/vietnam_era5.nc
```

| Key | Meaning |
|---|---|
| `data` | directory of the processed inputs and results; exported as `VN_DATA` |
| `results` | sub-directory of the run set (`results_v6` = archived run set); exported as `RES_SUB` |
| `summary` | output directory of `make_summary` |
| `solver.name`, `solver.threads` | solver and threads of each run (`SOLVER`, `THREADS`) |
| `external.vietnamgrid_dir` | [vietnamgrid](https://github.com/nautel/vietnamgrid) data model: hourly load shape and 500 kV bus names |
| `external.pypsa_vn_file` | network of [pypsa-vn](https://github.com/fiasresna/pypsa-vn): hydro inflow per bus 2015–2016 |

Any key can be overridden on the command line, for example `snakemake -j4 solve_all --config results=my_runs`.

(run-settings)=
## Run settings

`scripts/model.py` solves one run, `python model.py <year> <pdp8|opt>`. Its settings are environment variables,
which `scripts/run_set.py` sets for every run of the [run set](run_set.md). The base settings of the run set are
`MODEL_V=6`, `DAY_STEP=4`, `COSTS=vntc`, `ALLOC=qd1509` and `VRE_SRC=gis`. Runs that differ from these list only
the settings they change.

### General

| Setting | Default | Meaning |
|---|---|---|
| `MODEL_V` | `6` | model version: `6` = central formulation; `5` = without monthly hydro budgets by default (benchmark runs of 2024) |
| `DAY_STEP` | `1` | keep every n-th day plus the peak day, reweighted (run set: `4`) |
| `SOLVER`, `THREADS` | `highs`, `4` | solver (`gurobi` or `highs`) and threads; Gurobi: barrier without crossover |
| `CROSSOVER` | `0` | `1`: run crossover after the barrier |
| `RUN_TAG` | (empty) | suffix of the run name (`<year>_<scenario><tag>`) |
| `PDP8_TAG` | `RUN_TAG` | plan run used as reference for the intra-regional grid and emission caps |
| `RES_SUB` | `results` | results sub-directory under `<VN_DATA>/expansion/` |

### Plan, demand and costs

| Setting | Default | Meaning |
|---|---|---|
| `PLAN_VARIANT` | `low` | variant of Decision 768 for demand and the plan's capacities (`low`, `high`) |
| `PLAN_RANGE` | `0` | `1` (`opt`): national capacities restricted to the plan's low–high ranges |
| `ALLOC` | `qd1509` | regional split of the plan's solar and wind additions: provincial project lists of Decision 1509 (`qd1509`) or the GEM pipeline (`gem`) |
| `COMMITTED` | `2026` | LNG projects fixed in every scenario: `2026` = contracts signed by 30 June 2026; `2025` = plants in operation only |
| `EXTRA` | (empty) | additional loads: `dc` (data centres), `hsr` (North–South high-speed rail) or `dc+hsr` |
| `DEMAND_X` | `1` | demand multiplier |
| `COSTS` | `vntc` | `vntc`: `repo_data/costs/costs_<year>.csv` (Vietnam Technology Catalogue 2026); `base`: `costs.csv` |
| `DISCOUNT` | `0.08` | real discount rate |
| `LNG_USD_MMBTU` | cost file | delivered LNG price, USD/MMBtu |
| `COAL_PRICE_X` | `1` | coal price multiplier |
| `SOLAR_CAPEX_X`, `ONWIND_CAPEX_X`, `OFFWIND_CAPEX_X`, `BAT_CAPEX_X`, `NUC_CAPEX_X`, `PHS_CAPEX_X`, `LINE_CAPEX_X` | `1` | investment cost multipliers |
| `CONN_COST` | `0` | grid-connection cost added to utility PV and onshore wind, USD/kW |

### Adequacy and operation

| Setting | Default | Meaning |
|---|---|---|
| `CRM` | `hourly` | capacity reserve margin: `hourly` = chronological in every snapshot; `static` = capacity credits at the annual peak |
| `RM` | `1.10` | reserve margin (firm capacity / peak demand) |
| `CREDIT_BATTERY` | `0.7` | capacity credit of batteries under `CRM=static` |
| `OPRES` | `1` | operating reserve (largest unit + 5% of wind and solar output) and SNSP limit in every snapshot |
| `SNSP_MAX` | `0.75` | maximum non-synchronous share of demand |
| `NO_RESERVE` | `0` | `1`: no reserve margin (energy adequacy tests of fixed portfolios) |
| `KEEP_OPRES` | `1` | keep the operating reserve and SNSP limit when `NO_RESERVE=1` |
| `UC` | `1` | linearised unit commitment of coal plants |
| `CORR_DERATE` | `0.7` | usable share of the summed thermal ratings of an inter-regional corridor |
| `HYDRO_TWH` | `100` | annual hydro inflow energy, TWh (dry year: `80`) |
| `HYDRO_MONTHLY` | `1` | hydro dispatch limited to the monthly inflow of each region |
| `GAS_QC` | `0.35` | minimum annual capacity factor of domestic gas (take-or-pay); `0` in zero-emission runs |
| `LNG_QC` | `0` | `pdp8`: minimum annual capacity factor of the plan's LNG plants |

### Expansion limits and emissions

| Setting | Default | Meaning |
|---|---|---|
| `BUILD_LIMIT` | `1` | `0`: no build-rate limits for solar, onshore and offshore wind (`opt`) |
| `BUILD_SOLAR_GW` | `11` | build rate of utility PV, GW per year |
| `BAT_BUILD_GW` | `0` | build rate of batteries, GW per year (`0` = unlimited) |
| `CO2_CAP` | `none` | `none`; `plan` (the plan's ceiling, 198 Mt in 2030 falling linearly to 27 Mt in 2050); `pdp8` or `pdp8*<f>` (emissions of the plan run, scaled by `f`); a number in Mt |

### Analyses

| Setting | Default | Meaning |
|---|---|---|
| `RELEASE` | (empty) | `pdp8`: groups of the plan optimised instead of fixed (`lng`, `offwind`, `nuclear`, `ac`, `rest`, `storage`) |
| `MGA` | (empty) | near-optimal space: `<group>:<slack>`, maximise the capacity of a group at a cost within `(1 + slack)` of the optimum |
| `MGA_REF` | (empty) | summary of the optimum that provides the cost |
| `PATH_FROM` | (empty) | start the expansion from the capacities of a solved earlier year (pathway) |
| `FIX_FROM` | (empty) | dispatch the solved portfolio of another run (adequacy and regret) |
| `SOLAR_NEW_X`, `BAT_NEW_X`, `NORTH_CORR_X` | `1` | with `FIX_FROM`: scale new utility PV, batteries, or the corridors into the North |
| `WEATHER_YEAR` | `2024` | ERA5 weather year (2015–2024) of the wind and solar profiles |
| `OUTAGE_SEED` | (empty) | seed of weekly random forced outages of thermal units |

Every setting that differs from the default is stored under `sensitivity` in the run summary.
