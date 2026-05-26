# Data Layer Taxonomy

Classification system for how websites serve structured data. Derived from probing 20 real-world websites (landscape architecture firms) and observing the full spectrum.

## Tier 1: Direct API (No Browser Needed)

### REST API
- **Detection:** `/api/`, `/wp-json/`, documented endpoints, API discovery links in `<head>`
- **Examples:** WordPress sites (OLIN), custom backends
- **Extraction:** Direct HTTP requests with pagination
- **Cost:** Cheapest. Pure HTTP, structured JSON responses.

### Institutional / Government Data API
- **Detection:** Form-based search interfaces, `action=` URLs in `<form>` tags, AJAX endpoints behind search/filter UIs, bulk download links (CSV/XML/JSON), SOAP/REST hybrid endpoints, API documentation pages (often buried at `/api/`, `/developer/`, `/data/`)
- **Examples:** NHTSA (SGO datasets behind search forms + downloadable bulk CSVs), data.gov catalog APIs, SEC EDGAR, BLS statistics
- **Extraction:** Multi-step — discover the form action endpoint, reverse-engineer query params, then paginate through results. Often the actual API is clean once you find it; the burial is in the UI, not the data layer.
- **Cost:** Low once discovered. The probe work is heavier than execution.
- **Key challenge:** These sites often have _two_ data surfaces: a user-facing search form (slow, paginated, session-dependent) and a bulk data endpoint (fast, complete, undocumented). The probe needs to detect both and prefer the bulk path.

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

## Tier 3.5: Buried Datasets (May or May Not Need Browser)

A distinct pattern that cuts across tiers. The data exists and is often well-structured, but it's not where you'd expect.

### Form-Gated Data
- **Detection:** `<form>` elements with search/filter inputs, POST endpoints in form actions, session tokens in hidden fields, pagination via form resubmission
- **Examples:** NHTSA incident search, court record databases, university course catalogs, patent offices
- **Extraction:** Reverse-engineer the form POST params, replay without the form UI. Often reveals a clean API underneath.
- **Cost:** Medium. Discovery requires analyzing form structure. Execution is cheap HTTP once you have the params.
- **Claude's role:** Critical. Reading a government form's HTML and extracting the right POST endpoint + required params + pagination logic is exactly the kind of ambiguous pattern recognition that rules can't handle.

### Bulk Download / Data Catalog
- **Detection:** Links to `.csv`, `.xlsx`, `.json`, `.xml` files. `/download/`, `/export/`, `/bulk/` paths. Data catalog pages listing available datasets.
- **Examples:** NHTSA bulk CSV downloads, Census data files, WHO datasets, NOAA weather data
- **Extraction:** Direct download. The probe's job is to _find_ these links, which are often buried 3-4 clicks deep in navigation.
- **Cost:** Cheapest possible once found. The entire dataset in one HTTP request.
- **Probe strategy:** Check `/data/`, `/datasets/`, `/download/`, `/open-data/`, `/developer/`, sitemap for file extensions. Claude scans page content for "download," "export," "bulk data" language.

### Hybrid Surface + Depth
- **Detection:** Surface HTML shows summary/preview data. Full data requires interaction (click-through, search, or API call).
- **Examples:** NHTSA showing recent incidents on a dashboard but full dataset behind a search interface. Real estate sites showing listings with detail pages behind clicks.
- **Extraction:** Two-pass. Scrape the surface for structure/schema, then use the discovered deeper endpoint for complete data.
- **Cost:** Variable. Depends on whether the deeper endpoint is HTTP-accessible or requires JS.

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

## The Two Extremes This Tool Must Handle

The versatility requirement comes from real-world targets spanning the full spectrum:

**Surface data (easy, but must detect):**
- Portfolio sites with all project data in HTML or embedded JSON
- WordPress sites with REST APIs serving everything
- Sites with Algolia/Elasticsearch backing the search UI

**Buried data (hard, but valuable):**
- NHTSA-style government sites with datasets behind form submissions, search UIs, and bulk download pages buried in navigation trees
- Institutional databases where the surface shows a search box but the real data is a 50MB CSV three links deep
- Sites with two data layers: a thin public surface and a complete dataset accessible only through an undocumented API or export function

The probe must handle both ends. A tool that only works on clean APIs misses the government/institutional data that's often the most valuable. A tool that always fires up a browser is overkill for the 75% of sites that serve data in the HTML.
