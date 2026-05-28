# How cartograph works

This document is for the reader who wants to know what's actually happening when you run `cartograph-ai`. The [README](../README.md) covers what the tool does. This covers how.

If you're trying to use the tool, the README is the right starting point. Come back here when you want to understand the architecture, see the Claude prompt, or know what to expect when the probe fails.

---

## The pipeline at a glance

A probe runs in four stages. Each stage is cheaper to skip than to run. The pipeline escalates only when it has to.

```
URL → HTTP probe → HTML analysis → [optional JS execution] → Claude classification → result
        ~1s           ~1-3s              ~3-10s                     ~1s
       (free)        (free)            (browser extra)          (~$0.015)
```

Stages 1, 2, and 4 always run. Stage 3 only runs when the user installed `cartograph-ai[browser]` and the earlier stages couldn't get clean signal without rendering.

For about 75% of public sites, the probe finishes after stage 2 and Claude classifies based on what HTML analysis found. The remaining 25% need stage 3, and the user opted into that when they installed the browser extra.

---

## Stage 1: HTTP probe

Cheapest possible signal. A HEAD request and two structured-data fetches. No HTML parsing yet. No LLM call.

What gets collected:

- Response status, redirect chain, server headers (especially `Server`, `X-Powered-By`, `X-Generator`, `Content-Type`, anything cache-related).
- `/robots.txt` if it exists. Useful for finding sitemap URLs and for noting which paths the site asks crawlers to avoid.
- Sitemap (`/sitemap.xml`, `/sitemap_index.xml`, or whatever `robots.txt` declared). Sitemaps often expose every URL the site cares about, which is gold for downstream extraction.
- TLS certificate and HTTP version (for completeness; rarely changes the classification but useful in the probe record).

This stage takes under a second on a healthy site. Pure Python over httpx.

---

## Stage 2: HTML analysis

Fetches the page HTML and walks it. Most of the discovery happens here. Still no LLM call.

The analysis runs five passes against the HTML body:

**Framework fingerprinting.** Looks for telltale signatures left by common platforms. `__NEXT_DATA__` script tag means Next.js. `wp-content/` paths or `/wp-json/` references mean WordPress. `/_nuxt/` chunks mean Nuxt. `/content/dam/` and `urn:aaid:aem:` patterns mean Adobe Experience Manager. Webflow leaves `data-wf-` attributes. Squarespace ships `static.squarespace.com`. Shopify exposes `cdn.shopify.com`. The v0.1 set has 25 fingerprints covering framework signatures (Next.js, Nuxt, WordPress, Adobe Experience Manager, Webflow, Squarespace, Shopify, Gatsby), search-as-a-service backends (Algolia, Elasticsearch), API conventions (REST, GraphQL, /wp-json/, /_api/), embedded data signals (JSON-LD, Open Graph, Schema.org, framework state blobs), and structural patterns (form-gated dataset detection, bulk download link detection). The set grows as new fingerprints are contributed.

**Embedded data extraction.** JSON-LD blocks (`<script type="application/ld+json">`). Open Graph and Schema.org tags. Inline JSON in `<script>` tags. Framework state blobs (`__NEXT_DATA__`, `__NUXT__`, `window.__INITIAL_STATE__`, `window.__APOLLO_STATE__`, custom variables like `window.products = [...]`). Each blob is captured with its key, approximate size, and a hash of its content so repeat probes can detect change.

**API endpoint discovery.** Scans inline `<script>` tags and string literals for what look like API references: `/api/`, `/graphql`, `/wp-json/`, `/_api/`, GraphQL endpoint paths, Algolia app IDs, Elasticsearch hosts, REST resource collections. Patterns are heuristic; false positives get filtered by Claude in stage 4.

**Form-gated dataset detection.** Looks for forms whose action posts to an endpoint that returns CSV, JSON, or bulk data (the NHTSA pattern). Also looks for bulk download links: anything ending in `.csv`, `.xlsx`, `.zip`, `.json` that's not obviously a single asset.

**Static structure analysis.** What does the HTML body actually contain? A real page with text and product listings? An empty `<div id="root">` waiting for JS? An e-commerce category page with structured product cards? This is what tells the difference between server-rendered content (extractable now) and a true SPA shell (needs stage 3).

