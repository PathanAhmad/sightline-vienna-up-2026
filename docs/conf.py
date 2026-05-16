"""Sphinx configuration for the Vienna UP 2026 documentation."""

from __future__ import annotations

from datetime import date

project = "Vienna UP 2026 Photo QC"
author = "Vienna UP 2026 team"
copyright = f"{date.today():%Y}, {author}"

extensions = [
    "sphinx.ext.autosectionlabel",
]

autosectionlabel_prefix_document = True

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "alabaster"
html_title = "Vienna UP 2026 Photo QC"
html_static_path = ["_static"]

