# PyPSA-VN-PDP8: planned versus least-cost power system for Vietnam

Code for the paper

> T. Le, H. C. Vu, M. Q. Duong, *Planned versus least-cost: Vietnam's power system and the revised Power Development
> Plan VIII*, submitted to Applied Energy (2026).

The model compares the revised Power Development Plan VIII (Decision 768/QĐ-TTg, 2025, and implementation plan
Decision 1509/QĐ-BCT) with a least-cost system for 2035 and 2040. It co-optimises generation, storage and
inter-regional transmission in a 30-region [PyPSA](https://pypsa.org) model under identical chronological adequacy,
operating-reserve and SNSP constraints, attributes the cost gap to the plan's components with Shapley values, and tests
robustness with sensitivities, a Monte Carlo analysis, near-optimal (MGA) runs, ten weather years and stress futures.

Processed input data, all results and the paper assets are archived on Zenodo: **DOI: [to be added]**.

## Repository structure

| Path | Content |
|---|---|
| `build_vn_*.py`, `substation_mva.py`, `check_grid_vs_official.py` | nodal model of the 2024 grid (500/220/110 kV) from OpenStreetMap and plant data |
| `build_vn_cutout.py`, `add_vre_profiles*.py` | ERA5 cutout and wind/solar profiles |
| `parse_qd1509*.py`, `geocode_qd1509.py` | parsing and geocoding of the transmission projects of Decision 1509 |
| `solve_vn.py`, `validate_2024.py`, `run_validation_2024.sh` | nodal dispatch of 2024 and benchmark against observed generation |
| `expansion/prepare.py`, `gis_inputs.py`, `vre_gis.py`, `onwind_new_cf.py` | clustering to 30 regions, land eligibility, VRE potentials and profiles |
| `expansion/costs_vntc2026.py`, `costs_*.csv` | cost assumptions (Vietnam Technology Catalogue 2026, fuel price frameworks 2025) |
| `expansion/model.py` | capacity-expansion model (all scenarios via environment variables, see its docstring) |
| `expansion/run_v6.py` | scheduler for the full run set of the paper (289 runs) |
| `expansion/weather_years.py` | ERA5 weather years 2015-2023 (Open-Meteo archive) for the adequacy test |
| `expansion/shapley.py`, `v5_tables.py`, `sensitivity_table.py`, `scenario_matrix.py`, ... | analyses and tables |
| `paper/make_paper_assets.py` | all figures and number macros (`numbers.tex`) of the paper |
| `DATA_SOURCES.md` | data sources (D-xx) and official documents (S-xx) referenced in the code comments |

## Installation

```bash
conda env create -f environment.yml
conda activate pypsa-vn-pdp8
```

The paper's runs used Gurobi 13 (barrier without crossover, relative tolerance 1e-4; free academic licences are
available). The open-source solver HiGHS (`SOLVER=highs`, the default of `model.py`) can be used instead, but a single
expansion run then takes hours instead of minutes; HiGHS results were not checked against the archived ones.

Reproduction check: from the archived inputs, re-running the central 2035 plan and least-cost cases with Gurobi gives
objectives within 0.05% and capacities within 0.1 GW of the archived runs, and `paper/make_paper_assets.py` applied
to the archived results reproduces every number and table of the paper.

## Reproducing the paper

1. Download the Zenodo archives and unpack `pypsa-vn-pdp8-inputs-v1.0.zip` and `pypsa-vn-pdp8-results-v6.zip` into
   `./data` (or set `VN_DATA=/path/to/data`).
2. Download the GADM 4.1 boundaries of Vietnam (levels 0-2, GeoJSON) from <https://gadm.org> into `data/shapes/`
   (`gadm41_VNM_0.json`, `gadm41_VNM_1.json`, `gadm41_VNM_2.json`); for the maps also the Paracel and Spratly
   outlines (`XPI`, `XSP`) into `data/shapes/islands/`. GADM data may not be redistributed and are therefore not
   included.
3. Optionally re-run all expansion runs (skipped if the results are unpacked):
   `python expansion/run_v6.py 2 8` (2 parallel jobs with 8 solver threads each; `SOLVER=highs` for HiGHS).
4. Regenerate all figures and numbers:
   `RES_DIR=data/expansion/results_v6 python paper/make_paper_assets.py <output-dir>`.

Rebuilding the nodal model from scratch additionally requires the OpenStreetMap extract (earth-osm), the
[pypsa-asean](https://github.com/pypsa-meets-earth/pypsa-asean) repository (commit `c0f2498`; set `PYPSA_EARTH_DIR`),
the Global Energy Monitor plant tracker, an ERA5 cutout (Copernicus CDS account) and the GIS layers listed in
`expansion/gis_inputs.py`; the processed results of these steps are included in the Zenodo inputs.

## Licences

Code: MIT (see `LICENSE`). The data archived on Zenodo carry the licences of their sources; see the Zenodo README.

## Citation

See `CITATION.cff`.
