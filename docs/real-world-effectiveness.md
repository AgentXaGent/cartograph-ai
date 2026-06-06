# Real-World Effectiveness

What cartograph has actually done in production runs. This page is updated after every multi-URL session of substance — trivial one-off probes don't get an entry. The intent is to ground the value claims in measured outcomes, not asserted ones.

**Tool version:** cartograph-ai v0.1.0 | **Model:** claude-sonnet-4-6 | **Approx unit cost:** $0.015 / URL, ~15s / URL.

---

## Roll-up

| Metric | Value |
|---|---|
| Sessions logged | 4 (incl. Session 0 — pre-tool proof of need) |
| URLs / firm domains | 84 (20 manual pre-tool + 64 via cartograph) |
| Tool-era spend | ~$0.97 |
| Wall-clock with parallelism | ~3 minutes (tool-era only) |
| Successful classifications / scrapes | 72 / 84 (~86%) |
| External deliverable shipped | 1 (multi-firm structured-data report to academic researcher, Session 0) |
| Estimated manual time saved (tool-era) | ~3-4 days of devtools inspection |

Session 0 is the load-bearing proof-of-need: we delivered 19/20 firm scrapes for an external academic-researcher client by doing the reconnaissance manually, two days before cartograph v0.1.0 shipped. The tool is the productized version of that recon discipline. The economic case is settled at ~$1 of probe ≈ ~1 week of manual reconnaissance. The remaining engineering questions are about lifting the success rate above 95% and promoting the qualitative wins to first-class outputs.

---

## Session 0 — Multi-Firm Structured-Data Scrape for Academic Research (2026-05-26)

This session ran **two days before cartograph v0.1.0 was tagged**. It is included as the load-bearing proof-of-need: the work that demonstrated cartograph as a discrete tool was worth building.

A client engagement asked for structured project-and-personnel data across 20 firms in a single professional sector (landscape architecture). Every firm had a different website architecture. Some were WordPress-backed. Some were Vercel. Some were fully JS-rendered SPAs. Some 403'd on plain HTTP. Some had no rate limiting; some had aggressive blocks. Figuring out *which architecture each firm used* was the dominant cost, eating the front end of the engagement before any extraction code could be written.

**Numerical results:**
- Firms targeted: 20
- Successful structured-data deliverables: **19 / 20 (95%)**
- NO-GO identified upfront: 1 (fully JS-rendered firm site, would have required full Playwright pipeline)
- Total deliverable: 19 Excel workbooks (project data + personnel data) shipped to the researcher
- Cost: human time only; no per-URL probe cost line item existed yet

**What it actually delivered:**

- 19 structured-data workbooks suitable for downstream academic analysis (project counts, geographic distribution, personnel credentials, leadership tier counts).
- A scaled-by-config dashboard prototype consuming the same `data.json` artifact.
- Specifically: identified that two firms (large enterprise sites) returned 403 on plain HTTP requests and needed structured-API paths (`/wp-json/wp/v2/`) — exactly the kind of fingerprint cartograph would have classified automatically two days later.
- Confirmed Design Workshop pattern (fully JS-rendered) as the single NO-GO, *upfront*, saving the build cost on the only target that would not have worked.

**Why this session mattered:** the pattern of *every site has a different architecture, the cost of figuring it out manually is the dominant cost, and one in twenty will be unworkable regardless* is exactly what cartograph's pre-extraction reconnaissance compresses. Manual recon worked here because we had a small enough target list and enough human attention. The motivation for building cartograph as a tool was the recognition that this same shape recurs constantly and the manual cost compounds.

---

## Session 1 — 51 State Departments of Insurance (2026-05-30)

Probed the company-licensee search pages for all 50 US states plus DC.

**Numerical results:**
- Probed: 42/51 successfully (82%)
- Headless-scrapable (no browser): 37
- Browser-required: 5
- High-confidence (≥0.7): 7
- Errors (Stage 1 + schema validation): 9
- Cost: ~$0.77

**What it actually delivered:**
- Identified HI as WordPress with live `/wp-json/` REST API
- Flagged FL as `form_post_bulk` viable, ME as `form_get_search` viable, AK as full static HTML
- Diagnosed that ~50% of the target URLs were stale 404s
- Flagged Cloudflare/CloudFront blocks on multiple state portals that no naive scraper would have survived

