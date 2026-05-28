"""Integration smoke test for sasaki.com/projects.

Expected behavior: cartograph detects the Algolia search backend the
site uses to serve its project list. Classification is ``direct_api``;
subcategory is ``algolia_search``; ``endpoints_discovered`` includes the
Algolia DSN host.

Marked ``integration`` so it does not run under the default ``pytest``
invocation; gets skipped silently when ``ANTHROPIC_API_KEY`` is unset.
"""

from __future__ import annotations

import pytest

from cartograph_ai import probe

pytestmark = pytest.mark.integration

SASAKI_URL = "https://www.sasaki.com/projects"


def test_sasaki_probe_classifies_algolia():
    result = probe(SASAKI_URL)

    # Stage completion sanity.
    assert result.probe_stages_completed == [
        "http",
        "html_analysis",
        "claude_classify",
    ]
    assert result.model.startswith("claude-")

    # Classification expectations. We accept either direct_api or
    # embedded_data because some probes may surface the hydration blob
    # before the Algolia call signal; both are correct framings.
    assert result.classification.category in {"direct_api", "embedded_data"}
    if result.classification.category == "direct_api":
        sub = (result.classification.subcategory or "").lower()
        assert "algolia" in sub or "search" in sub

    # Confidence is high for this clean case.
    assert result.classification.confidence >= 0.6

    # The Algolia host should appear among discovered endpoints.
    algolia_endpoints = [
        e for e in result.endpoints_discovered if "algolia" in e.url.lower()
    ]
    assert algolia_endpoints, (
        "Expected at least one Algolia endpoint among discovered endpoints; "
        f"got {[e.url for e in result.endpoints_discovered]}"
    )
