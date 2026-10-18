"""Runtime settings. Everything is overridable by flag or environment, nothing is secret."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_MODEL = "claude-sonnet-5-5"
ENV_PREFIX = "AI_TEST_ARCHITECT_"

Effort = Literal["low", "medium", "high"]


class Settings(BaseModel):
    """Model and budget knobs shared by every command.

    ``effort`` is the determinism lever on Claude Sonnet 5.5: sampling parameters are not
    configurable on that model, so repeatability comes from low effort plus schema-validated
    output rather than from ``temperature``.
    """

    model: str = Field(default=DEFAULT_MODEL, min_length=1)
    effort: Effort = "low"
    max_tokens: int = Field(default=16_000, ge=1_024, le=128_000)
    max_input_chars: int = Field(default=60_000, ge=1_000)

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None = None,
        effort: Effort | None = None,
        max_tokens: int | None = None,
        environ: dict[str, str] | None = None,
    ) -> Settings:
        """Build settings from explicit overrides first, then ``AI_TEST_ARCHITECT_*`` variables."""
        env = os.environ if environ is None else environ
        values: dict[str, object] = {}
        if m := model or env.get(f"{ENV_PREFIX}MODEL"):
            values["model"] = m
        if e := effort or env.get(f"{ENV_PREFIX}EFFORT"):
            values["effort"] = e
        if t := max_tokens or env.get(f"{ENV_PREFIX}MAX_TOKENS"):
            values["max_tokens"] = int(t)
        if c := env.get(f"{ENV_PREFIX}MAX_INPUT_CHARS"):
            values["max_input_chars"] = int(c)
        return cls.model_validate(values)
