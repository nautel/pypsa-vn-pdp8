# Model description

## Space and time

The capacity-expansion model represents Vietnam by **30 regions**, clustered from the 2024 nodal model
(`scripts/prepare.py`). The regions are connected by a transport model. Inter-regional corridors carry the existing
lines at 70% of their summed thermal ratings (`CORR_DERATE`); new AC capacity and the HVDC links of the plan can be
added. Hourly series of the reference year are averaged to **three-hour steps**. Every fourth day plus the day of the
annual peak is retained (`DAY_STEP=4`) and reweighted, so that each snapshot represents about 12 h in the objective.
Storage moves with the true step length of 3 h.

## Objective

For one reference year (2035 or 2040) the model minimises the total annual system cost:

$$
\min \Big[\sum_{n,s} c_{n,s}\,(G_{n,s}-G^{0}_{n,s}) + \sum_{\ell} c_{\ell}\,(F_{\ell}-F^{0}_{\ell})
+ \sum_{n,s,t} w_t\, o_{n,s}\, g_{n,s,t} + \omega\sum_{n,s,t} k^{\mathrm{su}}_{n,s}\, u^{\mathrm{su}}_{n,s,t}\Big]
$$

- $G_{n,s}$, $F_\ell$: capacities of technology $s$ in region $n$ and of corridor $\ell$; the superscript 0 marks
  existing capacity.
- $c$: fixed costs, annualised at a real discount rate of 8%.
- $o_{n,s}$: variable costs.
- $g_{n,s,t}$: dispatch, with snapshot weighting $w_t$.
- $u^{\mathrm{su}}_{n,s,t}$, $k^{\mathrm{su}}_{n,s}$: start-ups of coal plants (linearised unit commitment, minimum
  stable load 40%) and their cost of 100 USD/MW. Start-ups are scaled by $\omega$, the ratio of days in the year to
  retained days.

The fixed costs of assets existing in 2024 are excluded, so that all costs and savings are incremental to the 2024
fleet. Unserved energy is valued at 3,000 USD/MWh.

## Adequacy and security

Both scenarios meet the same standard:

- **Capacity reserve margin**, chronological in every snapshot (GenX-style, `CRM=hourly`). The left-hand side counts
  the derated capacity of dispatchable plants, the available output of wind and solar, and the scheduled net output
  of storage, hydro reservoirs and imports. It must be at least 110% of the load scaled to the hourly peak:

  $$
  \sum_{n,s\in\mathcal{D}} \kappa_s G_{n,s} + \sum_{n,s\in\mathcal{V}} \bar g_{n,s,t} G_{n,s}
  + \sum_{n,s\in\mathcal{S}} (g^{\mathrm{dis}}_{n,s,t} - g^{\mathrm{ch}}_{n,s,t}) + \sum_n g^{\mathrm{imp}}_{n,t}
  \ge (1+m)\,\frac{\hat d}{\max_\tau d_\tau}\, d_t \quad \forall t
  $$

  The same constraint applies to the northern region, which counts the transfer capacity into the region.
- **Operating reserve**: the headroom of committed coal units, other thermal plants and storage must cover the
  largest unit (1.2 GW) plus 5% of wind and solar output.
- **Non-synchronous penetration** (SNSP) is limited to 75% of demand plus storage charging.
- The plan may add OCGT wherever its own capacity does not meet these constraints.

## Supply

| Group | Representation |
|---|---|
| Committed assets | hydro (monthly inflow budgets per region, 100 TWh/a), coal plants in operation and under construction, domestic gas with a take-or-pay offtake (minimum capacity factor 0.35), imports from Laos and China (annual capacity factor 0.45–0.55), biomass, rooftop PV of 2024, LNG plants in operation or under contract |
| Extendable (least cost) | utility PV and onshore wind (land-eligible potentials, three onshore wind classes), offshore wind, batteries (4 h), pumped hydro, LNG-fired CCGT, OCGT, nuclear power (Ninh Thuận, at most 6.4 GW), AC corridors and HVDC links |
| Build-rate limits (least cost) | utility PV 11 GW/a, onshore wind 3.6 GW/a, offshore wind 17 GW by 2035 |
| Wind and solar profiles | ERA5 2024 via atlite on land-eligible cells (ESA WorldCover, Copernicus DEM, WDPA), calibrated to observed 2024 generation |

## Costs

Technology costs follow the Vietnam Technology Catalogue 2026; fuel prices follow the price frameworks of 2025. The
values are in `workflow/repo_data/costs/costs_<year>.csv`, each with its source. `scripts/costs_vntc2026.py` derives
them from `costs.csv`. All money is in real USD.

## Plan representation

The plan run fixes the national capacities of Decision 768 (low variant; 2035 and 2040 interpolated between the
targets of 2030 and 2050). Solar and wind additions are distributed over regions with the provincial project lists of
Decision 1509. The run adds the plan's 500 kV and 220 kV line projects (mapped to corridors) and its HVDC links. The same demand, the same
committed assets and the same adequacy standard apply to both scenarios.

## Analyses

| Analysis | Method |
|---|---|
| Attribution | Shapley values of five groups of the plan (LNG, offshore wind, nuclear power, inter-regional transmission, the rest), from the system cost of all 32 subsets released to optimisation |
| Near-optimal space | capacity of offshore wind, LNG, nuclear power and transmission maximised at a cost within 2, 5 and 10% of the optimum |
| Sensitivities | 18 one-at-a-time variations of structural assumptions |
| Monte Carlo | 32 Latin-hypercube samples of nine jointly varied factors |
| Adequacy | the 2035 portfolios dispatched over ten weather years (2015–2024) with normal and dry hydrology and weekly random forced outages |
| Regret | five fixed 2035 portfolios under nine stress futures |

The settings of every analysis run are listed in the [run set](run_set.md).

## Benchmark

The 2024 nodal model (2,175 buses, 500/220/110 kV) dispatches the 2024 fleet in weekly chunks
(`scripts/solve_vn.py`), and the result is compared with the monthly generation by technology reported by Ember
(`scripts/validate_2024.py`). The 30-region model is benchmarked the same way: the three `2024_pdp8_bench*` runs
dispatch the 2024 fleet (`scripts/benchmark_2024.py`).

## Solution

Expansion problems are built with linopy and solved with the barrier algorithm of Gurobi 13 to a relative tolerance
of $10^{-4}$, without crossover. A run takes a few minutes (median 6 min with four threads).
