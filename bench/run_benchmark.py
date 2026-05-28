"""Sonnet-vs-Opus benchmark harness for cartograph-ai.

For each (URL, model) pair, run the full probe pipeline directly through
the stage modules (so we can capture token counts the public probe()
return type does not expose), record classification + confidence +
input/output tokens + Stage 4 latency + estimated cost, and save a
deterministic JSON record to ``bench/results.json``.

Usage:

    export ANTHROPIC_API_KEY=sk-ant-...
    python bench/run_benchmark.py                 # all URLs, both models
    python bench/run_benchmark.py --models claude-sonnet-4-6
    python bench/run_benchmark.py --urls bench/urls.json
    python bench/run_benchmark.py --resume        # skip URLs already in results.json

Output is a JSON file with one record per (URL, model) tuple. The
file is updated incrementally so a Ctrl-C mid-run still leaves the
completed entries behind.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from cartograph_ai.exceptions import CartographError
from cartograph_ai.stages.claude_classify import classify
from cartograph_ai.stages.html_analysis import analyze_html
from cartograph_ai.stages.http_probe import probe_http
from cartograph_ai.validation import cross_reference_endpoints

# Per-million-token rates in USD. Update when Anthropic pricing changes.
# Values are the public Sonnet/Opus rates as of the benchmark date; the
# CHANGELOG entry that updates these should also bump the constant below.
MODEL_PRICING_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-opus-4-5": {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
}
PRICING_DATE = "2026-05-28"

DEFAULT_MODELS = ("claude-sonnet-4-6", "claude-opus-4-6")
DEFAULT_URLS_PATH = Path(__file__).parent / "urls.json"
DEFAULT_RESULTS_PATH = Path(__file__).parent / "results.json"


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    rates = MODEL_PRICING_USD_PER_MTOK.get(model)
    if not rates:
        return None
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_one(url: str, model: str, http_client: httpx.Client, anthropic_client) -> dict[str, Any]:
    """Run all stages directly so we can capture token usage from Stage 4."""
    record: dict[str, Any] = {
        "url": url,
        "model_requested": model,
        "model_actual": None,
        "timestamp": _now(),
        "status": None,
        "stage1_latency_seconds": None,
        "stage2_latency_seconds": None,
        "stage4_latency_seconds": None,
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "classification": None,
        "subcategory": None,
        "confidence": None,
        "reasoning": None,
        "extraction_method": None,
        "endpoints_discovered_count": 0,
        "limitations_count": 0,
        "stripped_endpoints": [],
        "error": None,
    }

    # Stage 1
    start = time.perf_counter()
    stage1 = probe_http(url, client=http_client)
    record["stage1_latency_seconds"] = time.perf_counter() - start

    if stage1["error"]:
        record["status"] = "stage1_error"
        record["error"] = stage1["error"]
        return record
    if not stage1.get("body"):
        record["status"] = "no_body"
        record["error"] = f"HTTP {stage1['status']} returned no body"
        return record

    # Stage 2
    start = time.perf_counter()
    stage2 = analyze_html(stage1["body"], stage1.get("final_url") or url)
    record["stage2_latency_seconds"] = time.perf_counter() - start

    # Stage 4
    payload = {
        "url": url,
        "stage1": {k: v for k, v in stage1.items() if k != "body"},
        "stage2": stage2,
    }
    try:
        cr = classify(
            probe_payload=payload,
            client=anthropic_client,
            model=model,
        )
    except CartographError as exc:
        record["status"] = "stage4_error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record

    record["model_actual"] = cr.model
    record["stage4_latency_seconds"] = cr.latency_seconds
    record["input_tokens"] = cr.input_tokens
    record["output_tokens"] = cr.output_tokens
    record["cost_usd"] = _cost_usd(cr.model, cr.input_tokens, cr.output_tokens)

    # Validation
    report = cross_reference_endpoints(cr.response, probe_payload=payload)
    record["stripped_endpoints"] = report.stripped_endpoints

    record["classification"] = cr.response.classification
    record["confidence"] = cr.response.confidence
    record["reasoning"] = cr.response.reasoning
    record["extraction_method"] = report.response.extraction_strategy.method
    record["subcategory"] = report.response.extraction_strategy.method
    record["endpoints_discovered_count"] = len(stage2.get("api_endpoints", []))
    record["limitations_count"] = len(cr.response.limitations)
    record["status"] = "ok"
    return record


def _load_urls(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    return data.get("urls", [])


def _save_results(path: Path, results: list[dict[str, Any]]) -> None:
    payload = {
        "_schema_version": "1",
        "_pricing_date": PRICING_DATE,
        "_generated_at": _now(),
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))


def _already_completed(results: list[dict[str, Any]], url: str, model: str) -> bool:
    return any(
        r.get("url") == url and r.get("model_requested") == model and r.get("status") == "ok"
        for r in results
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the cartograph Sonnet-vs-Opus benchmark.")
    parser.add_argument(
        "--urls", type=Path, default=DEFAULT_URLS_PATH,
        help="Path to a URL list JSON (default: bench/urls.json).",
    )
    parser.add_argument(
        "--results", type=Path, default=DEFAULT_RESULTS_PATH,
        help="Output JSON path (default: bench/results.json).",
    )
    parser.add_argument(
        "--models", nargs="+", default=list(DEFAULT_MODELS),
        help="Model strings to benchmark.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip (URL, model) pairs already marked status=ok in the results file.",
    )
    args = parser.parse_args(argv)

    try:
        from anthropic import Anthropic
    except ImportError:
        print("anthropic package is not installed. Run 'pip install cartograph-ai'.", file=sys.stderr)
        return 2

    urls = _load_urls(args.urls)
    if not urls:
        print(f"No URLs in {args.urls}", file=sys.stderr)
        return 1

    existing: list[dict[str, Any]] = []
    if args.resume and args.results.exists():
        existing = json.loads(args.results.read_text()).get("results", [])

    anthropic_client = Anthropic()
    results: list[dict[str, Any]] = list(existing)

    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(10.0, connect=5.0),
        headers={"User-Agent": "cartograph-ai-benchmark/0.1"},
    ) as http_client:
        total = len(urls) * len(args.models)
        done = 0
        for entry in urls:
            url = entry["url"]
            for model in args.models:
                done += 1
                if args.resume and _already_completed(results, url, model):
                    print(f"[{done}/{total}] SKIP (already ok) {model} {url}", flush=True)
                    continue
                print(f"[{done}/{total}] RUN  {model} {url}", flush=True)
                try:
                    record = _run_one(url, model, http_client, anthropic_client)
                except Exception as exc:  # noqa: BLE001
                    record = {
                        "url": url,
                        "model_requested": model,
                        "timestamp": _now(),
                        "status": "unexpected_error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                results = [r for r in results if not (r.get("url") == url and r.get("model_requested") == model)]
                results.append(record)
                _save_results(args.results, results)
                # Pretty-print a one-line summary.
                summary = (
                    f"    status={record['status']} "
                    f"cls={record.get('classification')} "
                    f"conf={record.get('confidence')} "
                    f"in={record.get('input_tokens')} out={record.get('output_tokens')} "
                    f"cost=${record.get('cost_usd'):.5f}"
                    if record.get("cost_usd") is not None
                    else f"    status={record['status']} error={record.get('error')}"
                )
                print(summary, flush=True)

    print(f"\nDone. Results saved to {args.results}.")
    print(f"Total (URL, model) records: {len(results)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
