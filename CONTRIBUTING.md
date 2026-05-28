# Contributing to cartograph

This repo is run as a workshop, not a billboard. v0.1 is the starting point, not the destination. If you find something broken, file it. If you find something missing, say so. The version number is honest about where the project is.

There are real ways to help, and not all of them require Python.

---

## Five things that move this project forward

**1. Failed probes.** The single highest-value contribution. If you run cartograph against a site and the classification is wrong, missing, or low-confidence on a site that should be easy, open an issue. Include the URL, the probe output (`--json` is fine), and what you expected to see. Failed probes are how the tool learns what the fingerprints actually need to cover.

**2. New framework fingerprints.** If you know a CMS, e-commerce platform, headless framework, or web stack that cartograph doesn't recognize yet, that's a contribution path. Open an issue with the framework name, a public example URL, and a brief note on the telltale signatures (specific HTML patterns, header values, script paths, anything cartograph could detect cheaply). Pull requests welcome for the actual fingerprint addition once the issue is scoped.

**3. Prompt improvements.** The Claude prompt that drives stage 4 classification is published in [/docs/how-it-works.md](docs/how-it-works.md). It is short on purpose, but it can be sharper. If you have prompt-engineering experience and see ways to improve heuristic ordering, output schema clarity, edge-case handling, or no-invention rules, open an issue describing the proposed change and the reasoning. Test cases that demonstrate before/after behavior are gold.

**4. Test URLs.** The README ships with three: Sasaki (Algolia API), NHTSA (form-gated bulk CSV), Ford (Adobe Experience Manager enterprise stack). Each was picked for a specific architecture pattern. If you have a public URL that demonstrates a pattern not in the existing set, especially something the roadmap (CHANGELOG) hasn't reached yet, suggest it.

**5. Documentation.** This README, /docs/why-this-exists.md, and /docs/how-it-works.md are v0.1. If something is unclear, contradictory, or written for the wrong audience, that's a fixable problem. PRs against the docs are welcome.

---

## What this project isn't picking up right now

The CHANGELOG's [Unreleased] section names what's planned for Phase 2 and Phase 3, and what's explicitly out of scope. Read that before opening an issue for a feature; it'll save us both time if the direction has already been considered.

---

## How to file a good issue

A useful issue is specific enough that someone reading it can reproduce what you saw.

For a failed probe:
- The URL you probed
- The exact command you ran (`cartograph-ai https://example.com --json`)
- The full output (paste it; don't summarize)
- What you expected instead
- Anything you noticed about the site that might explain the mismatch (e.g., "this site uses Sanity CMS, here's the giveaway")

For a feature suggestion:
- What you're trying to do
- Why the current behavior doesn't get you there
- A specific proposal, if you have one
- A public URL that demonstrates the case, if relevant

For a documentation issue:
- The doc and the section
- What's unclear
- What you'd expect to read instead

---

## How to send a pull request

The bar is "credible attempt at the implied standard." Reasonable code, reasonable tests, reasonable commit messages.

- Open an issue first if the change is non-trivial. Saves both of us time if the direction needs adjustment.
- Branch from `main`, name the branch after what it does (`fix-shopify-fingerprint`, not `patch-1`).
- Run the existing tests locally before pushing. If you added a feature, add a test.
- Commit messages: short imperative subject line, longer body if the change needs explanation. "Add Sanity CMS fingerprint detection" is fine. "fix" is not.
- Open the PR against `main` with a description that explains the change and links the issue it addresses.

The maintainer (one person, intermittently available) will respond when able. v0.1 is hand-reviewed.

---

## About this project

cartograph is built by a domain professional with AI tooling assistance. The full story is in [why this exists](docs/why-this-exists.md).

What that means for contributors: code reviews from experienced Python developers are genuinely useful (idiomatic patterns, dependency choices, testing structure). And prompt-engineering or domain-fingerprint contributions don't require Python at all. The prompt is published. The fingerprint patterns are pure pattern-matching. If you know how a particular kind of site is built, you can teach cartograph to recognize it without touching the codebase.

---

## Code of conduct

Be useful. Be specific. Don't be a jerk.

This is a small project run by one person. Real contributions (a failed probe, a framework fingerprint, a documentation fix, even a thoughtful question) get heard. Drive-by demands and hot takes get heard too, but expect them to land at the bottom of the priority list. The maintainer is intermittently available; responses take time. We're all balancing real lives.

We all deserve a little grace. Assume good faith when reading other people's issues. Extend the benefit of the doubt before the benefit of the snark.

If you experience or observe behavior that crosses the line, email teekaywhy@otrovertproductions.com. The bar is judgment, not legalese.

---

## License

See [LICENSE](LICENSE) (MIT).
