import json

import pytest
from pydantic import BaseModel

from ai_test_architect.config import Settings
from ai_test_architect.llm import (
    AnthropicStructuredLLM,
    LLMOutputError,
    LLMRefusedError,
    LLMTruncatedError,
)
from tests.conftest import messages_api_response


class Answer(BaseModel):
    value: int
    label: str


def test_parses_structured_output_and_sends_effort(anthropic_client_factory) -> None:
    client, seen = anthropic_client_factory(
        messages_api_response(text=json.dumps({"value": 7, "label": "seven"}))
    )
    llm = AnthropicStructuredLLM(Settings(effort="low", max_tokens=2048), client=client)

    result = llm.complete(system="sys", user="usr", schema=Answer)

    assert result.parsed == Answer(value=7, label="seven")
    assert result.usage.input_tokens == 42
    body = seen[0]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 2048
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in body
    assert body["system"] == "sys"
    assert body["messages"] == [{"role": "user", "content": "usr"}]


def test_refusal_becomes_typed_error(anthropic_client_factory) -> None:
    client, _ = anthropic_client_factory(
        messages_api_response(
            text=None,
            stop_reason="refusal",
            stop_details={"type": "refusal", "category": "general_harms", "explanation": "nope"},
        )
    )
    llm = AnthropicStructuredLLM(Settings(), client=client)
    with pytest.raises(LLMRefusedError) as exc:
        llm.complete(system="s", user="u", schema=Answer)
    assert exc.value.category == "general_harms"


def test_truncation_becomes_typed_error(anthropic_client_factory) -> None:
    client, _ = anthropic_client_factory(
        messages_api_response(text='{"value": 1, "lab', stop_reason="max_tokens")
    )
    llm = AnthropicStructuredLLM(Settings(max_tokens=1024), client=client)
    with pytest.raises(LLMTruncatedError, match="max_tokens=1024"):
        llm.complete(system="s", user="u", schema=Answer)


def test_missing_output_becomes_typed_error(anthropic_client_factory) -> None:
    client, _ = anthropic_client_factory(messages_api_response(text=None))
    llm = AnthropicStructuredLLM(Settings(), client=client)
    with pytest.raises(LLMOutputError, match="no text block"):
        llm.complete(system="s", user="u", schema=Answer)


def test_schema_mismatch_becomes_typed_error(anthropic_client_factory) -> None:
    client, _ = anthropic_client_factory(
        messages_api_response(text=json.dumps({"value": "not-an-int", "label": "x"}))
    )
    llm = AnthropicStructuredLLM(Settings(), client=client)
    with pytest.raises(LLMOutputError, match="did not match Answer"):
        llm.complete(system="s", user="u", schema=Answer)


def test_schema_sent_to_api_forbids_extra_properties(anthropic_client_factory) -> None:
    client, seen = anthropic_client_factory(
        messages_api_response(text=json.dumps({"value": 1, "label": "one"}))
    )
    AnthropicStructuredLLM(Settings(), client=client).complete(system="s", user="u", schema=Answer)
    schema = seen[0]["output_config"]["format"]["schema"]
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"value", "label"}
    assert schema["additionalProperties"] is False
