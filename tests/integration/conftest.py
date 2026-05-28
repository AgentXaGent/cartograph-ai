"""Fixtures shared across integration tests.

Integration tests hit the real Anthropic API. They are deselected by
default via ``[tool.pytest.ini_options].addopts = "-m 'not integration'"``
in pyproject.toml. To run them::

    pytest -m integration                  # run all
    pytest -m integration -k sasaki        # run just the Sasaki probe
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip integration tests when ANTHROPIC_API_KEY is not set."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    skip_marker = pytest.mark.skip(
        reason="ANTHROPIC_API_KEY not set; integration tests require a funded key."
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)
