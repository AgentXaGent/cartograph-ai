"""Stage 1: HTTP probe.

Cheapest possible signal collection. No HTML parsing, no LLM call.
Fetches the URL with redirect following, the response headers and HTTP
version, ``/robots.txt`` if present, and any sitemaps declared by
``robots.txt`` or living at the conventional paths.

The output is a structured ``dict`` (not a Pydantic model) so it
serialises cleanly into the Stage 4 prompt payload.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Optional

import httpx

from cartograph_ai._version import __version__

log = logging.getLogger("cartograph_ai")

DEFAULT_USER_AGENT = (
    f"cartograph-ai/{__version__} (+https://github.com/AgentXaGent/cartograph-ai)"
)
"""User-Agent string. Identifies the tool honestly so site owners can
distinguish probes from generic scrapers."""

CONTACT_EMAIL_ENV_VAR = "CARTOGRAPH_CONTACT_EMAIL"
"""Environment variable consulted for the operator contact email when
none is passed explicitly. Used for per-domain declared-UA conventions
(currently SEC). This is disclosure, not evasion (issue #13)."""

DEFAULT_ACCEPT_HEADERS: dict[str, str] = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
"""Browser-plausible Accept headers. Several gov CDNs reject requests
with httpx's bare defaults; declaring ordinary content-negotiation
headers is honest (we do want HTML) and removes a needless tell."""

# Hosts whose published automation policy asks for a declared contact in
# the User-Agent. SEC documents the convention explicitly:
# "Sample Company Name AdminContact@<sample company domain>.com"
_DECLARED_CONTACT_HOST_SUFFIXES: tuple[str, ...] = ("sec.gov",)

_POLITE_DELAY_GOV_DEFAULT = 1.0
"""Default seconds between requests to the same .gov host (issue #13)."""


def user_agent_for(
    url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    contact_email: Optional[str] = None,
) -> str:
    """Return the effective User-Agent for ``url``.

    For hosts that publish a declared-UA convention (SEC), append the
    operator contact email per their documented format. Explicit custom
    user agents are never overridden. The contact email comes from the
    ``contact_email`` argument or the ``CARTOGRAPH_CONTACT_EMAIL``
    environment variable.
    """
    if user_agent != DEFAULT_USER_AGENT:
        return user_agent
    host = httpx.URL(url).host or ""
    if not any(
        host == sfx or host.endswith("." + sfx)
        for sfx in _DECLARED_CONTACT_HOST_SUFFIXES
    ):
        return user_agent
    email = contact_email or os.environ.get(CONTACT_EMAIL_ENV_VAR)
    if not email:
        log.warning(
            "cartograph: %s asks automated clients to declare a contact "
            "in the User-Agent; set %s (or ProbeOptions.contact_email) "
            "to comply. Proceeding with the default UA.",
            host,
            CONTACT_EMAIL_ENV_VAR,
        )
        return user_agent
    # No repo URL on declared-contact hosts. Empirical finding
    # (2026-06-12 A/B from a residential origin, issue #24): SEC's
    # Akamai filter passes 'cartograph-ai/x.y email' (200) but rejects
    # the same string with the '(+https://...)' repo-URL suffix (403).
    # The trimmed form is still full disclosure -- tool, version,
    # contact -- and matches the format SEC documents. Doctrine intact:
    # this is complying with their convention more exactly, not hiding.
    return f"cartograph-ai/{__version__} {email}"


class _HostPacer:
    """Per-host politeness pacing for the requests inside one probe.

    Defaults: 1 req/sec on ``.gov`` hosts; any host that answers 429 or
    503 gets paced at 1 req/sec for the remainder of the probe. A probe
    makes at most ~5 requests (page, robots, up to 3 sitemaps) so the
    worst-case cost is a few seconds. Configurable via ``polite_delay``.
    """

    def __init__(self, polite_delay: Optional[float] = None) -> None:
        self._configured = polite_delay
        self._throttled_hosts: set[str] = set()
        self._last_request: dict[str, float] = {}

    def _delay_for(self, host: str) -> float:
        if self._configured is not None:
            return self._configured
        if host in self._throttled_hosts or host.endswith(".gov"):
            return _POLITE_DELAY_GOV_DEFAULT
        return 0.0

    def wait(self, url: str) -> None:
        host = httpx.URL(url).host or ""
        delay = self._delay_for(host)
        last = self._last_request.get(host)
        if delay > 0 and last is not None:
            elapsed = time.monotonic() - last
            if elapsed < delay:
                time.sleep(delay - elapsed)
        self._last_request[host] = time.monotonic()

    def note_response(self, url: str, status: Optional[int]) -> None:
        if status in (429, 503):
            host = httpx.URL(url).host or ""
            self._throttled_hosts.add(host)

# Headers worth surfacing to Stage 4. Server / X-Powered-By / generator
# headers are the highest-signal ones; we also keep Content-Type for
# basic sanity and cache headers because they sometimes leak the CDN /
# platform in front of the origin.
_INTERESTING_HEADERS: tuple[str, ...] = (
    "server",
    "x-powered-by",
    "x-generator",
    "x-drupal-cache",
    "x-aem-instance",
    "x-host",
    "x-vercel-cache",
    "x-vercel-id",
    "x-amz-cf-pop",
    "x-amz-cf-id",
    "x-amzn-waf-action",
    "x-cache",
    "via",
    "cf-ray",
    "content-type",
    "content-encoding",
    "cache-control",
    "etag",
    "last-modified",
)



# --- WAF / CDN edge-block detection (issue #12) ---------------------------
#
# A 403 served by an identifiable CDN/WAF edge box is a different signal
# from a content-layer 403: the origin never saw the request, so no
# content-layer evidence exists and Stage 2/4 have nothing real to read.
# Detection is conservative: the vendor fingerprint must be positively
# identified from response headers or block-page body markers cartograph
# already received. An unidentified 403 falls through to the normal
# pipeline untouched.
#
# Doctrine note: detection reports the block honestly. cartograph never
# escalates past honest declared identity; the downstream action is to
# route to a sanctioned API/bulk endpoint (issue #21), never to evade.

_BLOCK_STATUS_CODES: frozenset = frozenset({403})
"""Status codes eligible for edge-block detection. 401 is handled as
auth-walled; 429/503 are pacing signals, not blocks."""


def detect_waf_block(
    status: Optional[int],
    headers: httpx.Headers,
    body: str,
) -> Optional[dict[str, Any]]:
    """Identify the CDN/WAF vendor behind an edge block.

    Returns ``{"vendor": <token>, "evidence": [<str>, ...]}`` when the
    status is block-eligible and a vendor fingerprint is positively
    identified, else ``None``. Vendor tokens map to the issue #12
    taxonomy: ``akamai_ghost`` | ``cloudfront`` | ``aws_waf_elb`` |
    ``cloudflare``.
    """
    if status not in _BLOCK_STATUS_CODES:
        return None

    server = (headers.get("server") or "").lower()
    body_lower = (body or "")[:20_000].lower()
    evidence: list[str] = []

    # Akamai (AkamaiGHost edge; NHTSA family, SEC EDGAR, tesla-vsr, FMCSA)
    if "akamaighost" in server or "akamainetstorage" in server:
        evidence.append(f"server header: {headers.get('server')}")
    if "errors.edgesuite.net" in body_lower:
        evidence.append("block page references errors.edgesuite.net")
    if "reference&#32;#" in body_lower:
        evidence.append("Akamai reference-number block page")
    if evidence:
        return {"vendor": "akamai_ghost", "evidence": evidence}

    # CloudFront (regulations.gov, courtlistener)
    if "cloudfront" in server:
        evidence.append(f"server header: {headers.get('server')}")
    if "generated by cloudfront" in body_lower:
        evidence.append("CloudFront-generated block page")
    if not evidence and ("x-amz-cf-id" in headers or "x-amz-cf-pop" in headers):
        evidence.append("x-amz-cf-* response headers present")
    if evidence:
        return {"vendor": "cloudfront", "evidence": evidence}

    # AWS WAF / ELB (SERFF-PA)
    if "awselb" in server:
        evidence.append(f"server header: {headers.get('server')}")
    if "x-amzn-waf-action" in headers:
        evidence.append(
            f"x-amzn-waf-action header: {headers.get('x-amzn-waf-action')}"
        )
    if evidence:
        return {"vendor": "aws_waf_elb", "evidence": evidence}

    # Cloudflare (not in the Auto Liability bench, but the most common
    # WAF on the public web; cheap to recognise honestly)
    if "cloudflare" in server and "cf-ray" in headers:
        evidence.append(
            f"server header: {headers.get('server')}; "
            f"cf-ray: {headers.get('cf-ray')}"
        )
    if "attention required! | cloudflare" in body_lower:
        evidence.append("Cloudflare challenge page title")
    if evidence:
        return {"vendor": "cloudflare", "evidence": evidence}

    return None


_SITEMAP_DECL_RE = re.compile(r"(?im)^\s*sitemap:\s*(\S+)\s*$")
"""Match a Sitemap directive in robots.txt (case-insensitive, per-line)."""

_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.IGNORECASE)
"""Lightweight <loc> extractor; we count URLs, we do not deeply validate."""

