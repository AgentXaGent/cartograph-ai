"""Tests for the honest agreement metric in ``bench/summarize.py`` (issue #1).

The bench package is not part of the installed distribution, so the
module is loaded by path.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SUMMARIZE_PATH = Path(__file__).parent.parent / "bench" / "summarize.py"
_spec = importlib.util.spec_from_file_location("bench_summarize", _SUMMARIZE_PATH)
summarize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(summarize)


def _rec(model: str, classification: str, *, limitations=None, reasoning=""):
    return {
        "model_actual": model,
        "classification": classification,
        "limitations": limitations or [],
        "reasoning": reasoning,
        "status": "ok",
        "url": "https://example.com/",
    }


def test_identical_classifications_agree():
    recs = {
        "claude-sonnet-4-6": _rec("claude-sonnet-4-6", "direct_api"),
        "claude-opus-4-1": _rec("claude-opus-4-1", "direct_api"),
    }
    assert summarize._hedged_agreement(recs) is True


def test_graphql_case_counts_as_hedged_agreement():
    # The v0.1.0 benchmark's lone "disagreement": Sonnet's limitations
    # explicitly named Opus's answer as its fallback.
    recs = {
        "claude-sonnet-4-6": _rec(
            "claude-sonnet-4-6",
            "direct_api",
            limitations=[
                "If the endpoint returns 404 or 405, fall back to "
                "heuristic #3 (static_html parsing of the docs pages)."
            ],
        ),
        "claude-opus-4-1": _rec("claude-opus-4-1", "static_html"),
    }
    assert summarize._hedged_agreement(recs) is True


def test_hedge_in_reasoning_also_counts():
    recs = {
        "claude-sonnet-4-6": _rec(
            "claude-sonnet-4-6",
            "direct_api",
            reasoning="API endpoint found; static html would also work as fallback.",
        ),
        "claude-opus-4-1": _rec("claude-opus-4-1", "static_html"),
    }
    assert summarize._hedged_agreement(recs) is True


def test_real_disagreement_stays_diff():
    recs = {
        "claude-sonnet-4-6": _rec(
            "claude-sonnet-4-6",
            "direct_api",
            limitations=["Could not verify pagination behaviour."],
        ),
        "claude-opus-4-1": _rec("claude-opus-4-1", "js_rendered_spa"),
    }
    assert summarize._hedged_agreement(recs) is False


def test_main_prints_honest_agreement_line(tmp_path, capsys):
    results = {
        "results": [
            {
                **_rec(
                    "claude-sonnet-4-6",
                    "direct_api",
                    limitations=["fall back to static_html if the endpoint 404s"],
                ),
                "cost_usd": 0.01,
                "confidence": 0.82,
            },
            {
                **_rec("claude-opus-4-1", "static_html"),
                "cost_usd": 0.05,
                "confidence": 0.65,
            },
        ]
    }
    path = tmp_path / "results.json"
    path.write_text(json.dumps(results))
    rc = summarize.main(["--results", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[HEDGED" in out
    assert "strict agreement: 0/1" in out
    assert "honest agreement: 1/1" in out
    assert "1 hedged-equivalent" in out
    # Ghost review amendment: every HEDGED call prints its matched
    # snippet for human audit, plus a negation-blindness warning.
    assert "hedge: claude-sonnet-4-6 names static_html" in out
    assert "audit every HEDGED snippet" in out


def test_hedge_evidence_collected():
    evidence = []
    recs = {
        "claude-sonnet-4-6": _rec(
            "claude-sonnet-4-6",
            "direct_api",
            limitations=["fall back to static_html if the endpoint 404s"],
        ),
        "claude-opus-4-1": _rec("claude-opus-4-1", "static_html"),
    }
    assert summarize._hedged_agreement(recs, evidence=evidence) is True
    assert len(evidence) == 1
    assert "static_html" in evidence[0]