The 7 high-confidence states became the actually-viable target set for downstream extraction. Without cartograph, this set would have been discovered through hours of manual devtools inspection per state. One session, $0.77, the question is answered.

---

## Session 2 — Six high-priority dealer / listing sites (2026-05-30)

Probed CarGurus, Bring a Trailer, Autotrader, two dealer-specific sites, and Cars.com.

**Results:**
- 2 actionable headless targets (CarGurus static_html, BaT WordPress REST)
- 3 browser-required (Cloudflare and Vercel walls)
- 1 fully blocked at Stage 1 (Cars.com ReadTimeout)
- Cost: ~$0.09

The Vercel-checkpoint pattern showed up across two of the six sites — architectural reuse meant one Playwright recipe could serve both. The Cars.com block was clean diagnosis: ReadTimeout at Stage 1, save the week of failed scraper attempts. This session also surfaced an internal schema validation bug (issue #3) which fed back into the issue queue.

---

## Session 3 — Federal-bill surveillance surface (2026-06-06)

Probed 7 surfaces for a daily-watcher pipeline: a primary government page, two legal-alert publications, two trade-press articles, and two bill-tracker indexes.

**Results:**
- 5 high-confidence `static_html` / `direct_api` targets (httpx viable, confidence 0.85-0.88)
- 1 Cloudflare-blocked (the primary government surface) — cartograph recommended a structured API alternative in the `limitations` field
- 2 low-confidence (recommend re-probe at article level rather than index level)
- Cost: ~$0.105
- Parallel wall-clock: ~30 seconds on a single small VPS

**The two qualitative wins from this session are worth calling out:**

### 3a. Unprompted strategic redirect via the `limitations` field

On the Cloudflare-blocked target, cartograph's `limitations` field noted *"it is unknown whether [the domain] exposes a public API that could serve this data without scraping — that should be investigated separately."* That API existed — and is free, well-documented, and rate-limited at 5000 requests per hour. Cartograph saved the entire surveillance architecture from being built around a Cloudflare-bypass scraper for content that was already available as structured JSON.

This is the kind of insight no other LLM-extraction tool in the field surfaces. The `limitations` field is currently treated as informational text. It should be promoted to a first-class `alternative_paths` output that downstream tooling can consume. Issue filed.

### 3b. Hallucination-stripping in production

On one of the WordPress-backed surfaces, the model attempted to fabricate three plausible-looking WordPress REST endpoints (`/wp-json/wp/v2/posts` and slug variants). Cartograph's verification step caught all three before JSON emission and logged: *"cartograph stripped 3 hallucinated endpoint(s) from response."*

This is a working anti-hallucination guard that most LLM-extraction tools in the ecosystem ship without. The mechanism is currently silent in default output — the stripped-count log goes to stderr. It should be surfaced as a first-class field in the JSON output (`hallucinations_stripped: [...]`) so downstream consumers can see what was rejected and why. Issue filed.

---

## Cross-session patterns

These observations recur across the three sessions and shape the v0.2 priority list.

1. **The 18% failure rate has two clear causes.** Schema validation failures (Claude responds outside the strict JSON shape) and Stage 1 timeouts (HTTP probe fails at the network layer). Both are addressable: schema validation should retry-with-correction; Stage 1 should produce a `probe_unreachable` result rather than an error.
2. **The `limitations` field is undervalued.** In Session 3 it surfaced the API-instead-of-scraper redirect that reshaped a whole surveillance architecture. Promote it to a first-class output.
3. **Hallucination-stripping is a real differentiator.** Make it visible.
4. **Re-probe-at-the-right-URL-level is a recurring failure mode.** Both Session 2 (one tag page) and Session 3 (one bill index, one tag page) saw low-confidence results because the probe target was an index/listing page rather than a content page. A "did you probe the right level" heuristic would catch ~20% of low-confidence outcomes.
5. **Cost ratio.** ~$1 of probe ≈ ~1 week of manual reconnaissance. This is the headline number for README economics.

---

## How this log is maintained

Appended on every multi-URL or strategically meaningful session. Trivial one-shot probes don't get entries. The intent is for this to be evidence base, not changelog — so each entry includes the numerical results, what the tool actually delivered, and what changed in our build plans as a result.

Sessions that surface architectural insights (Session 3, hallucination-stripping) generate companion issues in the tracker. Sessions that produce benchmark-quality data (Sessions 1 and 2) feed back into the cost and confidence estimates in `bench/`.