# Sitemap fetch hard caps so a 100 MB sitemap does not blow up the probe.
_SITEMAP_MAX_BYTES = 2_000_000  # 2 MB per sitemap fetched
_SITEMAP_MAX_FETCH = 3  # at most 3 sitemap URLs touched in Stage 1

# Cap on raw HTML body captured for Stage 2. 5 MB is generous for
# real-world pages; runaway responses get truncated.
_BODY_MAX_BYTES = 5_000_000


def probe_http(
    url: str,
    *,
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
    max_redirects: int = 5,
    user_agent: str = DEFAULT_USER_AGENT,
    contact_email: Optional[str] = None,
    polite_delay: Optional[float] = None,
) -> dict[str, Any]:
    """Run Stage 1 against ``url`` and return a structured findings dict.

    Args:
        url: The URL to probe.
        client: Optional pre-configured ``httpx.Client``. Injected for
            testability; if ``None`` a transient client is created and
            disposed inside the call.
        timeout: Per-request timeout in seconds.
        max_redirects: Maximum redirect hops to follow.
        user_agent: User-Agent header value. Hosts with a published
            declared-UA convention (SEC) get the contact email appended
            unless a custom ``user_agent`` was supplied (issue #13).
        contact_email: Operator contact for declared-UA conventions.
            Falls back to the ``CARTOGRAPH_CONTACT_EMAIL`` env var.
        polite_delay: Seconds between requests to the same host. ``None``
            means automatic: 1 req/sec on ``.gov`` hosts and on any host
            that returns 429/503 during the probe; no pacing elsewhere.

    Returns:
        A dict with keys ``url``, ``final_url``, ``status``,
        ``redirect_chain``, ``headers``, ``http_version``, ``robots_txt``,
        ``sitemaps``, and ``error``. The ``error`` field is ``None`` on
        success and carries a short string when the probe could not
        reach the target at all.
    """
    effective_ua = user_agent_for(
        url, user_agent=user_agent, contact_email=contact_email
    )
    request_headers = {"User-Agent": effective_ua, **DEFAULT_ACCEPT_HEADERS}
    pacer = _HostPacer(polite_delay)

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
            follow_redirects=True,
            max_redirects=max_redirects,
            headers=request_headers,
        )

    findings: dict[str, Any] = {
        "url": url,
        "final_url": None,
        "status": None,
        "redirect_chain": [],
        "headers": {},
        "http_version": None,
        "body": None,
        "body_size_bytes": 0,
        "body_truncated": False,
        "robots_txt": {"present": False},
        "sitemaps": [],
        "waf_block": None,
        "error": None,
    }

    try:
        try:
            pacer.wait(url)
            response = client.get(url, headers=request_headers)
        except httpx.HTTPError as exc:
            findings["error"] = f"{type(exc).__name__}: {exc}"
            return findings
        pacer.note_response(url, response.status_code)

        findings["final_url"] = str(response.url)
        findings["status"] = response.status_code
        findings["http_version"] = response.http_version
        raw = response.content or b""
        findings["body_size_bytes"] = len(raw)
        if len(raw) > _BODY_MAX_BYTES:
            findings["body"] = raw[:_BODY_MAX_BYTES].decode("utf-8", errors="ignore")
            findings["body_truncated"] = True
        else:
            findings["body"] = raw.decode("utf-8", errors="ignore")
        findings["redirect_chain"] = [
            {"url": str(h.url), "status": h.status_code, "to": h.headers.get("location")}
            for h in response.history
        ]
        findings["headers"] = _collect_interesting_headers(response.headers)

        # Issue #12: identify CDN/WAF edge blocks from evidence already
        # in hand. On a positive identification, stop probing: the
        # origin never saw the request, robots/sitemap fetches would
        # just hammer the same edge box that blocked us (politeness),
        # and the orchestrator short-circuits to a probe_blocked result.
        findings["waf_block"] = detect_waf_block(
            response.status_code, response.headers, findings["body"] or ""
        )
        if findings["waf_block"]:
            log.info(
                "cartograph Stage 1 edge block identified for %s: %s",
                url,
                findings["waf_block"]["vendor"],
            )
            return findings

        base = _origin(str(response.url))
        findings["robots_txt"] = _fetch_robots(
            client, base, headers=request_headers, pacer=pacer
        )

        sitemap_candidates = list(findings["robots_txt"].get("sitemap_urls") or [])
        if not sitemap_candidates:
            sitemap_candidates = [
                f"{base}/sitemap.xml",
                f"{base}/sitemap_index.xml",
            ]

        findings["sitemaps"] = _fetch_sitemaps(
            client, sitemap_candidates, headers=request_headers, pacer=pacer
        )

    finally:
        if owns_client:
            client.close()

    return findings


