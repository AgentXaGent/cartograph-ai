"""Stage 2: HTML analysis.

Five-pass walk over the served document. Pure Python (BeautifulSoup +
lxml), no LLM call.

Passes:

1. **Framework fingerprinting** via ``cartograph_ai.fingerprints``.
2. **Embedded data extraction** (JSON-LD blocks, ``__NEXT_DATA__``,
   ``__NUXT__`` / Apollo / initial-state hydration assignments). Each
   blob is captured with its key, size, content hash, and either the
   full content (when small) or a leading sample (when large).
3. **API endpoint discovery** via regex over the served HTML for the
   common REST / GraphQL / WordPress / generic ``/_api/`` shapes plus
   Algolia hosts.
4. **Form-gated dataset detection**: enumerate ``<form>`` elements whose
   action looks API/export-bound so the Stage 4 prompt sees the actual
   action URLs, not just a yes/no signal.
5. **Static structure**: title, visible body text length, image/form/
   link counts, SPA-shell flag.

Returns a structured dict suitable for inclusion in the Stage 4 payload.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from cartograph_ai.fingerprints import detect_all as _detect_fingerprints

# Threshold below which we include the full blob content in the payload.
# Above it, we include a leading sample plus a content hash so repeat
# probes can still detect change without blowing up the prompt size.
_BLOB_INLINE_THRESHOLD = 4_000
_BLOB_SAMPLE_HEAD = 500
_MAX_EMBEDDED_BLOBS = 12
_MAX_API_ENDPOINTS = 30
_MAX_FORM_ENDPOINTS = 10
_MAX_BULK_DOWNLOAD_LINKS = 20

# Patterns for API endpoint discovery. Each yields a URL-like substring
# plus a type label. Regexes are conservative: they look for paths
# embedded in string literals (single, double, or backtick quotes) so
# random body text mentioning "/api" does not get picked up.
_API_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\"'`](/api/(?:v\d+/)?[A-Za-z0-9_\-/.]+)[\"'`?]"), "rest_api"),
    (re.compile(r"[\"'`](/wp-json/[A-Za-z0-9_\-/.]+)[\"'`?]"), "wp_json_api"),
    (re.compile(r"[\"'`](/_api/[A-Za-z0-9_\-/.]+)[\"'`?]"), "underscore_api"),
    (re.compile(r"[\"'`](/graphql)[\"'`?]"), "graphql"),
    (
        re.compile(
            r"(https?://[A-Za-z0-9_\-]+(?:-dsn)?\.algolia(?:net)?\.(?:net|com)/[A-Za-z0-9_\-/.?=&%]+)"
        ),
        "algolia_search_api",
    ),
)

_SCRIPT_LIKE = {"script", "style", "noscript", "template"}
_SPA_ROOT_IDS = ("root", "app", "__next", "___gatsby", "nuxt", "app-root")
_BULK_SUFFIXES = (".csv", ".xlsx", ".xls", ".zip", ".json", ".tsv", ".ndjson")
_FORM_API_SEGMENTS = ("/api/", "/_api/", "/search", "/export", "/download")


def analyze_html(html: str, source_url: str) -> dict[str, Any]:
    """Run Stage 2 against the served document.

    Args:
        html: The raw HTML body.
        source_url: The URL the HTML was served from. Used for
            origin-aware analysis (e.g., distinguishing external from
            internal links).

    Returns:
        A dict with keys ``fingerprints``, ``embedded_data``,
        ``api_endpoints``, ``form_gated_endpoints``,
        ``bulk_download_links``, and ``structure``. The shape is stable
        across patch releases per the pinning policy in
        ``docs/how-it-works.md``.
    """
    soup = BeautifulSoup(html, "lxml")

    fingerprints = [
        {
            "id": h.id,
            "category": h.category,
            "description": h.description,
            "evidence": h.evidence,
        }
        for h in _detect_fingerprints(html, soup)
    ]
    return {
        "fingerprints": fingerprints,
        "embedded_data": _extract_embedded_data(soup),
        "api_endpoints": _discover_api_endpoints(html),
        "form_gated_endpoints": _extract_form_gated_endpoints(soup),
        "bulk_download_links": _extract_bulk_download_links(soup),
        "structure": _analyze_structure(soup, source_url),
    }


# ---------------- Embedded data extraction -----------------------------


def _describe_blob(*, key: str, content: str, kind: str) -> dict[str, Any]:
    """Summarize a blob: key + kind + size + hash + content or sample."""
    raw = content.encode("utf-8", errors="ignore")
    size_bytes = len(raw)
    sha = hashlib.sha256(raw).hexdigest()[:16]
    blob: dict[str, Any] = {
        "key": key,
        "kind": kind,
        "size_bytes": size_bytes,
        "sha256_16": sha,
    }
    if size_bytes <= _BLOB_INLINE_THRESHOLD:
        blob["content"] = content
        blob["sample_truncated"] = False
    else:
        blob["sample"] = content[:_BLOB_SAMPLE_HEAD]
        blob["sample_truncated"] = True
    return blob


def _extract_embedded_data(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    # JSON-LD blocks.
    for i, tag in enumerate(soup.find_all("script", type="application/ld+json")):
        content = tag.string or tag.get_text() or ""
        if not content.strip():
            continue
        out.append(_describe_blob(key=f"ld+json[{i}]", content=content, kind="json_ld"))
        if len(out) >= _MAX_EMBEDDED_BLOBS:
            return out

    # __NEXT_DATA__ blob.
    next_tag = soup.find("script", id="__NEXT_DATA__")
    if next_tag is not None and next_tag.string:
        out.append(
            _describe_blob(
                key="__NEXT_DATA__",
                content=next_tag.string,
                kind="hydration",
            )
        )
        if len(out) >= _MAX_EMBEDDED_BLOBS:
            return out

    # Inline scripts containing well-known state assignments.
    state_markers = (
        "window.__NUXT__",
        "window.__APOLLO_STATE__",
        "window.__INITIAL_STATE__",
        "window.__PRELOADED_STATE__",
    )
    for tag in soup.find_all("script"):
        if tag.get("id") == "__NEXT_DATA__":
            continue  # already captured
        if tag.get("type") == "application/ld+json":
            continue  # already captured
        content = tag.string or ""
        if not content:
            continue
        for marker in state_markers:
            if marker in content:
                out.append(
                    _describe_blob(
                        key=marker,
                        content=content,
                        kind="hydration",
                    )
                )
                break  # at most one entry per script
        if len(out) >= _MAX_EMBEDDED_BLOBS:
            break

    return out


# ---------------- API endpoint discovery -------------------------------


def _discover_api_endpoints(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern, endpoint_type in _API_PATTERNS:
        for match in pattern.finditer(html):
            url = match.group(1) if match.lastindex else match.group(0)
            url = url.rstrip("?")
            if url in seen:
                continue
            seen.add(url)
            out.append(
                {
                    "url": url,
                    "type": endpoint_type,
                    "evidence": "string_literal_in_html",
                }
            )
            if len(out) >= _MAX_API_ENDPOINTS:
                return out
    return out


# ---------------- Form-gated dataset endpoints -------------------------


def _extract_form_gated_endpoints(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for form in soup.find_all("form"):
        action = (form.get("action") or "").strip()
        if not action:
            continue
        lowered = action.lower()
        if not any(seg in lowered for seg in _FORM_API_SEGMENTS):
            continue
        method = (form.get("method") or "get").lower()
        inputs = [inp.get("name") for inp in form.find_all("input") if inp.get("name")]
        out.append(
            {
                "action": action,
                "method": method,
                "input_names": inputs[:20],
            }
        )
        if len(out) >= _MAX_FORM_ENDPOINTS:
            break
    return out


# ---------------- Bulk download links ----------------------------------


def _extract_bulk_download_links(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        stem = href.split("?", 1)[0].split("#", 1)[0].lower()
        suffix = next((s for s in _BULK_SUFFIXES if stem.endswith(s)), None)
        if suffix is None:
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(
            {
                "url": href,
                "type": suffix.lstrip("."),
                "text": (link.get_text(strip=True) or None),
            }
        )
        if len(out) >= _MAX_BULK_DOWNLOAD_LINKS:
            break
    return out


# ---------------- Static structure -------------------------------------


def _analyze_structure(soup: BeautifulSoup, source_url: str) -> dict[str, Any]:
    body = soup.find("body")
    title = (soup.title.string.strip() if soup.title and soup.title.string else None)

    if body is None:
        return {
            "title": title,
            "body_present": False,
            "body_visible_text_chars": 0,
            "image_count": 0,
            "form_count": 0,
            "link_count": 0,
            "external_link_count": 0,
            "spa_shell": False,
        }

    visible_segments = [
        s.strip()
        for s in body.find_all(string=True)
        if s.parent is not None and s.parent.name not in _SCRIPT_LIKE
    ]
    visible_text = " ".join(t for t in visible_segments if t)

    links = body.find_all("a", href=True)
    image_count = len(body.find_all("img"))
    form_count = len(body.find_all("form"))
    link_count = len(links)

    origin_host = urlparse(source_url).hostname or ""
    external_link_count = 0
    for a in links:
        href = a["href"]
        if href.startswith(("http://", "https://")):
            host = urlparse(href).hostname or ""
            if host and host != origin_host:
                external_link_count += 1

    spa_shell = False
    if len(visible_text) <= 200:
        for marker_id in _SPA_ROOT_IDS:
            if body.find(id=marker_id) is not None:
                spa_shell = True
                break

    return {
        "title": title,
        "body_present": True,
        "body_visible_text_chars": len(visible_text),
        "image_count": image_count,
        "form_count": form_count,
        "link_count": link_count,
        "external_link_count": external_link_count,
        "spa_shell": spa_shell,
    }
