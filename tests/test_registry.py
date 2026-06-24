"""Tests for the known-source registry (issue #21): data integrity,
lookup semantics, and orchestrator integration."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest
import respx

from cartograph_ai import ProbeOptions, probe
from cartograph_ai.registry import (
    find_domains_in_text,
    load_registry,
    lookup_host,
    lookup_url,
    registry_version,
)
from cartograph_ai.schema import RecommendedBackdoor


# ---------------- Stubs (same shape as test_probe.py) ---------------------


@dataclass
class StubUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StubTextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class StubMessage:
    content: list
    model: str = "claude-sonnet-4-6"
    usage: StubUsage = None

    def __post_init__(self):
        if self.usage is None:
            self.usage = StubUsage(input_tokens=1500, output_tokens=300)


class StubMessagesEndpoint:
    def __init__(self, response: StubMessage):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class StubAnthropic:
    def __init__(self, response: StubMessage):
        self.messages = StubMessagesEndpoint(response)


def _claude_json(
    *,
    classification: str = "static_html",
    confidence: float = 0.8,
    method: str = "html_parsing",
    specifics: dict | None = None,
    limitations: list | None = None,
) -> str:
    return json.dumps(
        {
            "classification": classification,
            "confidence": confidence,
            "reasoning": "Test fixture reasoning.",
            "extraction_strategy": {
                "method": method,
                "requires_browser": False,
                "estimated_requests": 3,
                "recommended_tool": "httpx",
                "specifics": specifics or {},
            },
            "limitations": limitations or [],
        }
    )


PLAIN_HTML = "<html><head><title>t</title></head><body><p>Visible content here.</p></body></html>"


def _mock_site(root: str, *, body: str = PLAIN_HTML) -> None:
    respx.get(root).mock(return_value=httpx.Response(200, content=body, headers={"server": "nginx"}))
    origin = root.rstrip("/")
    respx.get(f"{origin}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(f"{origin}/sitemap.xml").mock(return_value=httpx.Response(404))
    respx.get(f"{origin}/sitemap_index.xml").mock(return_value=httpx.Response(404))


# ---------------- Registry data integrity ---------------------------------


def test_registry_loads_and_carries_version():
    reg = load_registry()
    assert reg["registry_version"]
    assert registry_version() == reg["registry_version"]
    assert len(reg["sources"]) >= 8


def test_every_entry_validates_into_the_output_model():
    """Each registry entry must round-trip into RecommendedBackdoor."""
    for domain in load_registry()["sources"]:
        entry = lookup_host(domain)
        bd = RecommendedBackdoor(
            matched_domain=entry["matched_domain"],
            source_name=entry["name"],
            status=entry["status"],
            endpoints=entry.get("endpoints", []),
            requires=dict(entry.get("requires", {})),
            notes=entry.get("notes"),
            registry_version=registry_version(),
        )
        if bd.status == "available":
            assert bd.endpoints, f"{domain}: available entry must list endpoints"
            for ep in bd.endpoints:
                assert ep.url.startswith("https://"), f"{domain}: non-https endpoint"
        else:
            assert not bd.endpoints, f"{domain}: none_known entry must not list endpoints"
            assert bd.notes, f"{domain}: none_known entry must explain itself"


def test_all_nine_blocked_bench_sources_resolve():
    """Issue #21 acceptance: every blocked bench source gets a verdict."""
    blocked_bench_hosts = [
        "www.nhtsa.gov",            # NHTSA x3 in the bench
        "www.sec.gov",
        "efts.sec.gov",
        "www.regulations.gov",
        "www.fmcsa.dot.gov",
        "filingaccess.serff.com",   # SERFF-PA
        "www.tesla.com",            # tesla-vsr
        "www.courtlistener.com",
    ]
    for host in blocked_bench_hosts:
        entry = lookup_host(host)
        assert entry is not None, f"{host}: no registry verdict"
    # 7 of 9 publish a sanctioned path; SERFF and Tesla honestly do not.
    assert lookup_host("filingaccess.serff.com")["status"] == "none_known"
    assert lookup_host("www.tesla.com")["status"] == "none_known"
    assert lookup_host("www.nhtsa.gov")["status"] == "available"


# ---------------- Lookup semantics -----------------------------------------


def test_lookup_matches_subdomains_not_lookalikes():
    assert lookup_host("static.nhtsa.gov")["matched_domain"] == "nhtsa.gov"
    assert lookup_host("nhtsa.gov")["matched_domain"] == "nhtsa.gov"
    assert lookup_host("notnhtsa.gov") is None
    assert lookup_host("nhtsa.gov.evil.com") is None
    assert lookup_host("") is None