# --- helpers -------------------------------------------------------------


def _origin(url: str) -> str:
    """Return ``scheme://host`` portion of a URL."""
    parsed = httpx.URL(url)
    return f"{parsed.scheme}://{parsed.host}" + (f":{parsed.port}" if parsed.port else "")


def _collect_interesting_headers(headers: httpx.Headers) -> dict[str, str]:
    """Subset header dict to high-signal entries, lowercased keys."""
    out: dict[str, str] = {}
    for name in _INTERESTING_HEADERS:
        if name in headers:
            out[name] = headers[name]
    return out


def _fetch_robots(
    client: httpx.Client,
    origin: str,
    *,
    headers: Optional[dict[str, str]] = None,
    pacer: Optional[_HostPacer] = None,
) -> dict[str, Any]:
    """Fetch /robots.txt and parse out Sitemap directives + a few counts.

    Returns a structured dict regardless of fetch outcome so the Stage 4
    payload has a stable shape.
    """
    record: dict[str, Any] = {
        "present": False,
        "status": None,
        "size_bytes": 0,
        "sitemap_urls": [],
        "user_agent_blocks": 0,
        "disallow_count": 0,
    }
    robots_url = f"{origin}/robots.txt"
    try:
        if pacer is not None:
            pacer.wait(robots_url)
        r = client.get(robots_url, headers=headers)
    except httpx.HTTPError as exc:
        record["fetch_error"] = f"{type(exc).__name__}: {exc}"
        return record

    if pacer is not None:
        pacer.note_response(robots_url, r.status_code)
    record["status"] = r.status_code
    if r.status_code != 200 or not r.text.strip():
        return record

    body = r.text
    record["present"] = True
    record["size_bytes"] = len(body)
    record["sitemap_urls"] = _SITEMAP_DECL_RE.findall(body)
    record["user_agent_blocks"] = sum(
        1 for line in body.splitlines() if line.strip().lower().startswith("user-agent:")
    )
    record["disallow_count"] = sum(
        1 for line in body.splitlines() if line.strip().lower().startswith("disallow:")
    )
    return record


