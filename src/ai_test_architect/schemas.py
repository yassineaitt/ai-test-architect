"""Output contracts. Every model response is parsed into one of these before use.

Schemas stay deliberately simple (strings, numbers, booleans, enums, lists, nested
objects) so they translate cleanly to the JSON Schema the API enforces server-side.
Range checks live in validators, not schema constraints.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- generate -----------------------------------------------------------------


class GeneratedTestFile(_Strict):
    path: str = Field(description="Relative path such as tests/test_pets.py or tests/conftest.py")
    content: str = Field(description="Complete file content, valid Python 3.12")

    @field_validator("path")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        if value.startswith(("/", "~")) or ".." in value.split("/"):
            msg = f"unsafe path from model: {value!r}"
            raise ValueError(msg)
        if not value.endswith(".py"):
            msg = f"expected a .py path, got {value!r}"
            raise ValueError(msg)
        return value


class GeneratedTestSuite(_Strict):
    files: list[GeneratedTestFile]
    covered_operations: list[str] = Field(description="operationId or 'METHOD /path' per test")
    assumptions: list[str] = Field(description="Anything the generator had to guess")


# ---- triage -------------------------------------------------------------------

TriageCategory = Literal["product-bug", "test-bug", "environment", "flaky", "test-data", "unknown"]


class SuggestedFix(_Strict):
    target: str = Field(description="File, config or component the fix applies to")
    description: str
    patch: str = Field(description="Unified diff or code snippet; empty if not applicable")


class TriageReport(_Strict):
    summary: str = Field(description="One sentence a release manager can read")
    root_cause: str
    category: TriageCategory
    confidence: float = Field(description="0.0 to 1.0")
    evidence: list[str] = Field(
        description="Quotes from the failure or logs that support the cause"
    )
    suggested_fix: SuggestedFix | None = None
    next_steps: list[str]

    @field_validator("confidence")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        return min(1.0, max(0.0, value))


# ---- heal ---------------------------------------------------------------------

LocatorStrategy = Literal["test-id", "role", "label", "placeholder", "text", "css", "xpath"]


class LocatorCandidate(_Strict):
    playwright: str = Field(
        description="Playwright locator expression, e.g. page.getByRole('button', { name: 'Save' })"
    )
    strategy: LocatorStrategy
    confidence: float = Field(description="0.0 to 1.0")
    rationale: str

    @field_validator("confidence")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        return min(1.0, max(0.0, value))


class LocatorSuggestions(_Strict):
    broken_selector: str
    likely_cause: str
    candidates: list[LocatorCandidate]
    recommended: str = Field(description="The single best candidate's playwright expression")
    notes: list[str]
