# Workflow rules

The Snakemake workflow (`workflow/Snakefile`) includes four rule files. Each rule writes a log to
`workflow/logs/<rule>.log`.

## Model runs and summary

| Rule | Script | Inputs | Outputs |
|---|---|---|---|
| `solve` | `model.py` | summaries of the runs it depends on | `<results>/<run>.nc`, `<results>/<run>_summary.json` |
| `solve_all` | none | summaries of all 289 runs | none (target rule) |
| `make_summary` | `make_summary.py` | summaries of all 289 runs | `results/summary/key_indicators.csv`, `results/summary/figures/` |
| `all` (default) | none | output of `make_summary` | none |

`solve` takes the year, scenario and settings of a run from `scripts/run_set.py`. `make_summary` runs the analysis
scripts:

| Script | Content |
|---|---|
| `scenario_matrix.py` | cost, capacity and emissions of all scenarios |
| `sensitivity_table.py` | one-at-a-time sensitivities |
| `shapley.py` | Shapley attribution and first/last bounds |
| `robustness_tables.py` | adequacy over weather years (unserved energy, loss-of-load hours) and regret under stress futures |
| `extra_load_analysis.py` | data centres and high-speed rail |
| `congestion.py` | corridor flows and congestion |
| `adequacy_margin.py` | operating margin of the fixed 2035 portfolios over weather years |
| `benchmark_2024.py` | 30-region model versus 2024 operation |
| `plot_vn.py` | maps and common plotting style |

## 30-region inputs (`rules/build_inputs.smk`)

| Rule | Script | Outputs |
|---|---|---|
| `cluster_network` | `prepare.py` | `expansion/busmap.csv`, `clusters.csv`, `corridors.csv`, capacity-factor series `cf_*.csv` |
| `plan_sources` | `parse_qd1509_sources.py` | the plan's solar and wind projects by province and region |
| `gis_inputs` | `gis_inputs.py` | WorldCover (74 m), slope from the Copernicus DEM, WDPA protected areas |
| `vre_potentials` | `vre_gis.py` | eligible land, potentials and calibrated solar and wind profiles per region (`expansion/gis/`) |
| `onwind_new_profiles` | `onwind_new_cf.py` | profiles of new onshore wind turbines |
| `weather_years` | `weather_years.py` | wind and solar profiles of the weather years 2015–2023 (`expansion/weather_years/`; 2024 is the base year) |
| `costs` | `costs_vntc2026.py` | `repo_data/costs/costs_2035.csv`, `costs_2040.csv` |
| `build_inputs` | none | target rule of this step |

## 2024 nodal model (`rules/build_network.smk`)

| Rule | Script | Outputs |
|---|---|---|
| `build_cutout` | `build_vn_cutout.py` | ERA5 cutout of 2024 (atlite) |
| `build_topology` | `build_vn_topology.py` | buses, lines and transformers of the 500/220/110 kV grid from OpenStreetMap |
| `build_plants` | `build_vn_plants.py` | power plant units from the Global Energy Monitor trackers |
| `build_network` | `build_vn_network.py` | `networks/vn2024_base.nc` (2,175 buses), plant mapping, load weights |
| `parse_plan` | `parse_qd1509.py` | lines, substations and HVDC projects of Decision 1509 |
| `geocode_plan` | `geocode_qd1509.py` | the plan's projects with coordinates |
| `nodal_vre_profiles` | `add_vre_profiles_openmeteo.py` | solar and wind profiles per bus |
| `validate_2024` | `solve_vn.py`, `validate_2024.py` | weekly dispatch of 2024 and its comparison with observed generation |
| `build_network_2024` | none | target rule of this step |

## Job graph

```bash
cd workflow
snakemake --rulegraph make_summary | dot -Tpng > rulegraph.png    # rules
snakemake -n make_summary                                         # jobs that would run
```
