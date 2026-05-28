"""Tests for ``cartograph_ai.cli``.

The CLI is exercised through typer's CliRunner with the underlying
``probe()`` function monkey-patched so no live calls occur.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from cartograph_ai import (
    Classification,
    EndpointDescriptor,
    ExtractionStrategy,
    LowConfidenceError,
    ProbeResult,
)
from cartograph_ai.cli import _confidence_label, app
from cartograph_ai.exceptions import HTTPProbeError

runner = CliRunner()


def _make_probe_result(
    *,
    confidence: float = 0.94,
    low_warning: bool = False,
    limitations: list | None = None,
) -> ProbeResult:
    return ProbeResult(
        url="https://sasaki.com/projects",
        probe_timestamp=datetime(2026, 5, 28, 22, 30, 0, tzinfo=timezone.utc),
        model="claude-sonnet-4-6",
        classification=Classification(
            category="direct_api",
            subcategory="algolia_search",
            confidence=confidence,
            reasoning="Algolia app ID found in inline script.",
        ),
        endpoints_discovered=[
            EndpointDescriptor(
                url="https://AHNZ21XTZ6-dsn.algolia.net/1/indexes/prod_projects/query",
                type="algolia_search_api",
            )
        ],
        extraction_strategy=ExtractionStrategy(
            method="algolia_search",
            requires_browser=False,
            estimated_requests=2,
            recommended_tool="requests",
            specifics={"app_id": "AHNZ21XTZ6"},
        ),
        probe_stages_completed=["http", "html_analysis", "claude_classify"],
        probe_stages_skipped=["js_execution"],
        skip_reason="Phase 1 only",
        limitations=limitations or [],
        low_confidence_warning=low_warning,
    )


# ---------------- Confidence label --------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0.99, "very high"),
        (0.9, "very high"),
        (0.85, "high"),
        (0.6, "moderate"),
        (0.3, "low"),
        (0.1, "very low"),
    ],
)
def test_confidence_label(value, expected):
    assert _confidence_label(value) == expected


# ---------------- --version / --help -----------------------------------


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "cartograph-ai" in result.output
    assert "0.1.0" in result.output


def test_help_text_includes_usage():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Probe a URL" in result.output
    assert "--strict" in result.output
    assert "--json" in result.output


# ---------------- Rich output ------------------------------------------


def test_rich_output_happy_path(monkeypatch):
    monkeypatch.setattr(
        "cartograph_ai.cli.probe", lambda url, options: _make_probe_result()
    )
    result = runner.invoke(app, ["https://sasaki.com/projects"])
    assert result.exit_code == 0
    out = result.stdout
    assert "sasaki.com/projects" in out
    assert "algolia_search" in out
    assert "very high" in out
    assert "Recommended:" in out
    assert "Endpoints:" in out
    assert "algolia.net" in out


def test_rich_output_verbose_includes_stage_trace(monkeypatch):
    monkeypatch.setattr(
        "cartograph_ai.cli.probe", lambda url, options: _make_probe_result()
    )
    result = runner.invoke(app, ["https://sasaki.com/projects", "--verbose"])
    assert result.exit_code == 0
    assert "model:" in result.stdout
    assert "stages:" in result.stdout
    assert "probe_timestamp:" in result.stdout


def test_rich_output_shows_low_confidence_warning(monkeypatch):
    monkeypatch.setattr(
        "cartograph_ai.cli.probe",
        lambda url, options: _make_probe_result(
            confidence=0.4,
            low_warning=True,
            limitations=["Could not identify backend."],
        ),
    )
    result = runner.invoke(app, ["https://x.com/"])
    assert result.exit_code == 0
    assert "Warning" in result.stdout
    assert "below threshold" in result.stdout
    assert "Could not identify backend" in result.stdout


# ---------------- JSON output ------------------------------------------


def test_json_output_emits_valid_probe_result(monkeypatch):
    monkeypatch.setattr(
        "cartograph_ai.cli.probe", lambda url, options: _make_probe_result()
    )
    result = runner.invoke(app, ["https://sasaki.com/projects", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["url"] == "https://sasaki.com/projects"
    assert parsed["classification"]["category"] == "direct_api"
    assert parsed["classification"]["confidence"] == 0.94
    assert parsed["model"] == "claude-sonnet-4-6"
    # Roundtrip back into the schema validates the shape.
    revived = ProbeResult.model_validate(parsed)
    assert revived.url == "https://sasaki.com/projects"


# ---------------- Error paths ------------------------------------------


def test_http_probe_error_exits_with_code_1(monkeypatch):
    def fail(url, options):
        raise HTTPProbeError("ConnectError: name resolution failed")

    monkeypatch.setattr("cartograph_ai.cli.probe", fail)
    result = runner.invoke(app, ["https://nope.invalid/"])
    assert result.exit_code == 1
    # Error goes to stderr; CliRunner captures it into result.stdout when
    # mix_stderr=True (the default). We assert on the combined output.
    assert "cartograph error" in result.output
    assert "ConnectError" in result.output


def test_strict_mode_propagates_low_confidence_error(monkeypatch):
    def strict_fail(url, options):
        assert options.strict is True
        raise LowConfidenceError("Confidence below threshold.")

    monkeypatch.setattr("cartograph_ai.cli.probe", strict_fail)
    result = runner.invoke(app, ["https://x.com/", "--strict"])
    assert result.exit_code == 1
    assert "below threshold" in result.output


# ---------------- Option plumbing --------------------------------------


def test_strict_and_debug_flags_flow_into_options(monkeypatch):
    captured = {}

    def capture(url, options):
        captured["url"] = url
        captured["strict"] = options.strict
        captured["debug"] = options.debug
        captured["model"] = options.model
        captured["timeout"] = options.timeout
        return _make_probe_result()

    monkeypatch.setattr("cartograph_ai.cli.probe", capture)
    result = runner.invoke(
        app,
        [
            "https://sasaki.com/projects",
            "--strict",
            "--debug",
            "--model",
            "claude-haiku-4-5-20251001",
            "--timeout",
            "5",
        ],
    )
    assert result.exit_code == 0
    assert captured["url"] == "https://sasaki.com/projects"
    assert captured["strict"] is True
    assert captured["debug"] is True
    assert captured["model"] == "claude-haiku-4-5-20251001"
    assert captured["timeout"] == 5.0
