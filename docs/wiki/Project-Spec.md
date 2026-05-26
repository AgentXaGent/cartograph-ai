# Project Spec — scrape-probe

## Problem

You have a URL. You want structured data from it. But every website serves data differently, and the right extraction strategy depends on how the site is built. Today this is manual detective work: inspect the page, check network requests, hunt for APIs, guess at rendering strategy. Repeat for every new domain.

No clean open-source tool does this. The closest things are generic scraping frameworks (Scrapy, Playwright scripts) that assume you already know _how_ the site works. The discovery step — figuring out what you're dealing with — is the part nobody's automated.

## What scrape-probe Does

1. **Probe** — Given a URL, run a series of lightweight checks to classify how the site serves data
2. **Classify** — Map the site to a data layer taxonomy (REST API, GraphQL, embedded JSON, static HTML, JS-rendered, etc.)
3. **Route** — Recommend (or execute) the optimal extraction strategy for that classification
4. **Report** — Output a structured probe report: what was found, confidence level, recommended approach, sample data

## Core Design Principles

- **Minimal footprint.** Don't install Chromium if you don't need it. Most sites don't need a full browser.
- **Claude as the brain.** The LLM interprets ambiguous HTML, identifies data patterns in markup, and makes routing decisions that rule-based systems can't.
- **Progressive escalation.** Start with the cheapest probe (HTTP HEAD + robots.txt). Escalate to HTML parsing, then JS execution, only when cheaper methods fail.
- **Zero config per site.** The whole point is that you don't need to write a custom scraper config for each domain.

## The Probe Pipeline

### Stage 1: Lightweight HTTP (no browser, no JS)

Cost: ~1 HTTP request. Time: <1s.

- `HEAD` request → status code, headers, `Content-Type`, server fingerprint
- `robots.txt` → sitemap references, crawl rules
- Sitemap.xml → URL structure, content organization
- Response headers → CDN, framework hints (`X-Powered-By`, `X-Generator`, etc.)

### Stage 2: HTML Analysis (no browser, no JS)

Cost: 1 GET request + parsing. Time: 1-3s.

- Fetch raw HTML
- Check for framework fingerprints:
  - WordPress: `/wp-json/wp/v2/` endpoint, `wp-content` paths, REST API discovery link in `<head>`
  - Next.js: `__NEXT_DATA__` script tag, `_next/` paths
  - Nuxt: `__NUXT__` / `window.__NUXT__` embedded state
  - Gatsby: `pageContext` in inline scripts
  - Webflow: `data-wf-` attributes
  - Squarespace: `.squarespace.com` resources, `Static.SQUARESPACE_CONTEXT`
  - Shopify: `Shopify.` global, `/products.json` endpoint
- Check for embedded structured data:
  - JSON-LD (`<script type="application/ld+json">`)
  - `window.__data__`, `window.__INITIAL_STATE__`, or similar hydration blobs
  - Inline `<script>` tags containing JSON arrays/objects (the LandCollective pattern)
- Check for search/API integrations:
  - Algolia: `algoliaAgent`, app ID in scripts (the Sasaki pattern)
  - Elasticsearch: `/_search` endpoints
  - GraphQL: `/graphql` endpoint probe
  - REST patterns: `/api/v1/`, `/api/v2/`, common REST URL structures
- Claude interprets ambiguous patterns (is this embedded JSON actually data, or config?)

### Stage 3: Minimal JS Execution (lightweight browser)

Cost: Browser context spin-up. Time: 3-10s.

- Only triggered when Stage 2 finds indicators of JS-rendered content:
  - Empty `<div id="root">` or `<div id="app">`
  - Minimal HTML body with heavy JS bundles
  - `noscript` fallback content that differs substantially from main content
  - Framework detected but no inline data found
- Execute page JS, wait for DOM settlement
- Re-run Stage 2 analysis on the hydrated DOM
- Capture any XHR/fetch requests fired during render (these often reveal the actual API)
- This is where we need the browser question answered (see [Browser Integration](Browser-Integration))

### Stage 4: Claude Classification

