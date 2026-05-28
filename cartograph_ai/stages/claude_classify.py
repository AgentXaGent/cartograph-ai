"""Stage 4: Claude classification.

Sends the assembled probe payload to Claude using the pinned prompt and
parses the response into a ``ClaudeResponse`` model.  The Anthropic
client is injectable; unit tests pass a stub, real probes pass a real
``anthropic.Anthropic()`` instance.

The pinned model is ``claude-sonnet-4-6``.  Bumping it is a versioned
release per the pinning policy documented in ``docs/how-it-works.md``.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from pydantic import ValidationError as PydanticValidationError

from cartograph_ai.exceptions import ClassificationError
from cartograph_ai.prompt import build_prompt
from cartograph_ai.schema import ClaudeResponse

DEFAULT_MODEL = "claude-sonnet-4-6"
"""Pinned model. Bumping requires a CHANGELOG entry."""

DEFAULT_MAX_TOKENS = 2048
"""Cap on response length. The schema response is small (low hundreds of
tokens for high-confidence cases, slightly more when limitations populate),
so 2048 leaves headroom without overpaying."""

# Strip a fenced JSON block if the model wraps its response that way.
# We accept ```json ... ``` and bare ``` ... ``` fences.
_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*\n(?P<body>.*?)\n```", re.DOTALL | re.IGNORECASE
)


class _SupportsMessages(Protocol):
    """Minimal protocol the injected client must satisfy.

    The real ``anthropic.Anthropic`` instance exposes ``messages.create``;
    test stubs can implement just that without importing the SDK.
    """

    messages: Any  # noqa: ANN401


@dataclass
class ClassificationResult:
    """The Stage 4 output.

    Bundles the parsed model response with the metadata an orchestrator
    needs to build the public ``ProbeResult`` and a debug-friendly
    ``--debug`` trace.
    """

    response: ClaudeResponse
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    raw_text: str


def classify(
    *,
    probe_payload: dict[str, Any],
    client: _SupportsMessages,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ClassificationResult:
    """Send ``probe_payload`` to Claude and parse the structured response.

    Args:
        probe_payload: The structured findings dict from Stages 1-3.
            Gets JSON-serialised inside the prompt by ``build_prompt``.
        client: An Anthropic-compatible client. Must expose
            ``messages.create(model, max_tokens, messages)``.
        model: The model string. Defaults to the pinned Sonnet version.
        max_tokens: Output token cap.

    Returns:
        A ``ClassificationResult`` bundling the parsed ``ClaudeResponse``,
        the model identifier the response actually came from, token
        counts, end-to-end latency, and the raw text body for debug.

    Raises:
        ClassificationError: If the API call fails, the response is not
            valid JSON, or the JSON does not match ``ClaudeResponse``.
    """
    prompt = build_prompt(probe_payload)
    started_at = time.perf_counter()
    try:
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise ClassificationError(
            f"Anthropic API call failed: {type(exc).__name__}: {exc}"
        ) from exc
    latency = time.perf_counter() - started_at

    raw_text = _extract_text(message)
    if not raw_text.strip():
        raise ClassificationError("Model returned an empty response body.")

    payload_str = _strip_json_fences(raw_text)

    try:
        parsed_json = json.loads(payload_str)
    except json.JSONDecodeError as exc:
        raise ClassificationError(
            f"Model response was not valid JSON: {exc}. "
            f"First 200 chars: {raw_text[:200]!r}"
        ) from exc

    try:
        response = ClaudeResponse.model_validate(parsed_json)
    except PydanticValidationError as exc:
        raise ClassificationError(
            f"Model response failed schema validation: {exc}"
        ) from exc

    response_model = getattr(message, "model", model) or model
    usage = getattr(message, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)

    return ClassificationResult(
        response=response,
        model=response_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_seconds=latency,
        raw_text=raw_text,
    )


# ---------------- Helpers ---------------------------------------------


def _extract_text(message: Any) -> str:
    """Concatenate ``type == "text"`` blocks from an Anthropic response.

    The real SDK returns a list of content blocks each with a ``.type``
    discriminator.  Test stubs that return a ``str`` directly work too:
    if ``message.content`` is a string, we return it as-is.
    """
    content = getattr(message, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        # Real SDK: block.type == "text", block.text == "..."
        block_type = getattr(block, "type", None)
        if block_type == "text":
            parts.append(getattr(block, "text", "") or "")
        # Dict-shaped stub support: {"type": "text", "text": "..."}
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", "") or "")
    return "".join(parts)


def _strip_json_fences(text: str) -> str:
    """If the model wrapped its response in a fenced code block, unwrap it."""
    stripped = text.strip()
    match = _FENCED_JSON_RE.search(stripped)
    if match:
        return match.group("body").strip()
    return stripped
