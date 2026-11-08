import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "workflow" / "scripts"


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    """Empty data directory: the run set and the workflow must be constructible without inputs or results."""
    return tmp_path_factory.mktemp("data")


@pytest.fixture(scope="session")
def run_set(data_dir):
    mp = pytest.MonkeyPatch()
    mp.setenv("VN_DATA", str(data_dir))
    mp.setenv("RES_SUB", "results_test")
    mp.syspath_prepend(str(SCRIPTS))
    sys.modules.pop("run_set", None)
    module = importlib.import_module("run_set")
    yield module
    mp.undo()
