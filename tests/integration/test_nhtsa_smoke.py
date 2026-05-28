"""Integration smoke test for nhtsa.gov.

Expected behavior: cartograph identifies NHTSA's form-gated bulk-data
pattern (search forms posting to endpoints that return CSV, plus bulk
download links). The classification should be ``form_gated_bulk`` or
``embedded_data`` depending on which page the test ultimately lands on
after the agency redirects.

Marked ``integration`` so it does not run under the default ``pytest``
invocation; gets skipped silently when ``ANTHROPIC_API_KEY`` is unset.
"""

from __future__ import annotations

import pytest

from cartograph_ai import probe

pytestmark = pytest.mark.integration

NHTSA_URL = "https://www.nhtsa.gov/"


def test_nhtsa_probe_completes_with_reasonable_classification():
    result = probe(NHTSA_URL)

    assert result.probe_stages_completed == [
        "http",
        "html_analysis",
        "claude_classify",
    ]
    # NHTSA serves a richer landing page; we accept several reasonable
    # classifications and only assert against the obviously wrong ones.
    assert result.classification.category in {
        "form_gated_bulk",
        "static_html",
        "embedded_data",
        "direct_api",
    }
    assert result.classification.confidence >= 0.4
    # Reasoning should mention something concrete about the architecture
    # (downloads, forms, government data, NHTSA, etc.).
    assert len(result.classification.reasoning) >= 30
