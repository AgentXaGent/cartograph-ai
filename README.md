# scrape-probe

> Given a URL, classify its data layer and route to the optimal extraction strategy.

Claude-powered web scraping intelligence. Born from a real project scraping 20 websites where every site used a different data architecture — from clean REST APIs to fully JS-rendered SPAs with no accessible data layer.

## The Problem

You have a URL. You want structured data from it. But every website serves data differently, and the right extraction strategy depends on how the site is built. Today this is manual detective work: inspect the page, check network requests, hunt for APIs, guess at rendering strategy. Repeat for every new domain.

No clean open-source tool does this.

## What scrape-probe Does

1. **Probe** — Run lightweight checks to classify how a site serves data
2. **Classify** — Map to a data layer taxonomy (REST API, GraphQL, embedded JSON, static HTML, JS-rendered)
3. **Route** — Recommend the optimal extraction strategy for that classification
4. **Report** — Structured probe report: what was found, confidence level, recommended approach, sample data

## Quick Example

```bash
scrape-probe https://example.com/projects
# → Classification: WordPress REST API
# → Strategy: Direct query /wp-json/wp/v2/projects, no browser needed
# → Sample: 90 records found

scrape-probe https://spa-site.com/work
# → Classification: JS-rendered SPA, hidden API discovered via network interception
# → API: GET /api/v1/projects (JSON, paginated)
# → Strategy: Direct HTTP. Browser no longer needed.
```

## Design Principles

- **Minimal footprint.** Browser is optional. 75% of sites don't need one.
- **Claude as the brain.** LLM interprets ambiguous HTML, identifies data patterns, makes routing decisions.
- **Progressive escalation.** Start cheap (HTTP HEAD), escalate only when needed.
- **Zero config per site.** No custom scraper config for each domain.

## Documentation

- **[Project Spec](docs/wiki/Project-Spec.md)** — Full technical specification
- **[Data Layer Taxonomy](docs/wiki/Data-Layer-Taxonomy.md)** — Classification of web data architectures
- **[Browser Integration](docs/wiki/Browser-Integration.md)** — How much browser do we actually need?

## Status

🔬 **Research / Spec Phase** — Architecture defined, implementation pending.
