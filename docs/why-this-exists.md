# Why cartograph exists

If you're here, you probably scanned the [README](../README.md) and want the longer story. This is it.

---

## The pattern

Every site stores data differently. WordPress REST API, Algolia search, embedded hydration JSON, raw HTML, JS-rendered SPA, form-gated datasets behind agency search portals, bulk download pages buried three clicks deep. The list keeps growing as the web fragments into more frameworks, more CMSs, more enterprise platforms.

Figuring out which one you're looking at, before you can extract anything, is manual detective work. You open devtools. You watch the network tab. You view source. You read HTML. You poke at suspicious-looking URLs. After 30 to 90 minutes you have an answer, and you write the extraction.

Then a quarter later the site changes. Or you encounter the next site on your list. Or you're handed twenty URLs from twenty different organizations and the work starts over. None of what you learned the first time is captured anywhere a tool can reuse it.

That repeated discovery is the bottleneck. The actual extraction, once you know what you're dealing with, is mostly straightforward. cartograph automates the half nobody tooled.

You point it at a URL. Claude reads the probe output and tells you what kind of site it is, where the data lives, what to do next. The actual extraction is still your code (and that's the right division of labor: Claude is expensive for bulk extraction, cheap for one-shot classification).

**Probe before extract** is the pattern. It's a category, not a feature.

---

## Three ways to use it

The pattern shows up across audiences. cartograph serves all three from the same engine. The deeper you integrate it, the more it returns. A one-time probe saves the hour you would have spent on a single site. A continuous pipeline saves the quarter you would have spent re-discovering the same sources. An embedded substrate saves whoever or whatever calls it from ever having to know what web scraping is. Value compounds with depth of use.

**Ad hoc (shallow integration).** One URL list, one-time research task, no engineering team. You're a researcher with twenty organizational websites to study. You're a journalist tracking a beat. You're a regulatory analyst pulling state-level data. You're not going to learn Python this week. You want an answer you can hand to a developer (or to your future self) that says: this site stores its data here, here's how to get it, here's roughly what it'll cost in time. One probe, one answer, one hour saved.

**Ongoing (sustained integration).** Continuous signal pipeline. You're maintaining a watchlist of fifty sources that change architecture, structure, or content unpredictably. NHTSA dockets, state DOI bulletins, agency press feeds, SEC filings, competitive intelligence sources. Re-doing discovery manually each quarter is the work that compounds. An ingestion runner that probes against a known landscape and notices when something changes is what you actually need. Now the tool is paying you back every cycle, not once.

**Embedded (deep integration).** Another tool calls cartograph with a URL and gets back a classification. A dashboard accepting URL input from a user. An agent encountering a new web source mid-task. A research assistant pipeline that needs to triage unfamiliar URLs before processing. The caller doesn't need to know anything about web scraping. They get a structured answer and act on it. Now the value isn't capped by what one operator can run. It scales with whatever's calling it.

The substrate is the same. The mode is yours. Each step deeper in the stack pulls more work out of more hands.

---

## Why now

cartograph wasn't economically viable in 2023. Using an LLM to classify a website would have cost more than just paying a contractor to figure it out by hand. The tool is possible in 2026 because three things changed.

Token costs collapsed. A typical probe runs about $0.015 in Claude API calls (measured median across a 15-URL benchmark set). At that price, probing is cheap enough to run unattended at scale.

Claude got accurate enough at structured classification that the operator can review judgment-grade output rather than rewrite the model's work. The intelligence layer doesn't need to be perfect; it needs to be honest about its confidence and good enough to compress 30 to 90 minutes of detective work into 2 seconds. It is.

The Python ecosystem matured around the pieces this tool needs. httpx for async HTTP. BeautifulSoup for HTML parsing. Playwright for the optional browser layer. Optional-extras as a real packaging pattern that lets a tool ship lean and grow heavy only when the user opts in. None of these were as clean two years ago.

The window opened recently. cartograph walks through it.

---

## What it isn't, and what it actually is

cartograph doesn't compete with scrapers. It sits underneath them.

Firecrawl, Apify, ScraperAPI, custom curl + BeautifulSoup. They all give you scraped bytes. They assume you already know what you're asking for. cartograph is what tells you what to ask for. The scrapers operate on bytes; cartograph operates on the question of which bytes. They run on top of its output (the strategy it recommended). They're downstream of cartograph, not competitors.

The actual incumbent cartograph displaces isn't a tool. It's the human spending 30 to 90 minutes manually investigating a site before they can write the extraction. That human's time is the thing being saved. The downstream extraction tool (whatever it is) still runs the same way.

The boundary is deliberate: one URL (or batch) at a time, no recursive crawling, no anti-bot evasion, no CAPTCHA solving. If a site actively defends against automation, cartograph reports that and stops. It runs on your machine with your API key, outputs JSON, and never phones home. No hosted tier, no per-seat pricing, no upsell. The Python package is the product.

---

## What's under the hood

Four stages, progressively escalating from cheap to expensive. HTTP headers and robots.txt first. HTML analysis second (framework fingerprints, embedded data, API discovery). Optional browser rendering third, only when the first two stages can't get clean signal. Claude classification last, turning probe results into a structured recommendation.

Most sites resolve by stage two. The full architecture, including the published Claude prompt and output schema, is in [how it works](how-it-works.md).

---

## Where this is going

Three phases. Each ships and is used in real work before the next starts.

**Phase 1 (active development).** Stages 1, 2, 4. CLI installable from PyPI, importable Python library, JSON + rich terminal output. Full prompt published. Model version pinned with stated reason (reproducibility). Roughly 75% of public sites covered cleanly.

**Phase 2.** Stage 3 enabled via `pip install cartograph-ai[browser]`. Playwright as an optional extra. Uses system Chrome or Edge if available, falls back to Playwright's bundled Chromium only if no system browser exists. Plus three quality-of-life additions for ongoing-pipeline users:
- Caching layer so repeat probes of stable sources are cheap
- Source-change detection: did this site's architecture change since the last probe?
- Diff output: tell me what's different about this source compared to last time

Phase 2 also handles sites where the data is technically public but the access pattern is buried. State DOI metrics are the canonical case: fifty-plus states, fifty-plus different web architectures, all public data, each access pattern different. Claude reverse-engineers the form structure and finds the right endpoint per state.

**Phase 3 (stretch, may not happen).** Probes against authenticated sites: login-required content, API keys, paid subscriptions, cookie-gated sessions. User provides credentials once, encrypted per-source storage, subsequent probes use the stored auth. Output includes auth requirements as part of the strategy. This is real state-management work and a different beast architecturally. It happens if Phase 1 and 2 see real demand for it.

Out of scope, explicitly: recursive crawling, anti-bot bypass tooling, persistent storage of probe results (other than local cache), hosted SaaS or paid tier.

---

## How this came together

A note about who built this and how, because it's relevant to what the project is.

The floor for who can build real software changed. cartograph is evidence.

The author is an insurance product professional who built a working tool because Claude Code and the surrounding Python ecosystem made it possible to bridge domain instinct and shippable software. That's the interesting part of the story. The tool exists because the gap between "I know exactly what this should do" and "I can ship it" got small enough to cross.

This matters in two practical ways.

First, the work itself. The code aims for quality, but it comes from someone learning in public. The bar is "credible attempt at the implied standard." When something is awkward, it's marked, not hidden.

Second, the contribution surface. The intelligence layer (the Claude prompt, the heuristics) is published in full. Improving the prompt is a real contribution path that doesn't require Python expertise. If you're a domain expert who knows how a particular framework or data layer works and you want to teach cartograph to recognize it, you can contribute without writing a line of Python.

Built with assistance from [Claude Code](https://claude.com/claude-code).

cartograph earns its keep by being useful. The build story is part of what it represents, not the point of it.

---

## Read next

- [How it works](how-it-works.md): the architecture in detail, the Claude prompt, the structured output schema, failure modes
- [Contributing](../CONTRIBUTING.md): how to help with failed probes, framework fingerprints, prompt improvements
- [Changelog](../CHANGELOG.md): what changed, when
- Or just go back to the [README](../README.md) and run `cartograph` against a URL of your choosing
