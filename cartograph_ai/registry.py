"""Stage 2.5: the known-source registry (issue #21).

Bench Runs 01-02 surfaced 9 of 22 Auto Liability sources as blocked at
a CDN/WAF edge. The initial response reached for User-Agent and TLS
fingerprint work; the course correction (2026-06-06) recognized that as
an evasion arms race and rejected it on doctrine. The durable insight:
the blocked sources are blocked at *the wrong URL*. The data lives on
different subdomains, behind documented APIs, or in static bulk
downloads — front-of-house doors the operators publish on purpose.

This module maintains a versioned, in-package registry of those
sanctioned paths (``known_sources.json``) and answers one question:
*given this host, is there a known authoritative back door?* The
orchestrator consults it after Stage 2 (and on edge blocks), emits a
``recommended_backdoor`` block in the output, and feeds the entry to
the Stage 4 model as probe evidence.

Design decisions (Toni-ratified 2026-06-12):

* **In-package, not fetched.** The registry ships with the package and
  updates ride releases. Deterministic, offline-safe, no new network
  surface, no supply chain risk. Staleness is handled by the CI
  live-URL sanity check (``tests/test_registry_live.py``).
* **Honest negatives are entries too.** Sources with no published
  automated path (SERFF, Tesla VSR) carry ``status: none_known`` so
  the output says "no sanctioned path exists" instead of staying
  silent — a verdict, not a shrug.
* **Doctrine.** A registry hit on a blocked source is the *correct*
  resolution of the block. cartograph never escalates past honest
  declared identity; it finds the front door instead.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any, Optional

import httpx

_REGISTRY_RESOURCE = "known_sources.json"


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    """Load and cache the in-package registry."""
    ref = resources.files("cartograph_ai").joinpath(_REGISTRY_RESOURCE)
    with ref.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def registry_version() -> str:
    return load_registry()["registry_version"]


def lookup_host(host: str) -> Optional[dict[str, Any]]:
    """Return the registry entry whose domain matches ``host``, if any.

    Matching is by registrable-domain suffix: ``www.nhtsa.gov`` and
    ``static.nhtsa.gov`` both match the ``nhtsa.gov`` entry. Longest
    key wins so a more specific entry shadows a broader one. The
    returned dict is the entry plus ``matched_domain``.
    """
    if not host:
        return None
    host = host.lower().rstrip(".")
    sources = load_registry()["sources"]
    best: Optional[str] = None
    for domain in sources:
        if host == domain or host.endswith("." + domain):
            if best is None or len(domain) > len(best):
                best = domain
    if best is None:
        return None
    return {"matched_domain": best, **sources[best]}


def lookup_url(url: str) -> Optional[dict[str, Any]]:
    """``lookup_host`` for a full URL."""
    try:
        host = httpx.URL(url).host or ""
    except Exception:
        return None
    return lookup_host(host)


def find_domains_in_text(text: str) -> list[str]:
    """Return registry domains mentioned anywhere in ``text``.

    Used to promote ``limitations`` entries that name a known source
    (issue #21 part 4): when the model's prose points at, say,
    ``api.regulations.gov``, the matching registry entry gets promoted
    to a first-class ``recommended_backdoor`` instead of staying flavor
    text. Matching is conservative substring-on-domain; ordering is
    deterministic (registry order).
    """
    if not text:
        return []
    lowered = text.lower()
    return [d for d in load_registry()["sources"] if d in lowered]
