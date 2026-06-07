"""Typed exceptions for cartograph-ai.

Every error raised by the library is a subclass of ``CartographError`` so
callers can ``except CartographError`` to handle anything the probe can
throw without catching unrelated exceptions.

The named failure classes mirror the five categories documented in
``docs/how-it-works.md``: auth-walled, anti-bot, novel pattern,
hallucinated endpoint, probe-time site instability. Each maps to a
specific exception type below.
"""

from __future__ import annotations


class CartographError(Exception):
    """Base class for every cartograph-ai exception."""


# Stage-level failures ------------------------------------------------------

class HTTPProbeError(CartographError):
    """Stage 1 (HTTP probe) failed in a way the orchestrator cannot recover from.

    Since issue #8 landed, ``probe()`` no longer raises this for network
    failures; it returns a structured ``probe_unreachable`` result
    instead. The class is retained so existing ``except HTTPProbeError``
    call sites keep working and for use by lower-level callers of
    ``probe_http`` who want a typed error to raise themselves.
    """


class HTMLAnalysisError(CartographError):
    """Stage 2 (HTML analysis) could not parse the served document.

    Raised when the response was reachable but the body could not be parsed
    as HTML at all (e.g., truncated bytes, binary payload served as text).
    """


class ClassificationError(CartographError):
    """Stage 4 (Claude classification) failed.

    Wraps non-recoverable Anthropic API errors and schema-validation
    failures on the model response. The cause is preserved via
    ``raise ... from e``.
    """


# Named failure classes from docs/how-it-works.md --------------------------

class AuthWalledError(CartographError):
    """Probe target requires authentication and Phase 1 cannot proceed.

    Phase 3 may add support for authenticated probes; this exception is
    the honest stop until then.
    """


class AntiBotDetectedError(CartographError):
    """Probe target served an anti-bot challenge (Cloudflare, CAPTCHA, etc.).

    By design, cartograph reports the pattern and stops. Bypassing
    anti-bot defenses is out of scope.
    """


class ProbeTimeoutError(CartographError):
    """Probe target was unstable across retries; no clean signal was obtained."""


class PreflightKeyError(CartographError):
    """The Anthropic API key failed preflight validation (issue #18).

    Raised before any HTTP request is sent to a probe target. A
    misconfigured key must never burn request budget (or operator IP
    reputation) against the very sites being probed. The cartograph
    contract is: if Stage 1 fires, the key is good.
    """


# Output / validation failures ---------------------------------------------

class OutputValidationError(CartographError):
    """Claude's response failed Pydantic schema validation or the endpoint cross-reference.

    Raised when the model returned a payload whose shape does not match
    the documented v1 output schema, or recommended an endpoint URL that
    does not appear verbatim in the stage 1-3 findings. The orchestrator
    strips invalid endpoints and logs them; this exception fires only
    when validation failure leaves no usable result.
    """


class LowConfidenceError(CartographError):
    """Confidence below threshold and the caller requested ``--strict`` mode.

    In default mode, low-confidence results return with a warning field
    set. ``--strict`` callers opt into hard-refusal so an agent or pipeline
    does not act on weak signal.
    """
