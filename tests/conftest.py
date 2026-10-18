"""Shared fixtures: a fake LLM and a mocked Anthropic transport (no API key needed)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx2 as httpx
import pytest
from pydantic import BaseModel

from ai_test_architect.config import Settings
from ai_test_architect.llm.client import LLMResult, Usage


@dataclass
class FakeLLM:
    """Records prompts and returns canned objects per schema type."""

    responses: dict[type[BaseModel], BaseModel] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete[T: BaseModel](self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]:
        self.calls.append({"system": system, "user": user, "schema": schema})
        try:
            parsed = self.responses[schema]
        except KeyError as exc:  # pragma: no cover - test authoring error
            msg = f"FakeLLM has no canned response for {schema.__name__}"
            raise AssertionError(msg) from exc
        assert isinstance(parsed, schema)
        return LLMResult(parsed=parsed, usage=Usage(100, 50), model="fake-model")


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def settings() -> Settings:
    return Settings()


def messages_api_response(
    *,
    text: str | None,
    stop_reason: str = "end_turn",
    stop_details: dict[str, Any] | None = None,
    model: str = "claude-sonnet-5-5",
) -> dict[str, Any]:
    """Minimal Messages API JSON body."""
    content = [] if text is None else [{"type": "text", "text": text}]
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {"input_tokens": 42, "output_tokens": 7},
    }


@pytest.fixture
def anthropic_client_factory() -> Callable[..., tuple[anthropic.Anthropic, list[dict[str, Any]]]]:
    """Build an Anthropic client whose HTTP layer is a MockTransport returning ``body``."""

    def factory(
        body: dict[str, Any], status: int = 200
    ) -> tuple[anthropic.Anthropic, list[dict[str, Any]]]:
        seen: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(status, json=body)

        client = anthropic.Anthropic(
            api_key="test-key-not-real",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )
        return client, seen

    return factory
