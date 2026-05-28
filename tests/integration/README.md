# Integration smoke tests

These tests hit the real Anthropic API and the real public web. They
are excluded from the default `pytest` invocation via pytest config in
`pyproject.toml` (the `addopts` line filters out the `integration`
marker).

## Prerequisites

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

If the key is unset the tests are skipped, not failed. The skip is
silent under the default invocation; explicit `-m integration` runs
report the skip reason.

## Running

```bash
# All three smoke tests
pytest -m integration

# One at a time
pytest -m integration -k sasaki
pytest -m integration -k nhtsa
pytest -m integration -k ford
```

Each test makes one full `probe()` call. The Anthropic charge per
test is in the $0.001-$0.005 range at current Sonnet pricing.

## What the tests assert

The assertions are loose on purpose. The model may legitimately land on
slightly different categories across runs (e.g., calling a Next.js
hydration blob "embedded_data" instead of "direct_api"); the goal of
the smoke tests is to catch obvious regressions, not to lock in a
single classification.

| Site | Expected behavior |
|---|---|
| `sasaki.com/projects` | `direct_api` with an `algolia` subcategory; Algolia host in endpoints discovered |
| `nhtsa.gov` | Any non-trivial classification with reasonable reasoning |
| `ford.com` | Server-rendered (static_html or similar); reasoning mentions AEM, Adobe, or server-rendering |

When a smoke test fails:

1. Re-run with `--verbose` to see the full reasoning.
2. Re-run with `--debug` to inspect the assembled probe payload.
3. If the model's call looks reasonable but the assertion is too strict,
   update the test to widen the acceptable set. If the call is wrong,
   investigate the prompt or the Stage 2 findings the prompt received.
