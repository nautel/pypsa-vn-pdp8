# Installation

## Code and environment

```bash
git clone https://github.com/nautel/pypsa-vn-pdp8.git
cd pypsa-vn-pdp8
conda env create -f workflow/envs/environment.yaml
conda activate pypsa-vn-pdp8
```

`workflow/envs/environment.yaml` pins the main packages to the versions used for the archived results (Python 3.13,
PyPSA 1.2.4, linopy 0.8.0). `workflow/envs/environment.fixed.yaml` records the exact versions of all direct
dependencies of that environment.

## Solver

The archived runs were solved with **Gurobi 13**, using the barrier method without crossover and a relative
tolerance of 1e-4. Free academic licences are available from Gurobi. The open-source solver
[HiGHS](https://highs.dev) is installed with the environment and can be selected in the configuration:

```yaml
solver:
  name: highs
```

With HiGHS a run takes hours instead of minutes. Building the summary from archived results needs no solver.

## Data

1. Download the archives from [Zenodo](https://doi.org/10.5281/zenodo.24037834) and unpack
   `pypsa-vn-pdp8-inputs-v1.0.zip` and `pypsa-vn-pdp8-results-v6.zip` into the repository root. Both create `data/`.
2. Download the GADM 4.1 boundaries of Vietnam (levels 0–2, GeoJSON) from <https://gadm.org> into `data/shapes/`,
   and the outlines of the Paracel and Spratly Islands (`XPI`, `XSP`) into `data/shapes/islands/`. The GADM licence
   does not allow redistribution, so these files are not included.

The layout of `data/` is:

```
data/
├── expansion/            inputs of the 30-region model and the run set results_v6/
├── networks/             2024 nodal model and its weekly dispatch
├── plans/                the plan's projects and lines (Decision 1509)
├── costs/, demand/, hydro/, gis/, grid/, plants/, validation/, weather/, cutouts/
└── shapes/               GADM boundaries (download separately)
```

(rebuilding-from-raw-data)=
## Rebuilding from raw data

Steps 2 and 3 of the workflow rebuild the processed inputs (`snakemake -j1 build_network_2024` and
`snakemake -j1 build_inputs`). They need:

- the OpenStreetMap extract of Vietnam ([earth-osm](https://github.com/pypsa-meets-earth/earth-osm));
- the Global Energy Monitor trackers;
- an ERA5 cutout, which requires a Copernicus Climate Data Store account (`~/.cdsapirc`);
- ESA WorldCover, the Copernicus DEM, WDPA and the Global Wind Atlas;
- the tables of transformer capacities included in the Zenodo inputs;
- for the hydro inflow and the hourly load shape, two external repositories, set under `external` in the
  configuration.

Every dataset is listed with its source and licence in [data sources](data_sources.md).
