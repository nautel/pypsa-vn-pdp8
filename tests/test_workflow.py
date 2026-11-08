"""The Snakemake workflow parses and resolves the full job graph (dry run, no data or solver needed)."""

import re
import shutil
import subprocess

import pytest
import yaml

from conftest import ROOT

WORKFLOW = ROOT / "workflow"


def test_default_config_keys():
    cfg = yaml.safe_load((WORKFLOW / "config" / "config.default.yaml").read_text())
    assert {"data", "results", "summary", "solver", "external"} <= set(cfg)
    assert cfg["solver"]["name"] in ("gurobi", "highs")
    assert int(cfg["solver"]["threads"]) >= 1


def dry_run(target, data_dir):
    out = subprocess.run(
        ["snakemake", "-n", "-j1", target, "--config", f"data={data_dir}", "results=results_test"],
        cwd=WORKFLOW,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    return out.stdout + out.stderr


def job_count(log, rule):
    m = re.search(rf"^{rule}\s+(\d+)\s*$", log, re.M)
    return int(m.group(1)) if m else 0


@pytest.mark.skipif(shutil.which("snakemake") is None, reason="snakemake not installed")
def test_dry_run_solve_all(data_dir):
    log = dry_run("solve_all", data_dir)
    assert job_count(log, "solve") == 289


@pytest.mark.skipif(shutil.which("snakemake") is None, reason="snakemake not installed")
def test_dry_run_summary(data_dir):
    log = dry_run("make_summary", data_dir)
    assert job_count(log, "solve") == 289
    assert job_count(log, "make_summary") == 1
