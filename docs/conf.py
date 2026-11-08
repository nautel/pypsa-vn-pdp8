# Sphinx configuration of the PyPSA-VN-PDP8 documentation (build: make docs, or sphinx-build -b html docs docs/_build)
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

project = "PyPSA-VN-PDP8"
author = "Tuan Le, Hai Canh Vu, Minh Quan Duong"
copyright = "2026, " + author
release = re.search(r"^version:\s*(\S+)", (ROOT / "CITATION.cff").read_text(), re.M).group(1)
version = release

extensions = ["myst_parser", "sphinx_copybutton"]
source_suffix = {".md": "markdown"}
myst_enable_extensions = ["colon_fence", "dollarmath", "amsmath", "deflist"]
myst_heading_anchors = 3
exclude_patterns = ["_build", "img/*.dot"]
suppress_warnings = ["myst.xref_missing"]  # links to files outside docs/ (README, workflow/) resolve on GitHub

html_theme = "sphinx_book_theme"
html_title = f"PyPSA-VN-PDP8 {release}"
html_static_path = []
html_theme_options = {
    "repository_url": "https://github.com/nautel/pypsa-vn-pdp8",
    "use_repository_button": True,
    "use_issues_button": True,
    "path_to_docs": "docs",
    "show_toc_level": 2,
}