def _fetch_sitemaps(
    client: httpx.Client,
    urls: list[str],
    *,
    headers: Optional[dict[str, str]] = None,
    pacer: Optional[_HostPacer] = None,
) -> list[dict[str, Any]]:
    """Fetch up to ``_SITEMAP_MAX_FETCH`` sitemaps and summarize each.

    For nested sitemap indexes we record the child sitemap URLs but do
    not recurse; the Stage 4 prompt only needs to know roughly how many
    URLs the site exposes and where to find them.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for raw in urls:
        if len(out) >= _SITEMAP_MAX_FETCH:
            break
        if raw in seen:
            continue
        seen.add(raw)

        record: dict[str, Any] = {"url": raw, "status": None, "url_count": 0, "child_sitemap_count": 0}
        try:
            if pacer is not None:
                pacer.wait(raw)
            r = client.get(raw, headers=headers)
        except httpx.HTTPError as exc:
            record["fetch_error"] = f"{type(exc).__name__}: {exc}"
            out.append(record)
            continue

        if pacer is not None:
            pacer.note_response(raw, r.status_code)
        record["status"] = r.status_code
        if r.status_code != 200:
            out.append(record)
            continue

        body = r.content[:_SITEMAP_MAX_BYTES].decode("utf-8", errors="ignore")
        record["size_bytes"] = len(r.content)
        record["truncated"] = len(r.content) > _SITEMAP_MAX_BYTES

        # Count <loc> occurrences. A sitemap index also uses <loc> but
        # nests <sitemap> wrappers; we distinguish via the <sitemapindex>
        # root element marker.
        loc_count = len(_LOC_RE.findall(body))
        if "<sitemapindex" in body.lower():
            record["child_sitemap_count"] = loc_count
        else:
            record["url_count"] = loc_count

        out.append(record)

    return out