- Feed probe results to Claude
- Output: structured classification + extraction recommendation
- Claude decides: "This is a WordPress site with a REST API. Query `/wp-json/wp/v2/posts?per_page=100` with pagination. Here's the schema."
- Or: "This is a React SPA that fetches from a GraphQL endpoint at `/api/graphql`. Here's the query structure I observed."
- Or: "This is static HTML with no API. Here's a CSS selector map for the data fields."

## Output Format

```json
{
  "url": "https://example.com/projects",
  "probe_timestamp": "2026-05-26T22:30:00Z",
  "classification": {
    "framework": "wordpress",
    "data_layer": "rest_api",
    "js_required": false,
    "confidence": 0.95
  },
  "endpoints_discovered": [
    {
      "url": "/wp-json/wp/v2/projects",
      "type": "rest_api",
      "pagination": "offset",
      "sample_count": 90
    }
  ],
  "extraction_strategy": {
    "method": "api_direct",
    "requires_browser": false,
    "estimated_requests": 2,
    "recommended_tool": "requests"
  },
  "sample_data": { ... },
  "probe_stages_completed": ["http", "html_analysis"],
  "probe_stages_skipped": ["js_execution"],
  "skip_reason": "API discovered in Stage 2, JS execution unnecessary"
}
```

## Architecture

```
CLI / Python API
       │
       ▼
┌─────────────────┐
│   Probe Engine   │ ← orchestrates stages, decides escalation
├─────────────────┤
│ Stage 1: HTTP    │ ← requests/httpx
│ Stage 2: HTML    │ ← BeautifulSoup + pattern matchers
│ Stage 3: JS Exec │ ← [browser component — see research]
│ Stage 4: Claude  │ ← Anthropic API for classification
└─────────────────┘
       │
       ▼
  Probe Report (JSON)
       │
       ▼
  Optional: Execute extraction using recommended strategy
```

## Tech Stack

- **Language:** Python 3.11+
- **HTTP:** `httpx` (async, HTTP/2 support)
- **HTML parsing:** `BeautifulSoup4` + `lxml`
- **JS execution:** TBD — see [Browser Integration Research](Browser-Integration)
- **LLM:** Anthropic Claude API (classification + interpretation)
- **CLI:** `click` or `typer`
- **Output:** JSON (machine) + rich terminal (human)

## Usage (Target UX)

```bash
# Basic probe
scrape-probe https://sasaki.com/projects
# → Classification: Algolia search API (app: AHNZ21XTZ6, index: prod_projects)
# → Strategy: Direct API query, no browser needed
# → Sample: 421 projects found

# Probe with extraction
scrape-probe https://olin.com/work --extract
# → Classification: WordPress REST API
# → Extracting via /wp-json/wp/v2/projects...
# → Wrote 90 records to olin_projects.json

# Probe a JS-rendered site
scrape-probe https://www.designworkshop.com/projects
# → Classification: JS-rendered SPA, no accessible API
# → Strategy: Browser render + DOM extraction
# → Requires: JS execution (Stage 3)
# → CSS selectors mapped for: project name, location, type

# Batch probe
scrape-probe --batch urls.txt --output probe-report.json
```

## Claude's Role (Specifically)

Claude isn't running the scraper. Claude is the _intelligence layer_:

1. **Pattern recognition in HTML** — Distinguishing real data blobs from config objects in inline scripts. Rule-based systems can't do this reliably.
2. **Schema inference** — Given a sample API response or HTML structure, infer the data schema and map it to the user's intent.
3. **Ambiguity resolution** — When a site has multiple possible data layers (e.g., both embedded JSON and an API), Claude decides which is more complete/reliable.
4. **Selector generation** — For static HTML sites, Claude generates CSS selectors or extraction logic from the markup.
5. **Strategy recommendation** — Synthesize all probe results into a clear extraction plan.

This is the piece that doesn't exist in any scraping framework. The discovery intelligence.

## Non-Goals (v1)

- Not a scraping framework. We classify and recommend. Extraction is optional.
- Not a crawler. One URL (or a batch of URLs) at a time. No recursive discovery.
- Not an anti-bot bypass tool. No CAPTCHA solving, no proxy rotation, no fingerprint evasion.
- No persistent storage. Probe results are output, not stored.