def test_lookup_url_extracts_host():
    assert lookup_url("https://www.regulations.gov/docket/x")["matched_domain"] == "regulations.gov"
    assert lookup_url("https://example.com/") is None
    assert lookup_url("not a url") is None


def test_find_domains_in_text():
    text = "The documented path is api.regulations.gov/v4 (free key); also see api.congress.gov."
    found = find_domains_in_text(text)
    assert "regulations.gov" in found
    assert "congress.gov" in found
    assert find_domains_in_text("") == []
    assert find_domains_in_text("nothing relevant here") == []


# ---------------- Orchestrator integration --------------------------------


@respx.mock
def test_blocked_known_source_recommends_backdoor_as_primary_action():
    """Issue #21 part 3: probe_blocked + registry hit = routed, not stuck."""
    respx.get("https://www.nhtsa.gov/").mock(
        return_value=httpx.Response(
            403, content="Access Denied", headers={"server": "AkamaiGHost"}
        )
    )
    client = StubAnthropic(StubMessage(content=[StubTextBlock(text="{}")]))
    http_client = httpx.Client(follow_redirects=True, timeout=5.0)
    try:
        result = probe(
            "https://www.nhtsa.gov/",
            anthropic_client=client,
            http_client=http_client,
            options=ProbeOptions(preflight_key_check=False, polite_delay=0.0),
        )
    finally:
        http_client.close()

    assert result.classification.category == "probe_blocked"
    bd = result.recommended_backdoor
    assert bd is not None and bd.status == "available"
    assert bd.matched_domain == "nhtsa.gov"
    assert any("api.nhtsa.gov" in ep.url for ep in bd.endpoints)
    assert result.extraction_strategy.method == "registry_backdoor"
    assert result.extraction_strategy.specifics["primary_action"] == "use_recommended_backdoor"
    assert any("sanctioned automated path" in lim for lim in result.limitations)


@respx.mock
def test_blocked_registry_endpoint_surfaces_unmet_requirement_not_self_loop():
    """Issue #22: when the probed host IS a sanctioned registry endpoint and
    it blocks, do not recommend the backdoor (it points back at the blocked
    host). Surface the unmet access requirement instead."""
    respx.get("https://data.sec.gov/").mock(
        return_value=httpx.Response(
            403, content="Access Denied", headers={"server": "AkamaiGHost"}
        )
    )
    client = StubAnthropic(StubMessage(content=[StubTextBlock(text="{}")]))
    http_client = httpx.Client(follow_redirects=True, timeout=5.0)
    try:
        result = probe(
            "https://data.sec.gov/",
            anthropic_client=client,
            http_client=http_client,
            options=ProbeOptions(preflight_key_check=False, polite_delay=0.0),
        )
    finally:
        http_client.close()

    assert result.classification.category == "probe_blocked"
    spec = result.extraction_strategy.specifics
    assert spec["primary_action"] == "satisfy_unmet_requirement"
    assert spec["primary_action"] != "use_recommended_backdoor"
    assert result.extraction_strategy.method == "satisfy_requirement"
    # the unmet requirement (declared-UA convention) is surfaced
    assert "unmet_requirements" in spec
    assert "ua_format" in spec["unmet_requirements"]
    # the backdoor object still ships (status available), it just is not the
    # primary action on a self-loop
    assert result.recommended_backdoor is not None
    assert result.recommended_backdoor.status == "available"
    assert any(
        "registry-sanctioned endpoint" in lim for lim in result.limitations
    )


@respx.mock
def test_blocked_source_with_no_backdoor_gets_honest_none_known_verdict():
    respx.get("https://filingaccess.serff.com/").mock(
        return_value=httpx.Response(403, content="", headers={"server": "awselb/2.0"})
    )
    client = StubAnthropic(StubMessage(content=[StubTextBlock(text="{}")]))
    http_client = httpx.Client(follow_redirects=True, timeout=5.0)
    try:
        result = probe(
            "https://filingaccess.serff.com/",
            anthropic_client=client,
            http_client=http_client,
            options=ProbeOptions(preflight_key_check=False, polite_delay=0.0),
        )
    finally:
        http_client.close()

    bd = result.recommended_backdoor
    assert bd is not None and bd.status == "none_known"
    assert result.extraction_strategy.method == "manual"
    assert result.extraction_strategy.specifics["primary_action"] == "manual_or_browser"


