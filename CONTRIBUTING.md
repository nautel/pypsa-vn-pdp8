# Contributing

Contributions are welcome: bug reports, questions, corrections of input data, new scenarios and improvements of the
code and documentation.

## Issues

- **Bugs:** open an issue with the bug report template. Include the command, the configuration and the relevant
  part of the log (`workflow/logs/`).
- **Data corrections:** cite the source of the corrected value (document, date, URL). Data sources are listed in
  [`docs/data_sources.md`](docs/data_sources.md).
- **Questions about the model or the results:** open an issue with the question template.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Install the environment (`conda env create -f workflow/envs/environment.yaml`) and the hooks:
   `pip install pre-commit && pre-commit install`.
3. Make the change, then run `make test` and `make lint`. If the change affects results, solve the runs it affects
   (see [`docs/tutorial.md`](docs/tutorial.md)).
4. Document new settings in `docs/configuration.md` and new runs in `docs/run_set.md`, and add a line to
   `docs/release_notes.md`.
5. Open the pull request and fill in the template.

## Style

- Python: formatted for a line length of 120 and checked with [ruff](https://docs.astral.sh/ruff/).
- Snakemake files: formatted with [snakefmt](https://github.com/snakemake/snakefmt).
- Every input value has a source: cite it in a comment next to the value, or as an ID of `docs/data_sources.md`.
