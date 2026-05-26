# Browser Integration Research

The central question: **How much of a web browser do we actually need to embed in this tool?**

The answer determines the project's footprint, install complexity, and whether users need a 300MB Chromium download just to probe a URL.

## The Spectrum

From lightest to heaviest:

### 1. No Browser (HTTP + HTML parsing only)

**Weight:** ~0 MB added. Pure Python.
**Covers:** Tier 1 (APIs) + Tier 2 (embedded data) + Tier 3 (static HTML) = **~75% of sites**
**Tools:** `httpx` + `BeautifulSoup4` + `lxml`
**Limitation:** Cannot execute JavaScript. JS-rendered sites return empty shells.

This is the baseline. Always available. No install friction.

### 2. jsdom (Node.js) / html5-gum (Rust)

**Weight:** ~10-20 MB (Node.js dependency or Rust binary)
**What it does:** Parses HTML and builds a DOM, can execute _some_ JavaScript
**Limitation:** No layout engine, no network stack, no real browser APIs. Most modern JS frameworks fail because they expect `window`, `fetch`, `IntersectionObserver`, CSS parsing, etc.
**Verdict:** ❌ Not enough. The JS that matters (React hydration, API calls during render) won't execute in jsdom. This half-measure adds weight without solving the problem.

### 3. Playwright with System Browser

**Weight:** ~2 MB (Playwright library itself)
**Chromium not bundled** — uses a browser already on the system, or downloads one on demand
**What it does:** Full browser automation. Page render, JS execution, network interception, DOM access.
**Key capability:** `page.route()` / network interception → capture all XHR/fetch requests during page load. This is how we discover hidden APIs.
**Advantage:** If the user already has Chrome/Chromium/Edge installed, Playwright can use it. No redundant browser download.
**Consideration:** `playwright install chromium` downloads ~150 MB if no compatible browser exists.

### 4. Playwright with Bundled Chromium

**Weight:** ~150-300 MB (Chromium binary)
**What it does:** Same as above, fully self-contained
**Advantage:** Zero-config. Works on any machine.
**Disadvantage:** Massive install size for a probe tool. Docker images bloat. CI pipelines slow down.

### 5. Chrome DevTools Protocol (CDP) Direct

**Weight:** ~1-2 MB (CDP client library)
**What it does:** Speaks the Chrome DevTools Protocol directly to any running Chromium instance
**Requirement:** User must have Chrome/Chromium running or available
**Tools:** `pychrome`, `pycdp`, or raw WebSocket
**Advantage:** Lightest possible full-browser integration. No Playwright abstraction layer.
**Disadvantage:** Lower-level API. More code to maintain. Less ecosystem tooling.

### 6. Headless Browser Alternatives

**Ferret (Go):** ~15 MB binary. CDP-based, scriptable. Limited ecosystem.
**Splash (Python/Lua):** Docker-based rendering service. Heavy, meant for server deployment.
**Browserless/Browserbase:** Cloud rendering APIs. No local install. Per-request cost.

## Recommendation: Tiered Architecture

Don't choose one. Layer them.

```
┌─────────────────────────────────────────────┐
│          scrape-probe core                   │
│   (httpx + BS4 — always available, 0 MB)    │
├─────────────────────────────────────────────┤
│     Optional: browser backend                │
│                                              │
│   Option A: playwright (preferred)           │
│     → uses system Chrome/Edge if available   │
│     → downloads Chromium only if needed      │
│     → full network interception              │
│                                              │
│   Option B: CDP direct                       │
│     → lightest, user points to own browser   │
│     → good for server/CI environments        │
│                                              │
│   Option C: cloud render                     │
│     → Browserless API / Browserbase          │
│     → zero local install, per-request cost   │
│     → good for serverless deployment         │
└─────────────────────────────────────────────┘
```

### How this works in practice:

