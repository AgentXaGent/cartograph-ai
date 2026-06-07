"""Schema validation tests.

Covers the rules enforced by ``cartograph_ai/schema.py``:

* enum values for classification category, recommended tool, probe stage
* numeric ranges (confidence in [0, 1]; negative estimated_requests
  coerced to None per issue #3)
* the low-confidence-requires-limitations rule from the prompt
* round-trip JSON encoding for ProbeResult
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from cartograph_ai.schema import (
    Classification,
    ClaudeResponse,
    EndpointDescriptor,
    ExtractionStrategy,
    ProbeResult,
)


# --- ExtractionStrategy ---------------------------------------------------

def _valid_strategy(**overrides):
    base = dict(
        method="algolia_search",
        requires_browser=False,
        estimated_requests=2,
        recommended_tool="requests",
        specifics={"app_id": "AHNZ21XTZ6", "index": "prod_projects"},
    )
    base.update(overrides)
    return ExtractionStrategy(**base)


def test_extraction_strategy_valid():
    s = _valid_strategy()
    assert s.method == "algolia_search"
    assert s.recommended_tool == "requests"
    assert s.specifics["app_id"] == "AHNZ21XTZ6"


def test_extraction_strategy_rejects_unknown_tool():
    with pytest.raises(ValidationError):
        _valid_strategy(recommended_tool="curl")


def test_extraction_strategy_negative_request_count_coerced_to_none():
    # Issue #3: Claude signals "unknown/indeterminate" with -1 on blocked
    # targets. The schema accepts the signal and normalises it to None.
    s = _valid_strategy(estimated_requests=-1)
    assert s.estimated_requests is None


def test_extraction_strategy_accepts_none_request_count():
    s = _valid_strategy(estimated_requests=None)
    assert s.estimated_requests is None


def test_extraction_strategy_defaults_request_count_to_none():
    s = _valid_strategy()
    base = s.model_dump()
    base.pop("estimated_requests")
    s2 = ExtractionStrategy(**base)
    assert s2.estimated_requests is None


def test_extraction_strategy_keeps_zero_request_count():
    s = _valid_strategy(estimated_requests=0)
    assert s.estimated_requests == 0


def test_extraction_strategy_defaults_empty_specifics():
    s = ExtractionStrategy(
        method="html_parsing",
        requires_browser=False,
        estimated_requests=1,
        recommended_tool="httpx",
    )
    assert s.specifics == {}


# --- Classification -------------------------------------------------------

def test_classification_valid():
    c = Classification(
        category="direct_api",
        subcategory="algolia_search",
        confidence=0.94,
        reasoning="Found Algolia app ID in inline script and confirmed via sample query.",
    )
    assert c.category == "direct_api"
    assert 0.0 <= c.confidence <= 1.0


def test_classification_rejects_unknown_category():
    with pytest.raises(ValidationError):
        Classification(
            category="magical_api",  # not in the literal set
            confidence=0.9,
            reasoning="x",
        )


def test_classification_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        Classification(category="direct_api", confidence=1.5, reasoning="x")
    with pytest.raises(ValidationError):
        Classification(category="direct_api", confidence=-0.1, reasoning="x")


def test_classification_rejects_empty_reasoning():
    with pytest.raises(ValidationError):
        Classification(category="direct_api", confidence=0.9, reasoning="")


# --- ClaudeResponse -------------------------------------------------------

def test_claude_response_valid_high_confidence():
    r = ClaudeResponse(
        classification="direct_api",
        confidence=0.94,
        reasoning="Found Algolia app ID in inline script.",
        extraction_strategy=_valid_strategy(),
    )
    assert r.limitations == []


def test_claude_response_low_confidence_requires_limitations():
    """The prompt explicitly requires limitations when confidence < 0.7."""
    with pytest.raises(ValidationError):
        ClaudeResponse(
            classification="unknown",
            confidence=0.4,
            reasoning="Could not get a clean read on the architecture.",
            extraction_strategy=_valid_strategy(),
            limitations=[],
        )


def test_claude_response_low_confidence_with_limitations_passes():
    r = ClaudeResponse(
        classification="unknown",
        confidence=0.4,
        reasoning="Could not get a clean read on the architecture.",
        extraction_strategy=_valid_strategy(),
        limitations=["Server response was truncated; no Stage 2 signal."],
    )
    assert r.confidence == 0.4
    assert len(r.limitations) == 1


def test_claude_response_rejects_unknown_classification():
    with pytest.raises(ValidationError):
        ClaudeResponse(
            classification="single_page_app",  # not in literal set
            confidence=0.9,
            reasoning="x",
            extraction_strategy=_valid_strategy(),
        )


def test_claude_response_rejects_extra_fields():
    """extra='forbid' guards against silent schema drift from the model."""
    with pytest.raises(ValidationError):
        ClaudeResponse.model_validate(
            {
                "classification": "direct_api",
                "confidence": 0.9,
                "reasoning": "x",
                "extraction_strategy": _valid_strategy().model_dump(),
                "limitations": [],
                "rogue_field": "model-added",
            }
        )


# --- ProbeResult ----------------------------------------------------------

def _valid_result(**overrides):
    base = dict(
        url="https://sasaki.com/projects",
        probe_timestamp=datetime(2026, 5, 28, 22, 30, 0, tzinfo=timezone.utc),
        model="claude-sonnet-4-6",
        classification=Classification(
            category="direct_api",
            subcategory="algolia_search",
            confidence=0.94,
            reasoning="Algolia app ID + confirmed sample query.",
        ),
        endpoints_discovered=[
            EndpointDescriptor(
                url="https://AHNZ21XTZ6-dsn.algolia.net/1/indexes/prod_projects/query",
                type="algolia_search_api",
                pagination="offset",
                auth="public_search_key_in_html",
            )
        ],
        extraction_strategy=_valid_strategy(),
        probe_stages_completed=["http", "html_analysis", "claude_classify"],
        probe_stages_skipped=["js_execution"],
        skip_reason="Clean API discovered in stage 2; stage 3 unnecessary",
        limitations=[],
    )
    base.update(overrides)
    return ProbeResult(**base)


def test_probe_result_valid():
    r = _valid_result()
    assert r.url == "https://sasaki.com/projects"
    assert r.model == "claude-sonnet-4-6"
    assert r.classification.category == "direct_api"
    assert r.low_confidence_warning is False


def test_probe_result_rejects_invalid_stage_name():
    with pytest.raises(ValidationError):
        _valid_result(probe_stages_completed=["http", "css_analysis"])  # not a stage


def test_probe_result_json_roundtrip():
    r = _valid_result()
    blob = r.model_dump_json()
    revived = ProbeResult.model_validate_json(blob)
    assert revived == r


def test_probe_result_json_shape_matches_docs_example():
    """Top-level keys must match the example in docs/how-it-works.md."""
    r = _valid_result()
    blob = r.model_dump(mode="json")
    expected_keys = {
        "url",
        "probe_timestamp",
        "model",
        "classification",
        "endpoints_discovered",
        "extraction_strategy",
        "probe_stages_completed",
        "probe_stages_skipped",
        "skip_reason",
        "limitations",
        "hallucinations_stripped",
        "low_confidence_warning",
    }
    assert set(blob.keys()) == expected_keys


def test_probe_result_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ProbeResult.model_validate(
            {
                **_valid_result().model_dump(mode="json"),
                "unexpected": "drift",
            }
        )
