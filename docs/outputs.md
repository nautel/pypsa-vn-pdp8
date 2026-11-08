# Outputs

| Path | Content |
|---|---|
| `data/expansion/<results>/<run>.nc` | optimised PyPSA network: capacities, dispatch, storage, flows and prices in every three-hour step |
| `data/expansion/<results>/<run>_summary.json` | run summary (below) |
| `data/expansion/<results>/mc_samples.csv` | Monte Carlo samples |
| `results/summary/key_indicators.csv` | all reported indicators: costs and savings, capacities, emissions, attribution, robustness |
| `results/summary/key_indicators.tex` | the same values as LaTeX macros `\R{key}` |
| `results/summary/tab_*.tex` | LaTeX rows of the cost, capacity, regret and near-optimal tables |
| `results/summary/figures/*.png` | figures |
| `results/summary/figures/gen/*.csv` | the tables behind the figures: scenario costs, sensitivities, Shapley values, Monte Carlo, regret, ... |

## Run summary

Each run writes `<run>_summary.json`:

| Key | Content |
|---|---|
| `year`, `scenario`, `plan_variant`, `model_v`, `costs_file`, `co2_cap`, `vre_src`, `vre_alloc` | run definition |
| `sensitivity` | settings that differ from the defaults |
| `demand_TWh`, `pmax_GW`, `extra_load`, `extra_TWh`, `extra_peak_MW` | demand, peak and additional loads |
| `objective` | objective value, USD |
| `cost_bnUSD_per_year` | annualised new generation and storage, annualised new transmission, fuel and variable O&M, unserved energy at VOLL, total excluding VOLL |
| `overnight_investment_new_bnUSD` | overnight investment by technology |
| `capacity_GW`, `energy_TWh` | capacity and annual energy by technology |
| `co2_Mt`, `co2_shadow_USD_per_t` | emissions and the CO₂ price of an emission cap |
| `load_shedding_TWh` | unserved energy |
| `transmission_added` | new AC (inter- and intra-regional) and HVDC capacity, TW·km and GW |
| `firm_capacity_GW`, `reserve_requirement_GW` | firm capacity and requirement of the reserve margin |
| `indicators` | reserve margin, curtailment, SNSP, loss-of-load hours, start-up cost, storage energy, ... |

```python
import json
import pandas as pd
from pathlib import Path

res = Path("data/expansion/results_v6")
rows = {p.name.removesuffix("_summary.json"): json.loads(p.read_text()) for p in res.glob("*_summary.json")}
cost = pd.Series({k: v["cost_bnUSD_per_year"]["total_excl_VOLL"] for k, v in rows.items()})
print(cost[["2035_pdp8_vn", "2035_opt_vn"]])
```

## Key indicators

`key_indicators.csv` has two columns, `key` and `value`. Values are rounded as reported. Keys combine a quantity, a
scenario and a year, for example the total cost of a scenario, a saving, a Shapley value or the range of the Monte
Carlo savings. `make_summary.py` documents how each key is computed.