```bash
# Default: no browser needed for 75% of sites
scrape-probe https://sasaki.com/projects
# → Algolia API detected. No browser required.

# Browser needed, system Chrome available
scrape-probe https://designworkshop.com/projects
# → JS-rendered detected. Using system Chrome via Playwright.
# → Network interception found API at /api/projects
# → Reclassified: SPA with hidden API. Future probes won't need browser.

# Browser needed, no system browser
scrape-probe https://designworkshop.com/projects
# → JS-rendered detected. No browser available.
# → Run `scrape-probe install-browser` to download Chromium (~150MB)
# → Or set SCRAPE_PROBE_BROWSER_WS=ws://... to use a remote browser
# → Or set SCRAPE_PROBE_CLOUD_RENDER=browserless to use cloud rendering

# Explicit no-browser mode (fast, lightweight, partial results)
scrape-probe --no-browser https://designworkshop.com/projects
# → JS-rendered detected. Browser required for full probe.
# → Partial result: framework fingerprint (React), no data extracted.
```

### The key architectural decision:

**Browser is a plugin, not a dependency.** The core tool installs clean with `pip install scrape-probe`. Browser support is an optional extra: `pip install scrape-probe[browser]`. Users who only probe API-backed sites never touch Chromium.

```toml
# pyproject.toml
[project.optional-dependencies]
browser = ["playwright>=1.40"]
cloud = ["httpx"]  # already a core dep, but cloud render client code
```

## What We Actually Need from the Browser

For scrape-probe's use case, the browser serves exactly two purposes:

### 1. Network Interception (primary)

Capture all `fetch()` / `XMLHttpRequest` calls fired during page render. This reveals hidden APIs.

```python
async def discover_apis(url):
    requests_captured = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Intercept all network requests
        page.on("request", lambda req: requests_captured.append({
            "url": req.url,
            "method": req.method,
            "resource_type": req.resource_type,
            "headers": req.headers
        }))
        
        await page.goto(url, wait_until="networkidle")
        await browser.close()
    
    # Filter for data requests (JSON APIs, not static assets)
    api_requests = [r for r in requests_captured 
                    if r["resource_type"] in ("xhr", "fetch")
                    and "json" in r.get("headers", {}).get("accept", "")]
    
    return api_requests
```

Once we find the API, we don't need the browser anymore. Future extraction uses direct HTTP.

### 2. Hydrated DOM Access (secondary)

For true "no API" sites, render the page and read the hydrated DOM.

```python
async def extract_hydrated(url, selectors):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        
        # Now page.content() has the fully rendered HTML
        html = await page.content()
        await browser.close()
    
    # Parse with BeautifulSoup as normal
    soup = BeautifulSoup(html, "lxml")
    return extract_with_selectors(soup, selectors)
```

### What we do NOT need:

- Screenshots / visual testing
- Cookie/session management (for v1)
- User interaction simulation (clicks, form fills)
- Multi-page navigation (probe is single-page)
- PDF generation
- Video recording

This means we need roughly **5% of what Playwright can do**. The question is whether that 5% justifies the dependency, or whether raw CDP gives us the same 5% at lower weight.

## Browser Size Comparison

| Approach | Install size | Runtime overhead | Full JS | Network intercept |
|---|---|---|---|---|
| No browser | 0 MB | 0 | ❌ | ❌ |
| jsdom | ~20 MB | Low | Partial | ❌ |
| Playwright (system browser) | ~2 MB | Medium | ✅ | ✅ |
| Playwright (bundled Chromium) | ~150-300 MB | Medium | ✅ | ✅ |
| CDP direct (system browser) | ~1 MB | Low | ✅ | ✅ |
| Cloud render API | 0 MB | Network latency | ✅ | Partial |

## Verdict

**Playwright as optional dependency, using system browser when available.** It's the best ratio of capability to complexity:

- Handles both use cases (network interception + DOM access)
- Ecosystem is mature and well-maintained
- System browser detection avoids the 150MB Chromium download for most users
- `pip install scrape-probe[browser]` keeps core install clean
- If the project grows to need more browser features later, Playwright scales

CDP direct is the lighter alternative if we want to minimize abstraction layers, but the maintenance cost of raw CDP code isn't worth saving ~1 MB over Playwright's client library.

Cloud rendering is the right answer for serverless/lambda deployment but wrong for a CLI tool's default path.
