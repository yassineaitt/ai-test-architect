"""Thin, typed wrapper over the Anthropic SDK's structured-output call.

Design rules (see docs/prompt-design.md):

* **Schema-enforced output** - ``output_config.format`` built from the Pydantic model with
  the SDK's ``transform_schema``; the API constrains generation to the schema and the
  response is validated again client-side with the same model.
* **Low effort by default** - the determinism knob on Claude Sonnet 5.5.
* **Stop reasons are checked before content is trusted** - refusals and truncation become
  typed exceptions instead of half-parsed objects.
* **No secrets in prompts** - this layer never reads env vars; callers pass redacted text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from ai_test_architect.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Base class for model-side failures the CLI can explain to the user."""


class LLMRefusedError(LLMError):
    def __init__(self, category: str | None, explanation: str | None) -> None:
        self.category = category
        self.explanation = explanation
        super().__init__(
            f"The model declined this request (category={category or 'unknown'})."
            + (f" {explanation}" if explanation else "")
        )


class LLMTruncatedError(LLMError):
    def __init__(self, max_tokens: int) -> None:
        super().__init__(
            f"The response hit max_tokens={max_tokens} before the JSON was complete. "
            "Raise --max-tokens or narrow the input."
        )


class LLMOutputError(LLMError):
    """The response finished but no schema-valid object came back."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    parsed: T
    usage: Usage
    model: str


class StructuredLLM(Protocol):
    """What the commands depend on. Tests substitute a fake; production uses Anthropic."""

    def complete(self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]: ...


class AnthropicStructuredLLM:
    """Production implementation backed by ``anthropic.Anthropic``."""

    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None) -> None:
        self._settings = settings
        # Credentials resolve from the environment inside the SDK (ANTHROPIC_API_KEY or an
        # `ant auth login` profile). They are never read, logged or passed around here.
        self._client = client or anthropic.Anthropic(max_retries=2, timeout=120.0)

    def complete(self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]:
        s = self._settings
        message = self._client.messages.create(
            model=s.model,
            max_tokens=s.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": s.effort,
                "format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)},
            },
        )
        # Stop reason first: a refusal or a truncated body must never be parsed as an answer.
        if message.stop_reason == "refusal":
            details = message.stop_details
            raise LLMRefusedError(
                category=getattr(details, "category", None),
                explanation=getattr(details, "explanation", None),
            )
        if message.stop_reason == "max_tokens":
            raise LLMTruncatedError(s.max_tokens)
        text = next((b.text for b in message.content if b.type == "text"), None)
        if text is None:
            msg = f"stop_reason={message.stop_reason!r} but the response contained no text block"
            raise LLMOutputError(msg)
        try:
            parsed = schema.model_validate_json(text)
        except ValidationError as exc:
            msg = f"Response did not match {schema.__name__}: {exc.error_count()} issue(s)\n{exc}"
            raise LLMOutputError(msg) from exc
        return LLMResult(
            parsed=parsed,
            usage=Usage(message.usage.input_tokens, message.usage.output_tokens),
            model=message.model,
        )