Stage 2 output is a structured dictionary covering what the analysis found. It feeds stage 4. If `cartograph-ai[browser]` was installed and stage 2's findings are inconclusive (mostly-empty body, no detectable data layer), the runner promotes to stage 3.

---

## Stage 3: JS execution (browser extra only)

Skipped entirely unless the user installed `cartograph-ai[browser]` AND stage 2 couldn't get clean signal without rendering. Most probes don't reach here. No LLM call.

When it runs, Playwright launches the page in a headless browser (system Chrome or Edge if available, falling back to Playwright's bundled Chromium only as a last resort). Two things happen during the render:

**Network interception.** Every outgoing request the page makes gets logged. This is how cartograph discovers hidden API endpoints that fire only after page load. If the site fetches `/api/v2/inventory?region=us` during render, that endpoint appears in the probe result even though no static link to it exists in the HTML.

**Hydrated DOM access.** After the page settles, scrape the rendered DOM. This catches content that exists only after client-side JS has run, which is the case for true SPAs with no SSR fallback.

Stage 3 is honest about what it can't do. It runs a real browser, which gets past sites that simply require JS execution. But there's no fingerprint evasion, no stealth plugins, no proxy rotation, no CAPTCHA solving. If the site detects automation and serves a challenge page, cartograph reports that and stops.

---

## Stage 4: The Claude classification

This is the intelligence layer. The structured findings from stages 1-3 become input to a Claude prompt; the response becomes the probe's final classification and recommendation.

### The model

Pinned. The current version uses `claude-sonnet-4-6`. Pinning is deliberate: probes need to be reproducible. If you run cartograph against the same site twice, you want the same answer (modulo the site itself changing). Floating model versions break that guarantee.

Sonnet was selected (over Opus) because Stage 4 is a structured-classification task with clear schemas, not a long-form reasoning task. Sonnet handles it at roughly 1/10th the per-probe cost of Opus, which keeps cartograph's economics viable for embedded use where the tool may be called thousands of times per month. Opus performance was benchmarked against Sonnet on the test URL set; the accuracy delta did not justify the cost delta for this workload.

When the pinned model is deprecated, the upgrade is a versioned release of cartograph with a CHANGELOG entry. Not a silent swap.

### The payload

Claude does not see raw HTML. The probe pipeline collects structured data in stages 1-3 and assembles a JSON dictionary that summarizes what was found: detected frameworks, captured embedded blobs (with sizes and hashes; full content only when small), discovered endpoints, form-gated dataset evidence, structural fingerprints. That dictionary is the input.

Typical payload runs 2-5 KB after structuring. Small enough to fit comfortably in Sonnet's context window. Measured median cost: ~$0.015 per probe (benchmark run 2026-05-28).

When a captured blob is larger than a few KB (some framework state blobs run 100+ KB), the payload includes the blob's key, size, and a content hash plus a short structural sample, not the full content. This keeps token cost predictable and prevents one inline JSON blob from blowing out the context.

To inspect what Claude actually receives for a given probe, run with `--debug` and the assembled payload prints to stderr before the API call.

### The prompt

Published in full. Improving it is a contribution path that doesn't require Python.

```
You are the intelligence layer of cartograph, a tool that classifies how
websites serve data and recommends extraction strategies. You receive
structured probe results from earlier stages and return a classification
plus a recommended approach.

Probe results (JSON):
{probe_results}

Apply these heuristics in order. Stop at the first one that fits.

1. Direct API discovered (REST, GraphQL, Algolia, Elasticsearch).
   Almost always the cleanest path. Recommend it.

2. Embedded data carries the target content (__NEXT_DATA__,
   window.__INITIAL_STATE__, hydration JSON, large inline JSON blobs).
   Extract from HTML; no API call required.

3. Structured static HTML carries the data (product cards, article
   listings, table rows with consistent selectors).
   Recommend HTML parsing with explicit selectors.

4. Form-gated bulk data (the NHTSA pattern: search form POSTs to an
   endpoint that returns CSV or JSON; or a downloads index page links
   to bulk files).
   Recommend form-POST or direct bulk download. Do not recommend
   scraping the search interface itself.

5. JS-rendered SPA with no accessible data layer in the HTML.
   If the browser extra is available, recommend re-probing with it.
   Otherwise, report honestly: this site needs the browser extra.

6. None of the above. Classify as "unknown" and explain what's
   missing or contradictory. Do not invent a strategy.

Return JSON matching this exact schema:

{
  "classification": "direct_api" | "embedded_data" | "static_html"
                  | "form_gated_bulk" | "js_rendered_spa" | "unknown",
  "confidence": float between 0.0 and 1.0,
  "reasoning": "one to three sentences explaining the call",
  "extraction_strategy": {
    "method": short label, e.g., "algolia_search", "wp_rest_api",
              "html_parsing", "form_post_bulk", "browser_render",
    "requires_browser": boolean,
    "estimated_requests": integer,
    "recommended_tool": "requests" | "httpx" | "playwright"
                       | "firecrawl" | "manual",
    "specifics": object with method-specific parameters
                 (endpoint URLs, selectors, query params, etc.)
  },
  "limitations": list of strings describing anything you could not
                determine. Populate when confidence is below 0.7.
}

If confidence is below 0.7, the limitations field MUST list specific
unknowns. "Insufficient information" alone is not acceptable; say what
information would change the classification.

Do not invent endpoints, app IDs, selectors, or parameters that were
not in the probe input. If you would need to guess a value, omit it
and list the gap in limitations.
```

The prompt is short on purpose. Shorter prompts are easier to reason about and cheaper to iterate on when a probe fails.

### The output schema

What cartograph hands back to the caller (CLI or library):

```json
{
  "url": "https://sasaki.com/projects",
  "probe_timestamp": "2026-05-26T22:30:00Z",
  "model": "claude-sonnet-4-6",
  "classification": {
    "category": "direct_api",
    "subcategory": "algolia_search",
    "confidence": 0.94,
    "reasoning": "Discovered Algolia search API app AHNZ21XTZ6 in inline script; framework fingerprints confirm front-end uses Algolia React InstantSearch; sample query returns 90 results in expected schema."
  },
  "endpoints_discovered": [
    {
      "url": "https://AHNZ21XTZ6-dsn.algolia.net/1/indexes/prod_projects/query",
      "type": "algolia_search_api",
      "pagination": "offset",
      "auth": "public_search_key_in_html"
    }
  ],
  "extraction_strategy": {
    "method": "algolia_search",
    "requires_browser": false,
    "estimated_requests": 2,
    "recommended_tool": "requests",
    "specifics": {
      "app_id": "AHNZ21XTZ6",
      "index": "prod_projects",
      "page_size_max": 1000
    }
  },
  "probe_stages_completed": ["http", "html_analysis", "claude_classify"],
  "probe_stages_skipped": ["js_execution"],
  "skip_reason": "Clean API discovered in stage 2; stage 3 unnecessary",
  "limitations": []
}
```

Stable schema. Versioned. Breaking changes get a major version bump, telegraphed in the CHANGELOG ahead of release.

---

## Failure modes (and why "I don't know" is a feature)

The most important thing cartograph does is decline to guess. A confidently wrong probe is worse than no probe. A researcher acting on bad info wastes real money. An embedded caller branching on a hallucinated endpoint loops or breaks.

Every classification ships with a confidence score in `[0.0, 1.0]`. Below a threshold (default 0.7), the result is flagged. The caller decides what to do:

- **Default behavior:** return the strategy with a `low_confidence_warning` field set. Show the warning in the rich terminal output. Caller can act on it or not.
- **`--strict` mode:** refuse to recommend a strategy when confidence is below threshold. Return `classification: "unknown"` and the populated `limitations` list. Good for agents and pipelines where acting on bad info has real cost.

Five named failure classes, each handled explicitly:

1. **Auth-walled site.** Login required, paywall, API key required to reach the data. Phase 1 reports this honestly and points at the authenticated-probe capability planned for Phase 3. It does not try to bypass.
2. **Anti-bot detection.** Cloudflare challenge page, JS-based bot detection, CAPTCHA. cartograph identifies the pattern and stops. Out of scope, by design.
3. **Genuinely novel pattern.** Nothing in the probe matches any known fingerprint. Classification is `unknown`, confidence is low, limitations describe what was contradictory or missing. These probes are the most valuable for improving the tool; logging them helps future fingerprint contributions.
4. **Hallucinated endpoint.** Rare but possible. Claude returns an endpoint that wasn't in the probe input. The validation layer is explicit: Pydantic enforces schema shape on the response, and a cross-reference check confirms that any endpoint URL Claude recommends appears verbatim somewhere in the stage 1-3 findings dictionary. Endpoints that fail the cross-reference get stripped from the output before display and logged. The check is conservative: if a recommended endpoint can't be traced to evidence the probe actually observed, it doesn't ship in the result.
5. **Probe-time site instability.** Transient errors, partial responses, timeouts. The probe retries once with backoff and reports the failure cleanly if the retry also fails. Doesn't make up answers from partial data.

Failure isn't hidden. Every probe result includes `probe_stages_completed`, `probe_stages_skipped`, and `skip_reason`. If something went wrong, it shows up in the output.

---

## Cost and performance

A successful probe of a typical public site:

- **Stages 1+2:** under 3 seconds end to end. Pure Python, no API calls.
- **Stage 4 (Claude):** ~$0.011 to $0.020 per probe at current Sonnet pricing (measured median: $0.015). The range reflects payload variance: simple JSON-LD sites land at the low end, complex enterprise DOMs with large framework state blobs land at the high end.
- **Stage 3 (if it runs):** adds 3 to 10 seconds depending on the site. No API cost.

A batch of 50 probes against a curated source landscape runs in under three minutes and costs $0.05 to $0.25 depending on payload distribution. That's the economic shape of the tool.

These numbers will shift as model pricing changes. The CHANGELOG records when costs or latency move materially.

---

## Minimal footprint

The base install is intentionally small. `pip install cartograph-ai` lands httpx, BeautifulSoup4, lxml, the official Anthropic client, and a CLI framework. That's it. No browser, no headless dependencies, nothing requiring platform-specific binaries.

The browser layer ships as an opt-in extra. `pip install cartograph-ai[browser]` adds Playwright (around 2 MB) and configures the runner to use system Chrome or Edge if either is present. If neither is, Playwright will offer to download Chromium on first run; users can decline if they only want to probe sites the base install can already handle.

This matters for two reasons. First, the base install needs to be cheap enough to drop into any pipeline or container without a fight. Second, an embedded caller (an agent, a dashboard, a downstream pipeline) shouldn't need to ship a browser to use cartograph.

---

## Dependencies, full list

Base install (`pip install cartograph-ai`):
- `httpx` for HTTP
- `beautifulsoup4` + `lxml` for HTML parsing
- `anthropic` (official client) for Claude calls
- `typer` for the CLI (rich terminal output included)
- `pydantic` for output schema validation

Browser extra (`pip install cartograph-ai[browser]`):
- `playwright`

Nothing else. No telemetry, no analytics, no phone-home behavior. cartograph reads the URL you give it, calls the Anthropic API once, and returns a result. The probe never leaves your machine except for the Claude call.

The `anthropic` and `pydantic` versions are pinned with explicit ranges in `pyproject.toml`. Pinning the LLM is meaningless if an upstream client library update breaks the code path; both get treated as version-controlled dependencies.

---

## Pinning, reproducibility, and what changes when

Three things in cartograph are explicitly pinned with rationale:

- **The Claude model version.** Currently `claude-sonnet-4-6`. Listed in the README, the CHANGELOG, and the output schema (`model` field). Bumping is a versioned release.
- **The prompt template.** Published in this doc. Material changes are CHANGELOG entries with before/after diffs.
- **The output schema.** Stable across patch releases. Schema versioning is part of the CHANGELOG. Breaking changes only on major version bumps.

Probe results that depended on a specific version of any of the three will say so in their output. You can re-run a probe against a specific version of the tool and get the same answer (assuming the site itself hasn't changed).

---

## What this doc doesn't cover

- Why the tool exists, who it's for, and the project's story. That's in [/docs/why-this-exists.md](why-this-exists.md).
- How to contribute. That's in [/CONTRIBUTING.md](../CONTRIBUTING.md).
- What changed between versions. That's in [/CHANGELOG.md](../CHANGELOG.md).
- How to use the tool day-to-day. That's the [README](../README.md).
