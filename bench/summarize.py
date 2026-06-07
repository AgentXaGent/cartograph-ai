"""Summarise bench/results.json into a comparison table.

Reads the benchmark output and prints, for each model, the median /
mean / total stats that go into the README economics tables.
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
from collections import defaultdict
from pathlib import Path

DEFAULT_RESULTS_PATH = Path(__file__).parent / "results.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise benchmark results.")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    args = parser.parse_args(argv)

    if not args.results.exists():
        print(f"No results file at {args.results}. Run run_benchmark.py first.")
        return 1

    data = json.loads(args.results.read_text())
    records = [r for r in data.get("results", []) if r.get("status") == "ok"]
    if not records:
        print("No successful records to summarise.")
        return 1

    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_model[r.get("model_actual") or r.get("model_requested")].append(r)

    print(f"\nBenchmark summary (n={len(records)} successful records)")
    print("-" * 72)
    for model, rs in sorted(by_model.items()):
        costs = [r["cost_usd"] for r in rs if r.get("cost_usd") is not None]
        latencies = [r["stage4_latency_seconds"] for r in rs if r.get("stage4_latency_seconds")]
        in_tokens = [r["input_tokens"] for r in rs if r.get("input_tokens")]
        out_tokens = [r["output_tokens"] for r in rs if r.get("output_tokens")]
        confidences = [r["confidence"] for r in rs if r.get("confidence") is not None]
        print(f"\n  model: {model}    n={len(rs)}")
        if costs:
            print(f"    cost/probe:    ${statistics.median(costs):.5f} median   ${statistics.mean(costs):.5f} mean   ${min(costs):.5f}-${max(costs):.5f} range")
        if latencies:
            print(f"    stage4 latency: {statistics.median(latencies):.2f}s median   {statistics.mean(latencies):.2f}s mean")
        if in_tokens:
            print(f"    input tokens:  {int(statistics.median(in_tokens))} median   {int(statistics.mean(in_tokens))} mean")
        if out_tokens:
            print(f"    output tokens: {int(statistics.median(out_tokens))} median   {int(statistics.mean(out_tokens))} mean")
        if confidences:
            print(f"    confidence:    {statistics.median(confidences):.2f} median   {statistics.mean(confidences):.2f} mean")

    # Per-URL agreement table.
    #
    # Issue #1: the top-line classification alone under-counts agreement.
    # A model that answers `direct_api` while explicitly hedging
    # "fall back to static_html if the endpoint 404s" in limitations is
    # not in real disagreement with a model that answered `static_html`
    # (the graphql.org case from the v0.1.0 benchmark). Three markers:
    #
    #   OK     identical top-line classifications
    #   HEDGED top-lines differ, but every disagreeing classification is
    #          named in another record's limitations/reasoning hedge -
    #          counted as agreement
    #   DIFF   real disagreement
    print("\nClassification agreement across models")
    print("-" * 72)
    by_url: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in records:
        model = r.get("model_actual") or r.get("model_requested")
        by_url[r["url"]][model] = r
    ok = hedged = diff = 0
    for url, model_to_rec in sorted(by_url.items()):
        model_to_cls = {m: rec.get("classification", "?") for m, rec in model_to_rec.items()}
        labels = [f"{m.split('-')[1]}={c}" for m, c in sorted(model_to_cls.items())]
        if len(set(model_to_cls.values())) == 1:
            marker = "OK"
            ok += 1
        elif _hedged_agreement(model_to_rec):
            marker = "HEDGED"
            hedged += 1
        else:
            marker = "DIFF"
            diff += 1
        print(f"  [{marker:<6s}] {url:<50s} {' | '.join(labels)}")

    total = ok + hedged + diff
    if total:
        print(
            f"\n  honest agreement: {ok + hedged}/{total} "
            f"({ok} identical, {hedged} hedged-equivalent, {diff} real disagreement)"
        )

    return 0


def _hedged_agreement(model_to_rec: dict[str, dict]) -> bool:
    """True when differing top-line classifications are hedge-covered.

    Two classifications are hedge-equivalent when at least one side
    names the other's answer in its own limitations or reasoning. The
    canonical case (issue #1, graphql.org): Sonnet answered
    `direct_api` with "fall back to static html parsing" in
    limitations; Opus answered `static_html`. Sonnet's hedge covers
    Opus's top-line, so the two are not in real disagreement.

    For every *pair* of differing classifications, coverage in either
    direction is required. Any uncovered pair means real disagreement.
    """
    hedge_text: dict[str, str] = {}
    for model, rec in model_to_rec.items():
        parts = list(rec.get("limitations") or [])
        if rec.get("reasoning"):
            parts.append(rec["reasoning"])
        hedge_text[model] = " ".join(parts).lower()

    def _mentions(model: str, cls: str) -> bool:
        text = hedge_text[model]
        return cls.lower() in text or cls.replace("_", " ").lower() in text

    cls_to_models: dict[str, list[str]] = {}
    for model, rec in model_to_rec.items():
        cls_to_models.setdefault(rec.get("classification", "?"), []).append(model)

    for c1, c2 in itertools.combinations(sorted(cls_to_models), 2):
        covered = any(_mentions(m, c2) for m in cls_to_models[c1]) or any(
            _mentions(m, c1) for m in cls_to_models[c2]
        )
        if not covered:
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
