# Changelog

All notable changes to cartograph will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Output schema versioning is tracked separately and described in [/docs/how-it-works.md](docs/how-it-works.md). Material schema changes will be called out in the changelog entry that introduces them.

---

## [Unreleased]

### Changed

- Replaced working-estimate cost figures in README, how-it-works, and why-this-exists with measured values from `bench/run_benchmark.py` (15-URL test set, run 2026-05-28 at commit `c1f8c15`). Median probe cost: $0.015. Median input tokens: 1,767. Sonnet confirmed as pin: 5x cheaper than Opus, higher confidence, 14/15 classification agreement.

### Planned for Phase 2

- Optional Playwright browser extra (`pip install cartograph-ai[browser]`). Uses system Chrome or Edge if present; falls back to Playwright's bundled Chromium only as a last resort.
- Stage 3 of the probe pipeline (JS execution, network interception, hydrated DOM access).
- LLM-assisted discovery for non-obvious public sites where the data is technically accessible but the access pattern is buried (state DOI metrics, agency search portals, form-gated bulk downloads).
- Caching layer for repeat probes of stable sources.
- Source-change detection: notice when a site's architecture changes between probes and surface the diff.
- Diff output mode for ongoing-pipeline users.

### Planned for Phase 3 (stretch, may not happen)

- Probes against authenticated sites: login flows, API keys, paid subscriptions, cookie-gated sessions. Per-source encrypted credential storage.
- Auth-aware extraction strategy output.

### Out of scope (explicitly)

- Recursive crawling
- Anti-bot bypass tooling
- Persistent storage of probe results (beyond local cache)
- Hosted SaaS or paid tier
- Multi-LLM abstraction (cartograph is built around Claude; that decision is documented in /docs/how-it-works.md)

---

## [0.1.0] - 2026-05-28

Initial release. The probe-classify-recommend loop is real and usable. Everything else on the roadmap is Phase 2 or later.

### Added

- Four-stage probe pipeline (stages 1, 2, 4 in v0.1; stage 3 is the Phase 2 browser extra). Architecture in [/docs/how-it-works.md](docs/how-it-works.md).
- CLI command `cartograph-ai <url>` and Python library `from cartograph_ai import probe`.
- Rich terminal output by default; `--json` for machine-consumable output; `--verbose` for full reasoning trace; `--strict` mode refuses to recommend a strategy when confidence is below 0.7; `--debug` prints the assembled payload to stderr before the Claude call.
- Confidence score on every classification, returned as a float in `[0.0, 1.0]`.
- Five named failure modes (auth-walled, anti-bot, novel pattern, hallucinated endpoint, probe-time instability), each handled explicitly and reported in the output.
- Output validation: Pydantic enforces schema shape on the Claude response. Endpoint URLs are cross-referenced against stage 1-3 findings before they ship in the output; anything Claude returns that can't be traced to observed evidence gets stripped and logged.
- Pinned Claude model: `claude-sonnet-4-6`. Reproducibility is a first-class concern; model bumps come with a versioned release and a CHANGELOG entry. Sonnet was selected over Opus after benchmarking: the accuracy delta did not justify the cost delta for this workload.
- Published Claude prompt in /docs/how-it-works.md. Improving it is a contribution path that does not require Python expertise.
- 25 framework fingerprints covering common platforms and data patterns. Full list in [/docs/how-it-works.md](docs/how-it-works.md).
- Output schema v1 with `model`, `probe_stages_completed`, `probe_stages_skipped`, and `skip_reason` fields for transparency. Full schema in [/docs/how-it-works.md](docs/how-it-works.md#the-output-schema).
- Minimal install footprint: `httpx`, `beautifulsoup4`, `lxml`, `anthropic`, `typer`, `pydantic`. No browser, no telemetry, no persistent storage. The probe never leaves your machine except for the Claude call.
- Per-probe cost in the $0.001 to $0.005 range depending on payload size. Stages 1+2 complete in under three seconds; stage 4 adds about one second.

### Project setup

- README, /docs/why-this-exists.md, /docs/how-it-works.md, /CONTRIBUTING.md, /CHANGELOG.md, /LICENSE (MIT).
- Repo at github.com/AgentXaGent/cartograph-ai.
- Distribution on PyPI as `cartograph-ai`. The plain `cartograph` namespace is taken by an unrelated 2019 package, so the suffix is the practical workaround.

---

[Unreleased]: https://github.com/AgentXaGent/cartograph-ai/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AgentXaGent/cartograph-ai/releases/tag/v0.1.0
