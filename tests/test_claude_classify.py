"""Tests for ``cartograph_ai.stages.claude_classify``.

The Anthropic client is stubbed so these tests run without network
access. The real Anthropic call is exercised by the integration tests
under ``@pytest.mark.integration`` (Toni runs those locally with a
funded API key).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from cartograph_ai.exceptions import ClassificationError
from cartograph_ai.stages.claude_classify import (
    DEFAULT_MODEL,
    DEFAULT_MAX_TOKENS,
    ClassificationResult,
    _strip_json_fences,
    classify,
)


# ---------------- Stub client ----------------------------------------


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
    model: str = DEFAULT_MODEL
    usage: StubUsage = None  # populated in __post_init__

    def __post_init__(self):
        if self.usage is None:
            self.usage = StubUsage()


class StubMessagesEndpoint:
    """Records calls and returns a pre-canned response."""

    def __init__(self, response: StubMessage):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class StubAnthropic:
    def __init__(self, response: StubMessage):
        self.messages = StubMessagesEndpoint(response)


def _valid_response_json() -> str:
    return json.dumps(
        {
            "classification": "direct_api",
            "confidence": 0.94,
            "reasoning": "Algolia app ID found in inline script.",
            "extraction_strategy": {
                "method": "algolia_search",
                "requires_browser": False,
                "estimated_requests": 2,
                "recommended_tool": "requests",
                "specifics": {"app_id": "AHNZ21XTZ6", "index": "prod_projects"},
            },
            "limitations": [],
        }
    )


def _stub_client(*, body: str, input_tokens: int = 1500, output_tokens: int = 320, model: str = DEFAULT_MODEL):
    msg = StubMessage(
        content=[StubTextBlock(type="text", text=body)],
        model=model,
        usage=StubUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )
    return StubAnthropic(msg)


# ---------------- Happy path -----------------------------------------


def test_classify_parses_valid_response():
    client = _stub_client(body=_valid_response_json())
    result = classify(probe_payload={"url": "https://x.com"}, client=client)
    assert isinstance(result, ClassificationResult)
    assert result.response.classification == "direct_api"
    assert result.response.confidence == 0.94
    assert result.input_tokens == 1500
    assert result.output_tokens == 320
    assert result.model == DEFAULT_MODEL
    assert result.latency_seconds >= 0.0


def test_classify_passes_correct_model_and_tokens():
    client = _stub_client(body=_valid_response_json())
    classify(probe_payload={"x": 1}, client=client, model="claude-sonnet-4-6", max_tokens=2048)
    call = client.messages.calls[0]
    assert call["model"] == "claude-sonnet-4-6"
    assert call["max_tokens"] == 2048
    assert call["messages"][0]["role"] == "user"


def test_classify_default_model_is_pinned_sonnet():
    assert DEFAULT_MODEL == "claude-sonnet-4-6"
    assert DEFAULT_MAX_TOKENS >= 1024


def test_classify_uses_build_prompt_so_probe_payload_is_in_the_prompt():
    client = _stub_client(body=_valid_response_json())
    classify(probe_payload={"url": "https://uniquemarker.test/x"}, client=client)
    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "https://uniquemarker.test/x" in prompt
    # And the heuristics from the prompt are still there.
    assert "Apply these heuristics in order" in prompt


# ---------------- Fence stripping ------------------------------------


def test_classify_handles_json_code_fence():
    fenced = f"```json\n{_valid_response_json()}\n```"
    client = _stub_client(body=fenced)
    result = classify(probe_payload={}, client=client)
    assert result.response.classification == "direct_api"


def test_classify_handles_bare_code_fence():
    fenced = f"```\n{_valid_response_json()}\n```"
    client = _stub_client(body=fenced)
    result = classify(probe_payload={}, client=client)
    assert result.response.classification == "direct_api"


def test_strip_fences_passthrough_for_plain_json():
    plain = '{"a": 1}'
    assert _strip_json_fences(plain) == plain


def test_strip_fences_unwraps_fenced():
    fenced = "```json\n{\"a\": 1}\n```"
    assert _strip_json_fences(fenced) == '{"a": 1}'


# ---------------- Error paths ----------------------------------------


def test_classify_raises_on_empty_response():
    client = _stub_client(body="")
    with pytest.raises(ClassificationError, match="empty"):
        classify(probe_payload={}, client=client)


def test_classify_raises_on_non_json_response():
    client = _stub_client(body="Sorry, I cannot help with that.")
    with pytest.raises(ClassificationError, match="not valid JSON"):
        classify(probe_payload={}, client=client)


def test_classify_raises_on_schema_violation():
    bad = json.dumps(
        {
            "classification": "magical_api",  # not in literal set
            "confidence": 0.9,
            "reasoning": "x",
            "extraction_strategy": {
                "method": "magic",
                "requires_browser": False,
                "estimated_requests": 1,
                "recommended_tool": "requests",
            },
            "limitations": [],
        }
    )
    client = _stub_client(body=bad)
    with pytest.raises(ClassificationError, match="schema validation"):
        classify(probe_payload={}, client=client)


def test_classify_raises_on_low_confidence_without_limitations():
    """The prompt rule from schema.py is enforced at parse time."""
    bad = json.dumps(
        {
            "classification": "unknown",
            "confidence": 0.4,
            "reasoning": "Could not get a clean read.",
            "extraction_strategy": {
                "method": "manual_review",
                "requires_browser": False,
                "estimated_requests": 0,
                "recommended_tool": "manual",
            },
            "limitations": [],
        }
    )
    client = _stub_client(body=bad)
    with pytest.raises(ClassificationError, match="schema validation"):
        classify(probe_payload={}, client=client)


def test_classify_wraps_anthropic_exception():
    class ExplodingClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("503 Service Unavailable")

    with pytest.raises(ClassificationError, match="Anthropic API call failed"):
        classify(probe_payload={}, client=ExplodingClient())


def test_classify_handles_string_content_stub():
    """Some test stubs return content as a bare string; we accept that."""
    class StringContentClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                @dataclass
                class M:
                    content: str = _valid_response_json()
                    model: str = DEFAULT_MODEL
                    usage: StubUsage = None
                    def __post_init__(self):
                        if self.usage is None:
                            self.usage = StubUsage()
                return M()

    result = classify(probe_payload={}, client=StringContentClient())
    assert result.response.classification == "direct_api"


def test_classify_handles_dict_shaped_content_blocks():
    """Some stubs use {"type": "text", "text": "..."} dicts instead of objects."""
    msg = StubMessage(content=[{"type": "text", "text": _valid_response_json()}])

    class DictBlockClient:
        def __init__(self, m):
            self.messages = StubMessagesEndpoint(m)
    result = classify(probe_payload={}, client=DictBlockClient(msg))
    assert result.response.classification == "direct_api"
