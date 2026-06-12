# Changelog

All notable changes to cartograph will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Output schema versioning is tracked separately and described in [/docs/how-it-works.md](docs/how-it-works.md). Material schema changes will be called out in the changelog entry that introduces them.

---

## [Unreleased]

### Added (continued)

- Known-source registry + `recommended_backdoor` (#21, the v0.2 headline): cartograph now ships a versioned in-package registry (`cartograph_ai/known_sources.json`) of authoritative sanctioned access paths for well-known government and industry sources whose human-facing edge blocks automated clients. Stage 2.5 looks up the probed host (registrable-domain suffix match); on a hit the registry entry (a) becomes probe evidence the Stage 4 model sees, (b) emits a first-class `recommended_backdoor` block in the output even when the surface probe succeeded, and (c) becomes the primary action on `probe_blocked` (method `registry_backdoor`, `specifics.primary_action = use_recommended_backdoor`). `limitations` prose naming a registry-known source promotes that entry to `recommended_backdoor` (`promoted_from: limitations_cross_reference`). Because registry endpoints appear verbatim in the model payload, they pass the validation cross-reference — the Run 01 over-stripping of `efts.sec.gov`/`data.sec.gov`, fixed at the root for known sources. Honest negatives are entries too: SERFF and Tesla VSR carry `status: none_known` ("no sanctioned path exists" is a verdict, not a shrug). Seeded with all 9 blocked bench sources (7 with sanctioned paths: SEC EDGAR, NHTSA, regulations.gov, CourtListener, FMCSA, plus congress.gov). A `network`-marked CI sanity check (`pytest -m network`) verifies registry URLs still answer; excluded from the default run. Design decisions ratified 2026-06-12: in-package versioned JSON, not runtime-fetched (deterministic, offline-safe, no new network surface). Doctrine: a registry hit is the *correct* resolution of an edge block — cartograph finds the front door, never picks the edge lock.

- `probe_blocked` first-class classification (#12): a 403 served by an identifiable CDN/WAF edge box (Akamai `AkamaiGHost`, CloudFront, AWS WAF/ELB, Cloudflare) now short-circuits into a synthetic `probe_blocked` result with the vendor fingerprint as `classification.subcategory` and the matched evidence in `extraction_strategy.specifics`. No Claude call is made (deterministic, $0), and Stage 1 stops probing the host that just blocked it (no robots/sitemap follow-ups). Previously these probes burned a Stage 4 call to be told `unknown` at 0.20-0.35 confidence — technically honest but operationally indistinguishable from "the model couldn't decide." A 403 with no identifiable vendor falls through to the normal pipeline untouched. Schema note: `probe_blocked` added to the category enum (synthetic, like `probe_unreachable`; Claude never returns it). Strict mode returns `probe_blocked` rather than raising: a vendor-identified block is actionable intelligence, not a 0.0-confidence shrug. Doctrine unchanged: the block is reported honestly; the downstream action is routing to a sanctioned path (see #21), never evasion.

- Honest declared identity hardening (#13): browser-plausible `Accept` / `Accept-Language` headers on all Stage 1 requests (disclosure-compatible; removes a needless tell several gov CDNs reject on), per-domain declared-UA convention support (SEC: `cartograph-ai/{version} contact@email (+repo)` per their published automation policy; contact from `--contact-email` / `ProbeOptions.contact_email` / `CARTOGRAPH_CONTACT_EMAIL`), and per-host politeness pacing (default 1 req/sec on `.gov` hosts and on any host answering 429/503 during the probe; configurable via `ProbeOptions.polite_delay`). The default User-Agent remains the honest `cartograph-ai/{version} (+repo)` string; custom UAs are never overridden. Hard doctrine unchanged: no impersonation, ever.

- Preflight key validation runs once per client per process (cross-check review amendment): batch runs cost N+1 API requests, not 2N. Key validation is a global precondition, not a per-probe dependency.
- Preflight API-key validation before any probe traffic: a shape check on the key plus a single `max_tokens=1` ping to the Anthropic API (~50ms, ~$0.00001). A bad or missing key now raises `PreflightKeyError` before any HTTP request touches the target host, instead of burning Stages 1-2 traffic (and operator IP reputation) on a run that cannot classify. Contract: if Stage 1 fires, the key is good. Opt out with `--no-preflight` / `ProbeOptions(preflight_key_check=False)`. (#18)

### Changed

- Validator redesign (#15): endpoints that fail the verbatim cross-reference are quarantined, not deleted. They move out of `extraction_strategy.specifics` into a new first-class `unverified_candidates` field (value + source path + reason), because unverified is not the same as fake — Run 01 stripped real, documented SEC endpoints (`efts.sec.gov`, `data.sec.gov`) alongside invented WordPress routes, hiding true positives from the operator. Endpoint validation now only runs on values with the shape of a single URL or path (no whitespace, length-capped): the model's own self-hedging prose is never again flagged as a "hallucinated endpoint" (the Run 01 regulations.gov bug). `limitations` remains prose by design and is never touched. `hallucinations_stripped` is retained for backward compatibility and carries the same values as a flat list. `--verbose` renders the quarantine with provenance. Supersedes the #9/#10 design as planned (both closed against Batch 1; this completes the redesign they pointed at).

- Strict mode (`--strict` / `ProbeOptions(strict=True)`) raises a typed `ProbeUnreachableError` on Stage 1 network failure instead of returning the synthetic `probe_unreachable` result (cross-check review amendment). Strict mode is a contract: actionable intelligence or a loud failure; a 0.0-confidence synthetic result is not actionable. The full `ProbeResult` is attached as `.result`. Default mode behavior unchanged.
- Stage 1 network failures (timeout, connection refused, DNS) no longer raise `HTTPProbeError` from `probe()` / exit code 1 from the CLI. They return a structured `probe_unreachable` result: `classification.category = "probe_unreachable"`, subcategory `stage_1_timeout` | `stage_1_refused` | `stage_1_dns_failure` (fallback `stage_1_error`), confidence 0.0, the error preserved in `reasoning` and `limitations`, and `specifics.retry_after_sec` for retry-queue routing. Schema notes: `probe_unreachable` added to the category enum; `extraction_strategy.requires_browser` and `recommended_tool` are now nullable (null only on synthetic results). `HTTPProbeError` is retained for back-compat but no longer raised by `probe()`. (#8)

### Fixed

- Bench summarize prints the matched hedge snippet under every `HEDGED` marker plus a negation-blindness warning, and reports `strict agreement` separately from `honest agreement` (cross-check review amendment: substring matching cannot read negation, so every hedged call is surfaced for human audit rather than silently counted).
- `bench/summarize.py` agreement metric no longer counts hedge-equivalent answers as disagreement (#1). When models' top-line classifications differ, the summary now checks each side's `limitations` and `reasoning` for an explicit hedge naming the other's answer; covered pairs print as `HEDGED` and count toward an `honest agreement` total alongside `OK`. The v0.1.0 benchmark's lone "disagreement" (graphql.org: Sonnet `direct_api` with an explicit `static_html` fallback vs Opus `static_html`) was this exact case. `bench/run_benchmark.py` now records the `limitations` text per probe to support the check.

- `extraction_strategy.estimated_requests` now accepts negative sentinel values from Claude (e.g., `-1` on blocked targets) by coercing them to `null`, and the field is `Optional[int]` with `null` meaning unknown/indeterminate. Previously the Pydantic `ge=0` bound rejected the whole response. Schema note: JSON consumers should treat `estimated_requests: null` as "no honest estimate exists." (#3)

### Added

- `hallucinations_stripped` is now a first-class field on `ProbeResult` / `--json` output (always present, defaults to `[]`) and renders as its own section in `--verbose` text output. Previously the strip was only visible as a generic note in `limitations` and a stderr log line. (#10)

- Published to PyPI: `pip install cartograph-ai` now resolves from the public registry. Project page: https://pypi.org/project/cartograph-ai/.
- `docs/real-world-effectiveness.md` — log of production sessions with measured outcomes. Three sessions to date (64 URLs, ~$0.97 spend, 83% classification success), with qualitative insights from each session that shape v0.2 priorities.

### Documented

- The hallucination-stripping mechanism (stage that verifies endpoints in the model's response against actual probe data and discards fabrications before JSON emission) is now documented as a working feature in the effectiveness log. Was previously implicit. Issue queued to promote `hallucinations_stripped: [...]` to a first-class JSON field in v0.2.
- The `limitations` field has been observed surfacing strategically valuable redirects (e.g., recommending a structured API alternative when scraping is blocked at the surface layer). Currently treated as informational; v0.2 will promote it to a first-class `alternative_paths` output.

### Changed

- Replaced working-estimate cost figures in README, how-it-works, and why-this-exists with measured values from `bench/run_benchmark.py` (15-URL test set, run 2026-05-28 at commit `c1f8c15`). Median probe cost: $0.015. Median input tokens: 1,767. Sonnet confirmed as pin: 5x cheaper than Opus, higher confidence, 14/15 classification agreement.

### Planned for v0.2 (sharpening from cross-session patterns)

- Schema-validation failures: retry-with-correction pass before erroring (Issue: schema-retry).
- Stage 1 timeouts: produce a `probe_unreachable` result instead of an error (Issue: graceful-stage-1).
- Promote `limitations` → `alternative_paths` as a first-class output (Issue: limitations-promotion).
- Surface `hallucinations_stripped` in JSON output and `--verbose` text output (Issue: surface-strip).
- Heuristic: "did you probe an index/listing page when you probably wanted a content page?" (Issue: right-level-probe).

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
