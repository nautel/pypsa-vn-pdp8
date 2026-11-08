[![Release](https://img.shields.io/badge/release-v1.2.1-2c6bac.svg)](docs/release_notes.md)
[![Test](https://github.com/nautel/pypsa-vn-pdp8/actions/workflows/test.yaml/badge.svg)](https://github.com/nautel/pypsa-vn-pdp8/actions/workflows/test.yaml)
[![Documentation](https://github.com/nautel/pypsa-vn-pdp8/actions/workflows/docs.yaml/badge.svg)](https://nautel.github.io/pypsa-vn-pdp8/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24037833.svg)](https://doi.org/10.5281/zenodo.24037833)
[![PyPSA](https://img.shields.io/badge/PyPSA-1.2-2c6bac.svg)](https://pypsa.org)
[![Snakemake](https://img.shields.io/badge/snakemake-%E2%89%A59-039475.svg)](https://snakemake.github.io)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

# PyPSA-VN-PDP8: planned versus least-cost power system for Vietnam

PyPSA-VN-PDP8 is an open capacity-expansion model of Vietnam's power system built with [PyPSA](https://pypsa.org).
It compares the revised **Power Development Plan VIII** (PDP8; Decision 768/QĐ-TTg of 2025 and its implementation
plan, Decision 1509/QĐ-BCT) with a **least-cost system** for 2035 and 2040. Both systems meet identical chronological
adequacy, operating-reserve and inverter-share constraints. The model attributes the gap between them to the plan's
components with Shapley values and tests it with near-optimal, Monte Carlo, weather-year and stress-test analyses.

The model-building routines form a [Snakemake](https://snakemake.github.io) workflow, organised like
[PyPSA-Eur](https://github.com/PyPSA/pypsa-eur) and [PyPSA-USA](https://github.com/PyPSA/pypsa-usa). The workflow
builds the model from open data and solves the plan and the least-cost system together with all scenarios,
sensitivities and analyses (289 runs). It then summarises the results in figures, tables and key indicators. The
processed inputs and all solved runs are archived on [Zenodo](https://doi.org/10.5281/zenodo.24037833). The
[documentation](https://nautel.github.io/pypsa-vn-pdp8/) covers installation, the workflow, the configuration and the outputs.

> [!WARNING]
> PyPSA-VN-PDP8 is a research model with simplifications: single reference years, a 30-region transport model,
> sampled days and one design weather year. Read the [limitations](docs/limitations.md) before using its results.

<p align="center">
  <img src="docs/img/network.png" width="85%" alt="Nodal model of the 2024 grid and the 30-region expansion model"><br>
  <em>(a) Nodal model of the 2024 transmission grid (500/220/110 kV, 2,175 buses) built from OpenStreetMap;
  (b) the 30-region expansion model with the capacity of the existing inter-regional corridors.</em>
</p>

## Key results

Measured as cost incremental to the 2024 fleet:

- The least-cost system is **25% cheaper** than the plan in 2035 (10.1 bn USD/a, or 14 USD/MWh of demand) and
  **22% cheaper** in 2040. It builds far more solar power and storage, almost no offshore wind, and almost no LNG
  capacity beyond the plants already committed.
- The largest shares of the gap come from the plan's mix of solar power, wind and storage, and from its
  inter-regional transmission. Offshore wind, nuclear power and the LNG fleet can each be accommodated on their own
  within 5% of the optimal cost.
- The least-cost system stays cheaper across 18 one-at-a-time sensitivities (18–27%), 32 Monte Carlo samples (20–30%),
  ten weather years with random outages and nine stress futures.

<table>
  <tr>
    <td width="44%"><img src="docs/img/maps_2035.png" alt="Regional capacity and transmission in 2035"></td>
    <td width="56%"><img src="docs/img/system_cost.png" alt="Average system cost by technology"><br><br>
        <img src="docs/img/attribution.png" alt="Shapley attribution and near-optimal space"></td>
  </tr>
  <tr>
    <td><em>Installed capacity per region and transmission in 2035: the plan (PDP8) and the least-cost system.</em></td>
    <td><em>Top: average system cost by technology and CO<sub>2</sub> emissions of the main scenarios. Bottom: Shapley
    values of the plan's components and their near-optimal space.</em></td>
  </tr>
</table>

## Features

| Feature | Implementation |
|---|---|
| Space | 30 regions, clustered from the nodal model; inter-regional corridors as a transport model; new AC lines and the plan's HVDC links |
| Time | three-hourly steps; every fourth day and the peak day of the year (weighted) |
| Investment | utility PV, onshore and offshore wind, batteries, pumped hydro, LNG-fired CCGT, OCGT, nuclear power, transmission |
| Security | chronological capacity reserve margin in every step (GenX-style), operating reserve, non-synchronous penetration ≤ 75% |
| Operation | linearised unit commitment of coal plants, monthly hydro budgets, take-or-pay offtake of domestic gas |
| Plan | capacities of Decisions 768/1509 (base and high variant) and the plan's own transmission projects |
| Data | OpenStreetMap, Global Energy Monitor, ERA5 and Global Wind Atlas, ESA WorldCover, Copernicus DEM, WDPA, Ember, Vietnam Technology Catalogue 2026 |
| Analyses | Shapley attribution over all 32 subsets of five groups, near-optimal space at 2, 5 and 10% slack, Latin-hypercube Monte Carlo (32 samples), ten weather years with random outages, regret of five portfolios under nine stress futures |

## Getting started

```bash
git clone https://github.com/nautel/pypsa-vn-pdp8.git
cd pypsa-vn-pdp8
conda env create -f workflow/envs/environment.yaml
conda activate pypsa-vn-pdp8
```

Unpack the [Zenodo](https://doi.org/10.5281/zenodo.24037833) archives of inputs and results into the repository root,
and add the GADM boundaries (see [installation](docs/installation.md)). Then:

```bash
cd workflow
snakemake -j1 make_summary      # figures, tables and key indicators from the archived runs (~10 min)
snakemake -j4 ../data/expansion/my_runs/2035_opt_vn_summary.json --config results=my_runs   # solve one run
```

The [tutorial](docs/tutorial.md) shows how to read results, solve runs and add scenarios. The archived runs were
solved with Gurobi 13. HiGHS can be selected in the configuration, but each run then takes hours instead of minutes.

<p align="center"><img src="docs/img/workflow.png" width="100%" alt="Workflow"></p>

## Documentation

| | |
|---|---|
| [Introduction](docs/introduction.md) | purpose, workflow steps, repository structure |
| [Installation](docs/installation.md) | environment, solver, data, rebuilding from raw data |
| [Tutorial](docs/tutorial.md) | summarise, read, solve and add runs |
| [Configuration](docs/configuration.md) | workflow configuration and the settings of a run |
| [Run set](docs/run_set.md) | the 289 runs: names, sensitivities, Monte Carlo, stress futures |
| [Model description](docs/model.md) | formulation, adequacy and security constraints, costs, analyses |
| [Workflow rules](docs/workflow.md) | Snakemake rules and scripts |
| [Outputs](docs/outputs.md) | networks, run summaries, key indicators |
| [Data sources](docs/data_sources.md) | source and licence of every dataset and parameter |
| [Limitations](docs/limitations.md) | simplifications to keep in mind |
| [Release notes](docs/release_notes.md) | changes between versions |

The documentation is online at <https://nautel.github.io/pypsa-vn-pdp8/> and can be built locally with `make docs` (Sphinx).

## Contributing and support

Questions, bug reports and corrections of input data are welcome as [issues](https://github.com/nautel/pypsa-vn-pdp8/issues).
Contributions are welcome as pull requests; see the [contribution guidelines](CONTRIBUTING.md). `make test` and
`make lint` run the checks that the continuous integration runs.

## Citation

If you use this model, its data or its results, please cite the archived release (see [`CITATION.cff`](CITATION.cff)
and [citation](docs/citation.md)):

> T. Le, H. C. Vu, M. Q. Duong, *PyPSA-VN-PDP8: an open capacity-expansion model of Vietnam's power system (data,
> results and code)*, Zenodo (2026), doi:[10.5281/zenodo.24037833](https://doi.org/10.5281/zenodo.24037833).

A paper describing the model and its results is in preparation.

## Licence

The code is released under the [MIT License](LICENSE). The input data carry the licences of their sources; see
[licences](docs/licenses.md) and [data sources](docs/data_sources.md).
