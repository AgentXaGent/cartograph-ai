"""The cartograph probe orchestrator.

Public entry point for the library. Wires the four stages together,
applies validation, and assembles the final ``ProbeResult``.

Stages 1 (HTTP), 2 (HTML analysis), and 4 (Claude classification) always
run in Phase 1. Stage 3 (JS execution) is skipped and reported in
``probe_stages_skipped``; users opt in by installing the ``browser``
extra (Phase 2).
"""

from __future__ import annotations

import datetime as _dt
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from cartograph_ai.exceptions import (
    AuthWalledError,
    CartographError,
    HTMLAnalysisError,
    LowConfidenceError,
    PreflightKeyError,
)
from cartograph_ai.schema import (
    Classification,
    EndpointDescriptor,
    ExtractionStrategy,
    ProbeResult,
)
from cartograph_ai.stages.claude_classify import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    ClassificationResult,
    classify,
)
from cartograph_ai.stages.html_analysis import analyze_html
from cartograph_ai.stages.http_probe import DEFAULT_USER_AGENT, probe_http
from cartograph_ai.validation import cross_reference_endpoints

log = logging.getLogger("cartograph_ai")

LOW_CONFIDENCE_THRESHOLD = 0.7
"""Confidence below this triggers the low-confidence warning in default
mode and a hard refusal in ``--strict`` mode. Defined here so callers can
override on a per-probe basis if their workflow needs a different bar."""


@dataclass
class ProbeOptions:
    """Configuration for a single probe call.

    Attributes:
        strict: If True, raise ``LowConfidenceError`` when the model's
            confidence falls below ``LOW_CONFIDENCE_THRESHOLD``. Default
            behaviour returns the result with ``low_confidence_warning``
            set instead.
        debug: If True, log the assembled Stage 4 payload at DEBUG level
            so ``--debug`` can route it to stderr.
        model: The Claude model to use at Stage 4.
        max_tokens: Output token cap for the Stage 4 call.
        timeout: Per-request timeout (seconds) for Stage 1 fetches.
        user_agent: User-Agent header for Stage 1 fetches.
        retry_on_stage1_failure: If True, Stage 1 transient errors get
            one retry with a half-second backoff before the orchestrator
            raises.
        preflight_key_check: If True (default), validate the Anthropic
            API key before any HTTP request is sent to the probe target
            (issue #18). A bad key fails fast with PreflightKeyError and
            never touches the target host.
    """

    strict: bool = False
    debug: bool = False
    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout: float = 10.0
    user_agent: str = DEFAULT_USER_AGENT
    retry_on_stage1_failure: bool = True
    preflight_key_check: bool = True


