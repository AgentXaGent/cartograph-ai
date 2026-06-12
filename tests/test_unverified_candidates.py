"""Acceptance tests for issue #15: validator redesign.

The three behaviors observed in Bench Run 01, each pinned:

1. ca-dmv-av (working as designed): invented WordPress routes are
   quarantined; the architecture call survives.
2. sec-edgar-fts (over-aggressive stripping, fixed): real documented
   endpoints the probe could not confirm land in unverified_candidates
   instead of being silently lost.
3. regulations-gov (genuine bug, fixed): the model's own self-hedging
   prose is never run through endpoint validation.

Plus: limitations is prose by design and is never stripped.
"""

from __future__ import annotations

from cartograph_ai.schema import ClaudeResponse, ExtractionStrategy
from cartograph_ai.validation import cross_reference_endpoints


def _response(
    specifics: dict,
    *,
    classification: str = "direct_api",
    method: str = "wp_rest_api",
    limitations: list | None = None,
    confidence: float = 0.85,
) -> ClaudeResponse:
    return ClaudeResponse(
        classification=classification,
        confidence=confidence,
        reasoning="Architecture identified from fingerprints.",
        extraction_strategy=ExtractionStrategy(
            method=method,
            requires_browser=False,
            estimated_requests=10,
            recommended_tool="httpx",
            specifics=specifics,
        ),
        limitations=limitations or [],
    )


CA_DMV_PAYLOAD = {
    "url": "https://www.dmv.ca.gov/portal/vehicle-industry-services/autonomous-vehicles/",
    "stage1": {"status": 200},
    "stage2": {
        "fingerprints": [
            {"id": "wordpress", "category": "cms", "evidence": "wp-content paths"}
        ],
        "api_endpoints": [],
    },
}


def test_ca_dmv_case_candidates_quarantined_architecture_kept():
    """Run 01 case 1: three invented /wp-json/ URLs, correct wp_rest_api call."""
    invented = [
        "/wp-json/wp/v2/pages",
        "/wp-json/wp/v2/posts?search=autonomous",
        "/wp-json/wp/v2/media",
    ]
    r = _response(
        {
            "rest_routes": invented,
            "cms": "wordpress",
        }
    )
    report = cross_reference_endpoints(r, probe_payload=CA_DMV_PAYLOAD)

    # All three quarantined with provenance...
    assert sorted(report.stripped_endpoints) == sorted(invented)
    assert {src for _, src in report.unverified} == {
        "extraction_strategy.specifics.rest_routes[0]",
        "extraction_strategy.specifics.rest_routes[1]",
        "extraction_strategy.specifics.rest_routes[2]",
    }
    # ...and the architecture call is untouched.
    assert report.response.extraction_strategy.method == "wp_rest_api"
    assert report.response.extraction_strategy.specifics["cms"] == "wordpress"
    assert report.response.classification == "direct_api"


SEC_PAYLOAD = {
    "url": "https://efts.sec.gov/LATEST/search-index?q=test",
    "stage1": {"status": 403, "headers": {"server": "AkamaiGHost"}},
    "stage2": {"fingerprints": [], "api_endpoints": []},
}


def test_sec_edgar_case_real_endpoints_preserved_not_lost():
    """Run 01 case 2: efts.sec.gov / data.sec.gov are real and documented.

    The probe couldn't confirm them (Akamai blocked the edge), so they
    cannot ship as machine-actionable strategy — but losing them hid
    the correct answer from the operator. They must survive in
    unverified_candidates.
    """
    r = _response(
        {
            "full_text_search": "https://efts.sec.gov/LATEST/search-index",
            "structured_data": "https://data.sec.gov/",
        },
        method="search_api",
        limitations=["Edge returned 403; endpoints inferred from SEC documentation."],
        confidence=0.5,
    )
    report = cross_reference_endpoints(r, probe_payload=SEC_PAYLOAD)

    values = [v for v, _ in report.unverified]
    assert "https://data.sec.gov/" in values
    # The efts URL appears verbatim in the payload URL itself, so it
    # survives verification — exactly the right outcome.
    assert "https://efts.sec.gov/LATEST/search-index" not in values
    assert (
        report.response.extraction_strategy.specifics["full_text_search"]
        == "https://efts.sec.gov/LATEST/search-index"
    )
    # Nothing silently lost: everything stripped is accounted for.
    assert set(report.stripped_endpoints) == set(values)


def test_regulations_gov_case_self_hedging_prose_is_not_an_endpoint():
    """Run 01 case 3: prose run through endpoint validation was a bug.

    A sentence that happens to start with a scheme or slash is not a
    machine-actionable endpoint. Whitespace is the discriminator.
    """
    hedge = (
        "https://api.regulations.gov/v4/ was NOT discovered in the probe "
        "and should not be treated as confirmed"
    )
    slash_prose = "/v4 API requires a free key per the public docs"
    r = _response(
        {
            "candidate_api": hedge,
            "note": slash_prose,
        },
        method="manual",
        limitations=["CloudFront 403 at edge."],
        confidence=0.4,
    )
    report = cross_reference_endpoints(
        r, probe_payload={"url": "https://www.regulations.gov/", "stage1": {}, "stage2": {}}
    )

    assert report.stripped_endpoints == []
    assert report.unverified == []
    assert report.response.extraction_strategy.specifics["candidate_api"] == hedge
    assert report.response.extraction_strategy.specifics["note"] == slash_prose


def test_limitations_are_never_stripped():
    """limitations is prose by design; the validator must not touch it."""
    lims = [
        "https://api.regulations.gov/v4/ exists per documentation but was not probed.",
        "Consider the bulk download at https://static.nhtsa.gov/ instead.",
    ]
    r = _response({"app": "x"}, limitations=lims, confidence=0.5)
    report = cross_reference_endpoints(
        r, probe_payload={"url": "https://example.com/", "stage1": {}, "stage2": {}}
    )
    assert report.response.limitations == lims
    assert report.stripped_endpoints == []


def test_oversized_url_like_value_is_left_alone():
    """Anything past the URL length cap is not treated as an endpoint."""
    monster = "/" + "a" * 3000
    r = _response({"weird": monster})
    report = cross_reference_endpoints(
        r, probe_payload={"url": "https://example.com/", "stage1": {}, "stage2": {}}
    )
    assert report.stripped_endpoints == []
    assert report.response.extraction_strategy.specifics["weird"] == monster
