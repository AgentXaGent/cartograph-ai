"""Summarise bench/results.json into a comparison table.

Reads the benchmark output and prints, for each model, the median /
mean / total stats that go into the README economics tables.
"""

from __future__ import annotations

import argparse
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
    print("\nClassification agreement across models")
    print("-" * 72)
    by_url: dict[str, dict[str, str]] = defaultdict(dict)
    for r in records:
        model = r.get("model_actual") or r.get("model_requested")
        by_url[r["url"]][model] = r.get("classification", "?")
    for url, model_to_cls in sorted(by_url.items()):
        labels = [f"{m.split('-')[1]}={c}" for m, c in sorted(model_to_cls.items())]
        same = len(set(model_to_cls.values())) == 1
        marker = "OK" if same else "DIFF"
        print(f"  [{marker}] {url:<50s} {' | '.join(labels)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
