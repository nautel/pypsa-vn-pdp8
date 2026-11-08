.PHONY: help test lint format docs summary clean

help:
	@echo "make test      run the tests (run set, Monte Carlo samples, Snakemake dry run)"
	@echo "make lint      check the code style (ruff, snakefmt)"
	@echo "make format    format Python and Snakemake files"
	@echo "make docs      build the documentation into docs/_build/html"
	@echo "make summary   figures, tables and key indicators from the archived run set"
	@echo "make clean     remove build files of the documentation and the tests"

test:
	pytest

lint:
	ruff check workflow/scripts tests docs/conf.py
	snakefmt --check workflow/Snakefile workflow/rules

format:
	ruff check --fix workflow/scripts tests docs/conf.py
	snakefmt workflow/Snakefile workflow/rules

docs:
	sphinx-build -b html docs docs/_build/html

summary:
	cd workflow && snakemake -j1 make_summary

clean:
	rm -rf docs/_build .pytest_cache