@respx.mock
def test_successful_probe_of_known_source_still_emits_backdoor():
    """Issue #21 part 2: the recommendation fires even when Stage 1 succeeds."""
    _mock_site("https://www.sec.gov/")
    client = StubAnthropic(
        StubMessage(content=[StubTextBlock(text=_claude_json())])
    )
    http_client = httpx.Client(follow_redirects=True, timeout=5.0)
    try:
        result = probe(
            "https://www.sec.gov/",
            anthropic_client=client,
            http_client=http_client,
            options=ProbeOptions(preflight_key_check=False, polite_delay=0.0),
        )
    finally:
        http_client.close()

    bd = result.recommended_backdoor
    assert bd is not None
    assert bd.status == "available"
    assert bd.promoted_from == "registry_host_match"
    assert any("data.sec.gov" in ep.url for ep in bd.endpoints)
    # The normal pipeline still ran.
    assert result.classification.category == "static_html"


@respx.mock
def test_registry_entry_is_fed_to_the_model_as_probe_evidence():
    """Issue #21 part 5: the model is told about the registry."""
    _mock_site("https://www.sec.gov/")
    client = StubAnthropic(
        StubMessage(content=[StubTextBlock(text=_claude_json())])
    )
    http_client = httpx.Client(follow_redirects=True, timeout=5.0)
    try:
        probe(
            "https://www.sec.gov/",
            anthropic_client=client,
            http_client=http_client,
            options=ProbeOptions(preflight_key_check=False, polite_delay=0.0),
        )
    finally:
        http_client.close()

    assert len(client.messages.calls) == 1
    prompt_text = client.messages.calls[0]["messages"][0]["content"]
    assert "known_source_registry" in prompt_text
    assert "data.sec.gov" in prompt_text


@respx.mock
def test_registry_endpoints_survive_validation_when_model_uses_them():
    """The Run 01 over-stripping, fixed at the root: because the registry
    entry is probe evidence, registry endpoints in the model's strategy
    pass the verbatim cross-reference instead of being quarantined."""
    _mock_site("https://www.sec.gov/")
    client = StubAnthropic(
        StubMessage(
            content=[
                StubTextBlock(
                    text=_claude_json(
                        classification="direct_api",
                        method="structured_api",
                        specifics={"endpoint": "https://data.sec.gov/"},
                    )
                )
            ]
        )
    )
    http_client = httpx.Client(follow_redirects=True, timeout=5.0)
    try:
        result = probe(
            "https://www.sec.gov/",
            anthropic_client=client,
            http_client=http_client,
            options=ProbeOptions(preflight_key_check=False, polite_delay=0.0),
        )
    finally:
        http_client.close()

    assert result.extraction_strategy.specifics["endpoint"] == "https://data.sec.gov/"
    assert result.hallucinations_stripped == []
    assert result.unverified_candidates == []


@respx.mock
def test_limitations_naming_a_known_source_promote_the_registry_entry():
    """Issue #21 part 4: limitations prose pointing at a known source is
    promoted to a first-class recommendation."""
    _mock_site("https://www.someagencysite.com/")
    client = StubAnthropic(
        StubMessage(
            content=[
                StubTextBlock(
                    text=_claude_json(
                        classification="unknown",
                        confidence=0.4,
                        method="manual",
                        limitations=[
                            "Data appears to mirror federal dockets; "
                            "api.regulations.gov likely carries the "
                            "authoritative copy but was not probed."
                        ],
                    )
                )
            ]
        )
    )
    http_client = httpx.Client(follow_redirects=True, timeout=5.0)
    try:
        result = probe(
            "https://www.someagencysite.com/",
            anthropic_client=client,
            http_client=http_client,
            options=ProbeOptions(preflight_key_check=False, polite_delay=0.0),
        )
    finally:
        http_client.close()

    bd = result.recommended_backdoor
    assert bd is not None
    assert bd.matched_domain == "regulations.gov"
    assert bd.promoted_from == "limitations_cross_reference"


@respx.mock
def test_unknown_host_emits_no_backdoor():
    _mock_site("https://example.com/")
    client = StubAnthropic(
        StubMessage(content=[StubTextBlock(text=_claude_json())])
    )
    http_client = httpx.Client(follow_redirects=True, timeout=5.0)
    try:
        result = probe(
            "https://example.com/",
            anthropic_client=client,
            http_client=http_client,
            options=ProbeOptions(preflight_key_check=False, polite_delay=0.0),
        )
    finally:
        http_client.close()

    assert result.recommended_backdoor is None