def probe(
    url: str,
    *,
    anthropic_client: Any = None,
    http_client: Optional[httpx.Client] = None,
    options: Optional[ProbeOptions] = None,
) -> ProbeResult:
    """Run the full probe pipeline against ``url``.

    Args:
        url: The URL to probe.
        anthropic_client: An Anthropic-compatible client. If ``None``, a
            default ``anthropic.Anthropic()`` is constructed (which picks
            up ``ANTHROPIC_API_KEY`` from the environment).
        http_client: An optional pre-configured ``httpx.Client`` to share
            across stages. If ``None``, a transient client is used.
        options: A ``ProbeOptions`` instance. Defaults if omitted.

    Returns:
        A ``ProbeResult`` matching the schema in
        ``docs/how-it-works.md``. If Stage 1 cannot reach the target
        across retries, this is a structured ``probe_unreachable``
        result (issue #8) rather than an exception.

    Raises:
        AuthWalledError: Target requires authentication (401).
        HTMLAnalysisError: Stage 2 had no HTML to walk.
        ClassificationError: Stage 4 failed to parse the model response.
        LowConfidenceError: ``strict`` was True and confidence dropped
            below threshold.
    """
    opts = options or ProbeOptions()
    if anthropic_client is None:
        anthropic_client = _default_anthropic_client()

    # ---- Preflight: validate the key before touching the target ------
    if opts.preflight_key_check:
        _preflight_key_check(anthropic_client, model=opts.model)

    stages_completed: list[str] = []
    stages_skipped: list[str] = ["js_execution"]
    skip_reason = "Phase 1 does not run Stage 3 (install [browser] extra to enable)"
    extra_limitations: list[str] = []

    # ---- Stage 1: HTTP probe -----------------------------------------
    stage1 = _run_stage1(url, http_client=http_client, opts=opts)

    if stage1["error"]:
        # Issue #8: network-layer failures are information, not errors.
        # Return a structured probe_unreachable result so callers can
        # route to retry queues or manual review without parsing
        # exception text.
        log.warning(
            "cartograph Stage 1 unreachable for %s: %s", url, stage1["error"]
        )
        return _unreachable_result(url, error=stage1["error"], opts=opts)
    stages_completed.append("http")

    status = stage1["status"]
    if status == 401:
        raise AuthWalledError(
            f"Target {url} requires authentication (HTTP 401). "
            "Phase 3 may add authenticated-probe support."
        )

    body = stage1.get("body") or ""
    if not body:
        raise HTMLAnalysisError(
            f"Target {url} returned no HTML body (status {status}); "
            "cannot run Stage 2 analysis."
        )

    # ---- Stage 2: HTML analysis --------------------------------------
    stage2 = analyze_html(body, stage1.get("final_url") or url)
    stages_completed.append("html_analysis")

    # ---- Stage 4: Claude classification ------------------------------
    probe_payload = {
        "url": url,
        "stage1": _stage1_for_payload(stage1),
        "stage2": stage2,
    }
    if opts.debug:
        log.debug("cartograph probe payload assembled for %s", url)

    classify_result = classify(
        probe_payload=probe_payload,
        client=anthropic_client,
        model=opts.model,
        max_tokens=opts.max_tokens,
    )
    stages_completed.append("claude_classify")

    # ---- Validation: strip hallucinated endpoints --------------------
    report = cross_reference_endpoints(
        classify_result.response, probe_payload=probe_payload
    )
    if report.stripped_endpoints:
        log.warning(
            "cartograph stripped %d hallucinated endpoint(s) from response: %s",
            len(report.stripped_endpoints),
            report.stripped_endpoints,
        )
        extra_limitations.append(
            "cartograph stripped "
            f"{len(report.stripped_endpoints)} endpoint(s) the model "
            "recommended that did not appear in the probe input."
        )

    cleaned_response = report.response

    # ---- Confidence handling -----------------------------------------
    low_confidence = cleaned_response.confidence < LOW_CONFIDENCE_THRESHOLD
    if low_confidence and opts.strict:
        raise LowConfidenceError(
            f"Confidence {cleaned_response.confidence:.2f} is below threshold "
            f"{LOW_CONFIDENCE_THRESHOLD} and strict mode was requested. "
            f"Limitations: {cleaned_response.limitations or 'none reported'}"
        )

    # ---- Assemble public output --------------------------------------
    return ProbeResult(
        url=url,
        probe_timestamp=_dt.datetime.now(_dt.timezone.utc),
        model=classify_result.model,
        classification=Classification(
            category=cleaned_response.classification,
            subcategory=cleaned_response.extraction_strategy.method or None,
            confidence=cleaned_response.confidence,
            reasoning=cleaned_response.reasoning,
        ),
        endpoints_discovered=_build_endpoints_discovered(stage2),
        extraction_strategy=cleaned_response.extraction_strategy,
        probe_stages_completed=stages_completed,
        probe_stages_skipped=stages_skipped,
        skip_reason=skip_reason,
        limitations=list(cleaned_response.limitations) + extra_limitations,
        hallucinations_stripped=list(report.stripped_endpoints),
        low_confidence_warning=low_confidence,
    )


# ---------------- Helpers ---------------------------------------------


