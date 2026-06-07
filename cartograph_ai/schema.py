"""Pydantic models for cartograph-ai's output schema.

Two layers:

* ``ClaudeResponse`` mirrors the JSON shape Claude is asked to produce in
  the published prompt (``docs/how-it-works.md``). The Stage 4 module
  parses the model response into this type so any malformed payload
  surfaces as a Pydantic validation error.
* ``ProbeResult`` is the full structure handed back to the caller of
  ``probe()`` and ``cartograph-ai``. It wraps the Claude response with
  probe metadata (URL, timestamp, model, endpoints discovered, stage
  tracking) and matches the example shown in ``docs/how-it-works.md``.

Both schemas are versioned. Breaking changes ship with a major version
bump and a CHANGELOG entry per the pinning policy documented in
``docs/how-it-works.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Enums (Literal types so the validator catches typos at parse time) -------

ClassificationCategory = Literal[
    "direct_api",
    "embedded_data",
    "static_html",
    "form_gated_bulk",
    "js_rendered_spa",
    "unknown",
]
"""The six classification buckets from the published prompt."""

RecommendedTool = Literal[
    "requests",
    "httpx",
    "playwright",
    "firecrawl",
    "manual",
]
"""The five tools the prompt allows Claude to recommend."""

ProbeStage = Literal[
    "http",
    "html_analysis",
    "js_execution",
    "claude_classify",
]
"""Pipeline stages. ``js_execution`` only runs when the browser extra is installed."""


# Sub-models ----------------------------------------------------------------

class EndpointDescriptor(BaseModel):
    """A data-source endpoint discovered during the probe.

    Endpoints surfaced here must appear verbatim somewhere in the
    stage 1-3 findings. Anything else is treated as hallucinated and
    stripped by the validation layer.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    type: str = Field(
        description="Short label like 'algolia_search_api' or 'wordpress_rest'."
    )
    pagination: Optional[str] = None
    auth: Optional[str] = None


class ExtractionStrategy(BaseModel):
    """How to extract data from the probed site."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(
        description=(
            "Short method label, e.g., 'algolia_search', 'wp_rest_api', "
            "'html_parsing', 'form_post_bulk', 'browser_render'."
        )
    )
    requires_browser: bool
    estimated_requests: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Expected number of requests for the recommended strategy. "
            "None means unknown/indeterminate (e.g., the target blocked "
            "the probe and no honest estimate exists)."
        ),
    )
    recommended_tool: RecommendedTool
    specifics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("estimated_requests", mode="before")
    @classmethod
    def _negative_means_unknown(cls, value: Any) -> Any:
        """Coerce negative sentinels (e.g., -1) to None.

        Claude sometimes signals "unknown/indeterminate" with -1 when a
        target blocks the probe (issue #3). Honest-limits philosophy:
        accept the signal, normalise it to None rather than rejecting
        the whole response.
        """
        if isinstance(value, int) and not isinstance(value, bool) and value < 0:
            return None
        return value


class Classification(BaseModel):
    """The probe's verdict, confidence, and rationale.

    Built by the orchestrator from Claude's response; ``category`` mirrors
    Claude's flat ``classification`` field and ``subcategory`` is set from
    ``extraction_strategy.method`` for the public output.
    """

    model_config = ConfigDict(extra="forbid")

    category: ClassificationCategory
    subcategory: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1)


# Stage 4 response ----------------------------------------------------------

class ClaudeResponse(BaseModel):
    """What Claude returns in Stage 4.

    Matches the JSON schema embedded in the published prompt
    (see ``cartograph_ai/prompt.py``). Validation rules enforced here
    are the same constraints the prompt asks the model to honor; if the
    response fails this check, the orchestrator raises a
    ``ClassificationError`` rather than passing bad data downstream.
    """

    model_config = ConfigDict(extra="forbid")

    classification: ClassificationCategory
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1)
    extraction_strategy: ExtractionStrategy
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _limitations_required_for_low_confidence(self) -> "ClaudeResponse":
        """The prompt requires limitations to be populated when confidence < 0.7."""
        if self.confidence < 0.7 and not self.limitations:
            raise ValueError(
                "limitations must be populated when confidence is below 0.7; "
                "the published prompt requires it"
            )
        return self


# Public output -------------------------------------------------------------

class ProbeResult(BaseModel):
    """The structure returned by ``probe()`` and emitted by ``cartograph-ai --json``.

    Matches the example shown in ``docs/how-it-works.md`` verbatim. The
    schema is stable across patch releases; breaking changes ship with
    a major version bump.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    probe_timestamp: datetime
    model: str = Field(
        description="The Claude model used for Stage 4, e.g. 'claude-sonnet-4-6'."
    )
    classification: Classification
    endpoints_discovered: list[EndpointDescriptor] = Field(default_factory=list)
    extraction_strategy: ExtractionStrategy
    probe_stages_completed: list[ProbeStage]
    probe_stages_skipped: list[ProbeStage] = Field(default_factory=list)
    skip_reason: Optional[str] = None
    limitations: list[str] = Field(default_factory=list)
    low_confidence_warning: bool = False
