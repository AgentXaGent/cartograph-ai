# Data Layer Taxonomy

Classification system for how websites serve structured data. Derived from probing 20 real-world websites (landscape architecture firms) and observing the full spectrum.

## Tier 1: Direct API (No Browser Needed)

### REST API
- **Detection:** `/api/`, `/wp-json/`, documented endpoints, API discovery links in `<head>`
- **Examples:** WordPress sites (OLIN), custom backends
- **Extraction:** Direct HTTP requests with pagination
- **Cost:** Cheapest. Pure HTTP, structured JSON responses.

### Search Service API
- **Detection:** Algolia (`algoliaAgent`, app IDs in scripts), Elasticsearch (`/_search`), Typesense, Meilisearch
- **Examples:** Sasaki (Algolia with `AHNZ21XTZ6`)
- **Extraction:** Query the search service directly with its client library or REST API
- **Cost:** Cheap. May have rate limits or require API key (often exposed in client-side code).

### GraphQL
- **Detection:** `/graphql` endpoint, `__schema` introspection, GraphQL query strings in JS bundles
- **Examples:** Gatsby sites, modern React apps
- **Extraction:** Introspection → schema → targeted queries
- **Cost:** Cheap, but query complexity can vary.

## Tier 2: Embedded Data (No Browser Needed)

### Server-Side Hydration Blob
- **Detection:** `__NEXT_DATA__`, `__NUXT__`, `__GATSBY`, `window.__INITIAL_STATE__`
- **Examples:** Next.js, Nuxt, Gatsby, Redux SSR apps
- **Extraction:** Parse the inline `<script>` tag, extract JSON
- **Cost:** Single page fetch. Data is right there in the HTML.

### Inline Data Objects
- **Detection:** `<script>` tags containing JSON arrays/objects not tied to a framework
- **Examples:** LandCollective (`window.people = [...]`)
- **Extraction:** Regex or AST parse of inline scripts
- **Cost:** Single page fetch. Claude helps distinguish data from config.

### JSON-LD / Structured Data
- **Detection:** `<script type="application/ld+json">`
- **Examples:** SEO-optimized sites, e-commerce
- **Extraction:** Parse JSON-LD blocks
- **Cost:** Single page fetch. Often incomplete (SEO subset of full data).

## Tier 3: Static HTML (No Browser Needed, More Work)

### Semantic HTML
- **Detection:** Clean markup, consistent CSS classes, `<article>`, `<table>`, structured divs
- **Examples:** Hand-coded portfolio sites, older CMS templates
- **Extraction:** CSS selectors / XPath. Claude generates the selector map.
- **Cost:** One fetch per listing page + one per detail page. Moderate request count.

### HTML Tables
- **Detection:** `<table>` elements with data rows
- **Extraction:** `pandas.read_html()` or BeautifulSoup table parsing
- **Cost:** Low. Tables are the easiest HTML to parse.

## Tier 4: JS-Rendered (Browser Required)

### SPA with Hidden API
- **Detection:** Empty root div, heavy JS bundles, but XHR/fetch calls visible on render
- **Examples:** React/Vue/Angular apps that fetch from a backend
- **Extraction:** Intercept network requests during browser render → discover the actual API → fall back to Tier 1
- **Cost:** One browser render to discover, then cheap API calls. The browser is diagnostic, not the extractor.
- **This is the key insight:** Many "JS-rendered" sites actually have an API. You just need one browser load to find it.

### SPA with No Accessible API
- **Detection:** All data baked into JS bundles, no XHR/fetch calls, or API requires auth tokens that can't be extracted
- **Examples:** Design Workshop, some Squarespace sites with heavy customization
- **Extraction:** Full browser render + DOM parsing on every page
- **Cost:** Expensive. Browser required for every page load. This is the worst case.

### Hybrid / Partial Hydration
- **Detection:** Some content in HTML, some loaded via JS
- **Examples:** Sites using partial hydration, lazy-loading sections
- **Extraction:** HTML parse for available data + browser for JS-loaded sections
- **Cost:** Variable. Depends on what's in the initial HTML vs. what needs JS.

## Classification Confidence

The probe assigns confidence scores:

| Confidence | Meaning |
|---|---|
| 0.9+ | Clear fingerprint match (e.g., WordPress REST API confirmed) |
| 0.7-0.9 | Strong indicators but not definitive (e.g., looks like Algolia but no app ID found) |
| 0.5-0.7 | Multiple possible classifications, Claude's best guess |
| <0.5 | Ambiguous. Manual inspection recommended. |

## Distribution (Observed)

From the 20-firm sample that spawned this project:

- **~30%** had a discoverable API (REST, search service, or GraphQL)
- **~25%** had usable embedded data (hydration blobs, inline JSON)
- **~20%** were parseable static HTML
- **~25%** required JS execution (and half of those had hidden APIs discoverable via network interception)

The implication: **~75% of sites don't need a browser at all.** And half the remaining 25% only need a browser briefly to discover the real API. True "must render every page" sites are ~12% of the sample.