def _preflight_key_check(client: Any, *, model: str) -> None:
    """Validate the Anthropic key before any probe traffic (issue #18).

    Two layers, cheapest first:

    1. Shape check on ``client.api_key`` when the attribute exists:
       an obviously malformed key (wrong prefix, too short) fails
       without any network traffic at all.
    2. A single throwaway ``messages.create`` call with ``max_tokens=1``
       (~50ms, ~$0.00001). A 401 surfaces here, against Anthropic,
       instead of after Stages 1-2 have already hit the target host.

    Raises:
        PreflightKeyError: The key is missing, malformed, or rejected.
    """
    api_key = getattr(client, "api_key", None)
    if isinstance(api_key, str):
        if not api_key.startswith("sk-ant-") or len(api_key) < 20:
            raise PreflightKeyError(
                "Anthropic API key failed the shape check (expected an "
                "'sk-ant-' prefix). No probe traffic was sent. Check "
                "ANTHROPIC_API_KEY."
            )

    try:
        client.messages.create(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except Exception as exc:
        raise PreflightKeyError(
            "Anthropic API key failed preflight validation; no probe "
            f"traffic was sent. Underlying error: {type(exc).__name__}: {exc}"
        ) from exc


def _unreachable_result(url: str, *, error: str, opts: ProbeOptions) -> ProbeResult:
    """Build the synthetic ``probe_unreachable`` result for Stage 1 failures.

    No Claude call is made; confidence is 0.0 by construction and the
    error string is preserved in ``classification.reasoning`` and
    ``limitations``. Subcategory taxonomy per issue #8:
    ``stage_1_timeout`` | ``stage_1_refused`` | ``stage_1_dns_failure``,
    with ``stage_1_error`` as the fallback for other network failures.
    """
    return ProbeResult(
        url=url,
        probe_timestamp=_dt.datetime.now(_dt.timezone.utc),
        model="none (stage 4 not reached)",
        classification=Classification(
            category="probe_unreachable",
            subcategory=_unreachable_subcategory(error),
            confidence=0.0,
            reasoning=f"Stage 1 HTTP probe failed: {error}",
        ),
        endpoints_discovered=[],
        extraction_strategy=ExtractionStrategy(
            method="manual",
            requires_browser=None,
            estimated_requests=None,
            recommended_tool=None,
            specifics={
                "reason": "network unreachable",
                "retry_after_sec": 60,
            },
        ),
        probe_stages_completed=[],
        probe_stages_skipped=["html_analysis", "js_execution", "claude_classify"],
        skip_reason="Stage 1 HTTP probe failed; downstream stages skipped.",
        limitations=[
            f"Stage 1 HTTP probe failed: {error}. No content-layer "
            "evidence exists for this URL; the classification is a "
            "network-layer report, not a content judgment."
        ],
        low_confidence_warning=False,
    )


def _unreachable_subcategory(error: str) -> str:
    """Map an httpx error string to the issue #8 subcategory taxonomy."""
    lowered = error.lower()
    if "timeout" in lowered:
        return "stage_1_timeout"
    if (
        "getaddrinfo" in lowered
        or "name or service not known" in lowered
        or "name resolution" in lowered
        or "nodename" in lowered
        or "no address associated" in lowered
    ):
        return "stage_1_dns_failure"
    if "refused" in lowered or "connecterror" in lowered:
        return "stage_1_refused"
    return "stage_1_error"


def _default_anthropic_client() -> Any:
    """Lazy import of the anthropic SDK so the library imports cleanly
    even when the SDK is not installed (e.g., during ``pip install -e .``
    without the API key configured)."""
    try:
        from anthropic import Anthropic  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - import guard
        raise CartographError(
            "The anthropic package is required to run the probe. "
            "Install with 'pip install cartograph-ai' or pass a custom client."
        ) from exc
    try:
        return Anthropic()
    except Exception as exc:
        # The SDK raises at construction when the key is missing. Wrap it
        # so the failure is typed and clearly pre-traffic (issue #18).
        raise PreflightKeyError(
            "Could not construct the Anthropic client (is "
            "ANTHROPIC_API_KEY set?). No probe traffic was sent. "
            f"Underlying error: {type(exc).__name__}: {exc}"
        ) from exc


def _run_stage1(
    url: str,
    *,
    http_client: Optional[httpx.Client],
    opts: ProbeOptions,
) -> dict[str, Any]:
    """Run probe_http with an optional single retry on transient error."""
    stage1 = probe_http(
        url,
        client=http_client,
        timeout=opts.timeout,
        user_agent=opts.user_agent,
    )
    if stage1["error"] and opts.retry_on_stage1_failure:
        log.info("cartograph Stage 1 transient error; retrying once: %s", stage1["error"])
        time.sleep(0.5)
        stage1 = probe_http(
            url,
            client=http_client,
            timeout=opts.timeout,
            user_agent=opts.user_agent,
        )
    return stage1


def _stage1_for_payload(stage1: dict[str, Any]) -> dict[str, Any]:
    """Drop the raw HTML body before serialising Stage 1 into the prompt.

    Stage 2's structured findings already represent the body. Sending
    the raw HTML on top would multiply token cost without adding signal.
    """
    summary = dict(stage1)
    summary.pop("body", None)
    return summary


def _build_endpoints_discovered(stage2: dict[str, Any]) -> list[EndpointDescriptor]:
    """Convert Stage 2 ``api_endpoints`` entries into EndpointDescriptors."""
    out: list[EndpointDescriptor] = []
    seen: set[str] = set()
    for endpoint in stage2.get("api_endpoints", []):
        url = endpoint.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(
            EndpointDescriptor(
                url=url,
                type=endpoint.get("type", "unknown"),
            )
        )
    return out
