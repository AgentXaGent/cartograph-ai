# cartograph

[![PyPI version](https://img.shields.io/pypi/v/cartograph-ai.svg)](https://pypi.org/project/cartograph-ai/)

**Probe before extract.** Give cartograph a URL. It tells you how the site serves data and recommends the optimal extraction strategy. Claude is the intelligence layer. CLI and Python library, equal citizens.

> **Mission.** Establish probe-before-extract as a standard primitive in the agentic web-data field, the way `ripgrep` became universally assumed for codebase search. Low-cost (~$0.015/URL), high-effectiveness (production data in [`docs/real-world-effectiveness.md`](docs/real-world-effectiveness.md)), composable with every extractor (recommender, not competitor), open-source MIT. Cartograph is the canonical implementation; the long-term goal is for the *primitive* to be the standard.

---

## What it solves

Figuring out how a site serves data is the work nobody tooled. You do it by hand, every time, for every site. WordPress here, Algolia search there, embedded hydration JSON on the next one, form-gated bulk CSV on the one after. Open devtools. Watch the network tab. View source. Guess. Build the extraction. Discover the architecture changed last quarter. Repeat.

cartograph automates the discovery half. Claude reads the probe output and tells you what kind of site it is, where the data lives, and what to do next. The actual extraction is still your code (and that's the right division of labor: Claude is expensive for bulk extraction, cheap for one-shot classification).

The value isn't probing one URL. The value is doing this 20 or 200 times against sources that all behave differently, without re-doing the same detective work every time.

---

## Quickstart

```bash
pip install cartograph-ai  # Requires Python 3.11+
export ANTHROPIC_API_KEY=your-key
cartograph-ai https://www.nhtsa.gov/recalls
```

```
www.nhtsa.gov/recalls
└── akamai_ghost (confidence: very high, 0.90)
    HTTP 403 served by an identified CDN/WAF edge (akamai_ghost). The origin
    never saw this request; no content-layer evidence exists.
    Recommended: registry_backdoor — the human site is walled, but NHTSA
    publishes a sanctioned automated path.
    Sanctioned path (NHTSA recalls/complaints/investigations registry):
      - https://api.nhtsa.gov/      (structured_api, auth: none)
      - https://static.nhtsa.gov/   (bulk_download, auth: none)
    Run with --json for machine output.
```

That is the whole thesis in one probe: cartograph fingerprinted the wall in front
of the human site, then routed you to the sanctioned API behind it instead of
trying to break through. For an auto underwriter, `api.nhtsa.gov` is exactly where
recall, complaint, and investigation data lives.

Same probe as a Python call:

```python
from cartograph_ai import probe

result = probe("https://www.nhtsa.gov/recalls")
print(result.classification.category)       # "probe_blocked"
print(result.classification.subcategory)    # "akamai_ghost"
print(result.classification.confidence)     # 0.9
# The human site is walled, but the registry routes you to the sanctioned API:
print(result.recommended_backdoor.endpoints[0].url)  # "https://api.nhtsa.gov/"
```

Or the full JSON output (`--json` from CLI, `result.model_dump()` from library):

```json
{
  "url": "https://www.nhtsa.gov/recalls",
  "model": "none (stage 4 not reached)",
  "classification": {
    "category": "probe_blocked",
    "subcategory": "akamai_ghost",
    "confidence": 0.9
  },
  "extraction_strategy": {
    "method": "registry_backdoor",
    "requires_browser": null,
    "recommended_tool": null
  },
  "recommended_backdoor": {
    "matched_domain": "nhtsa.gov",
    "source_name": "NHTSA (recalls, complaints, investigations, FARS, SGO)",
    "status": "available",
    "endpoints": [
      {"url": "https://api.nhtsa.gov/", "type": "structured_api", "format": "json", "auth": "none"},
      {"url": "https://static.nhtsa.gov/", "type": "bulk_download", "format": "csv/json/zip", "auth": "none"}
    ],
    "registry_version": "2026.06.12"
  }
}
```

This probe never reaches the paid model call: cartograph recognizes the edge block at
stage 1 and answers from the known-source registry, so it costs effectively nothing. A
full four-stage probe of an unknown site runs about 15 seconds and ~$0.015 in tokens at
current Sonnet rates. Either way you are done with the first hour of detective work that
usually eats the front of every scraping project.

---

## Three ways to use it

**Ad hoc.** One URL list, one-time research, no engineering team. Run the CLI, get an answer you can hand to a developer.

**Ongoing.** Continuous signal pipeline. Probe new sources as they appear. Re-validate existing sources on a schedule. Detect when an architecture changes.

**Embedded.** Another tool calls cartograph with a URL and gets back a classification. A dashboard accepting URL input. An agent encountering a new web source mid-task. The caller doesn't need to know anything about web scraping.

The pattern is the same across all three modes. The deeper you integrate it, the more value compounds.

---

## Economics

cartograph's real competitor isn't compute cost. It's human time. Two ways the math lands.

**Batch cost comparison (50 URLs from your typical source list):**

| Approach | Time | Cost |
|---|---|---|
| cartograph (stages 1+2+4) | ~12 minutes | ~$0.75 in tokens |
| Headless browser per URL | ~15-25 minutes | ~$0 compute, ~$50-150 in developer time |
| Manual devtools inspection | ~25-75 hours | ~$2,500-7,500 in labor |

**Token economics for downstream LLM consumers:**

If you're piping into another LLM (agent, RAG, summarizer), the structured probe result is a few KB of clean JSON. Throwing raw HTML at the model instead burns 80-95% of the context window on DOM noise.

| Input to your LLM | Typical size | Input tokens (~) | Cost at Sonnet rates |
|---|---|---|---|
| Raw HTML (typical page) | 200-500 KB | 50K-125K | $0.15-0.38 |
| cartograph probe result | 2-5 KB | 1,500-2,500 | $0.005-0.008 |

Roughly 99% less spend on downstream input tokens. The probe already knows what to fetch and how, so the model doesn't have to figure it out from the raw DOM.

Real-world payloads run larger than initial back-of-envelope estimates; the cost math still favors cartograph by 10-1000x over alternatives. Numbers measured against a 15-URL benchmark set (2026-05-28, commit `c1f8c15`); `claude-sonnet-4-6` pinned. Median probe cost: $0.015. Full results in [`bench/results.json`](bench/results.json).

**Production track record.** Across three production sessions (state DOI probes, dealer/listing sites, and a federal-bill surveillance surface), cartograph has classified **64 URLs at ~$0.97 total spend, 83% successful classifications**, with an estimated 3-4 days of devtools inspection avoided. The qualitative wins are documented in [`docs/real-world-effectiveness.md`](docs/real-world-effectiveness.md) — the `limitations` field has surfaced strategically useful API-instead-of-scraping redirects, and the in-pipeline hallucination-stripping has caught fabricated endpoints before they reached the output (a guard most LLM-extraction tools ship without).

---

## Harder example: enterprise site

Big enterprise sites often look intimidating but reveal their architecture quickly. cartograph's job is to give you an honest fingerprint and point you at where the data actually lives.

```bash
cartograph-ai https://ford.com
```

```
ford.com
└── Adobe Experience Manager (confidence: high)
    Heavily server-rendered HTML. Content available in the initial response.
    Asset paths follow AEM conventions: /content/dam/ for the DAM, dedicated
    assets origin at assets.ford.com with Adobe Dynamic Media renditions.
    No client-side state blob or JSON API surface detected in the served HTML.
    Multi-subdomain topology suggests product data lives elsewhere:
      shop.ford.com (vehicle catalog and configurator)
      owner.ford.com (account and ownership data)
      fordpro.com (commercial fleet)
    Recommended: parse the server-rendered HTML directly for content on ford.com.
    Probe shop.ford.com separately for product data; the architecture there may
    differ (configurator likely needs the browser extra).
```

No Chromium downloaded. No Playwright on disk. cartograph identified the platform, named the asset patterns, and pointed you at the right subdomain to probe next. When you eventually need a browser, you opt in.

---

## What it isn't

cartograph tells you which scraper to use; it doesn't do the scraping. It's a CLI and Python library that runs on your machine with your API key, outputs JSON, and never phones home. The full anti-positioning argument (vs Firecrawl, Apify, manual investigation, and what cartograph deliberately doesn't try to do) is in [/docs/why-this-exists.md](docs/why-this-exists.md).

---

## How it works

Four stages, progressively escalating from cheap to expensive: HTTP probe, HTML analysis, optional JS execution via Playwright (browser extra), and Claude classification. Most sites stop at stage 2. The pinned model is `claude-sonnet-4-6`. Full architecture, the published prompt, the output schema, and named failure modes live in [/docs/how-it-works.md](docs/how-it-works.md).

---

## Honest limits

Every probe returns a confidence score. When cartograph can't get a clean read, it says so. That matters more than the classifications it gets right, because a confidently wrong probe wastes real time downstream.

Phase 1 covers ~75% of public sites without a browser. Auth-walled sites, anti-bot defenses, and genuinely novel architectures get reported honestly as limitations. The `--strict` flag makes cartograph refuse to recommend a strategy when confidence drops below threshold. See [how it works](docs/how-it-works.md) for the full failure-mode taxonomy.

---

## Roadmap

**Phase 1 (active development).** Stages 1, 2, 4. No browser. Covers most public sites. CLI, library, JSON + rich terminal output, full prompt published.

**Phase 2.** Stage 3 via `pip install cartograph-ai[browser]`. Playwright as optional extra. Uses system Chrome or Edge if available, falls back to Chromium only as last resort. Plus: caching layer, source-change detection, diff output for ongoing-mode users.

**Phase 3 (stretch, may not happen).** Probes against authenticated sites: login flows, API keys, paid subscriptions. Per-source encrypted credential storage.

Out of scope: crawler, anti-bot bypass, persistent storage, hosted SaaS.

---

## Contribute

Issues welcome. Failed probes especially welcome. They're the input loop that improves the tool. Pull requests for framework fingerprints, prompt improvements, or test URLs against new patterns are all real contribution paths. See [/CONTRIBUTING.md](CONTRIBUTING.md).

---

## More

- [Why this exists](docs/why-this-exists.md): the pattern, the anti-positioning, how this project came together
- [How it works](docs/how-it-works.md): architecture, the Claude prompt, failure modes, the structured output schema
- [Contributing](CONTRIBUTING.md): workshop principle, how to help
- [Changelog](CHANGELOG.md): what changed, when

---

Built with [Claude Code](https://claude.com/claude-code).
