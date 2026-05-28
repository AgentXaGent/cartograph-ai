# Benchmark harness

The benchmark compares Stage 4 model choices (default: Sonnet vs Opus)
across a curated URL set so the README economics tables and the model
pin in `cartograph_ai/stages/claude_classify.py` can be backed by real
numbers.

## Quickstart

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Run all URLs against both default models (Sonnet + Opus).
python bench/run_benchmark.py

# Summarise the results.
python bench/summarize.py
```

Expected cost for a full run (15 URLs * 2 models, current pricing):
roughly **$0.05 - $0.30** depending on Stage 4 payload size per URL.
Sonnet typically lands around $0.001 - $0.005 per probe; Opus is ~10x.

## URL list

`bench/urls.json` carries the test set. Each entry has the URL plus an
expected category hint (used for sanity checking, not for assertions).
The default list covers the three Phase-1 reference cases (Sasaki,
NHTSA, Ford) plus a dozen other architectures: WordPress, Next.js,
Shopify, Webflow, Squarespace, Gatsby, AEM, plus a few control cases
that should fingerprint as plain `static_html`.

To add a URL: append an entry under `urls[]`. Keep `expected_category`
loose; the goal is to exercise the model, not lock in a single answer.

## What gets recorded

`bench/results.json` (in `.gitignore`) collects one record per (URL,
model) tuple:

- `url`, `model_requested`, `model_actual`
- `status`: `ok`, `stage1_error`, `no_body`, `stage4_error`, or
  `unexpected_error`
- Stage-level latencies (`stage1_latency_seconds`,
  `stage2_latency_seconds`, `stage4_latency_seconds`)
- Stage 4 token usage (`input_tokens`, `output_tokens`)
- Estimated `cost_usd` based on `MODEL_PRICING_USD_PER_MTOK` (update
  the constant when Anthropic pricing changes; the dated `_pricing_date`
  field in the output flags stale pricing if the run is old)
- Classification: `classification`, `subcategory`, `confidence`,
  `reasoning`
- `extraction_method`, `endpoints_discovered_count`, `limitations_count`
- `stripped_endpoints`: any URLs validation removed as hallucinated

Records are written **after each (URL, model) pair completes**, so a
Ctrl-C mid-run leaves a usable partial file. Re-run with `--resume`
to skip pairs already marked `status=ok`.

## Updating the README economics

The README's cost tables are labelled as working estimates until real
benchmark data lands. After a full run:

1. Pull median Sonnet cost-per-probe from `summarize.py`.
2. Cross-check against `confidence` distribution (low confidence is a
   tell that the prompt or the Stage 2 findings need work).
3. Update the README tables, drop the "working estimate" caveat, and
   add a CHANGELOG entry pointing at the run date + commit SHA.

## Sonnet vs Opus decision criterion

The Phase 1 model pin (`claude-sonnet-4-6`) is the result of this
benchmark. The decision rule:

- If Opus catches cases Sonnet misses on more than ~20% of the URL
  set, and the misses are not trivially fixable by sharpening Stage 2
  findings, the pin moves to Opus.
- Otherwise, the pin stays on Sonnet (~10x cheaper, comparable
  classification accuracy on Phase-1 workloads).

The `summarize.py` agreement table is the artifact that drives that
call. Disagreement rate above ~20% triggers a deeper look at the
divergent URLs.
