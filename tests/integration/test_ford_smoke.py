"""Integration smoke test for ford.com.

Expected behavior: ford.com is server-rendered Adobe Experience Manager
(AEM). cartograph should identify the AEM fingerprint via Stage 2 and
classify as ``static_html`` (server-rendered content) with
``requires_browser`` False for the landing page itself.

Marked ``integration`` so it does not run under the default ``pytest``
invocation; gets skipped silently when ``ANTHROPIC_API_KEY`` is unset.
"""

from __future__ import annotations

import pytest

from cartograph_ai import probe

pytestmark = pytest.mark.integration

FORD_URL = "https://www.ford.com/"


def test_ford_probe_recognizes_server_rendered_enterprise_site():
    result = probe(FORD_URL)

    assert result.probe_stages_completed == [
        "http",
        "html_analysis",
        "claude_classify",
    ]
    # Reasonable framings for a server-rendered enterprise site.
    assert result.classification.category in {
        "static_html",
        "embedded_data",
        "direct_api",
    }
    # The reasoning should call out either AEM or the server-rendered
    # nature of the content; we look for one of several keywords.
    reasoning_lower = result.classification.reasoning.lower()
    assert any(
        keyword in reasoning_lower
        for keyword in (
            "aem",
            "adobe",
            "experience manager",
            "server-rendered",
            "server rendered",
            "html parsing",
            "static",
        )
    ), f"Reasoning did not mention AEM / server-rendering: {result.classification.reasoning!r}"
