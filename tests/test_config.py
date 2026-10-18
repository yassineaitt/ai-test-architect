import pytest
from pydantic import ValidationError

from ai_test_architect.config import DEFAULT_MODEL, Settings


def test_defaults() -> None:
    s = Settings.from_env(environ={})
    assert s.model == DEFAULT_MODEL
    assert s.effort == "low"
    assert s.max_tokens == 16_000


def test_env_overrides() -> None:
    s = Settings.from_env(
        environ={
            "AI_TEST_ARCHITECT_MODEL": "claude-opus-5-5",
            "AI_TEST_ARCHITECT_EFFORT": "medium",
            "AI_TEST_ARCHITECT_MAX_TOKENS": "4096",
        }
    )
    assert (s.model, s.effort, s.max_tokens) == ("claude-opus-5-5", "medium", 4096)


def test_explicit_flags_beat_env() -> None:
    s = Settings.from_env(model="flag-model", environ={"AI_TEST_ARCHITECT_MODEL": "env-model"})
    assert s.model == "flag-model"


def test_invalid_effort_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.from_env(environ={"AI_TEST_ARCHITECT_EFFORT": "max"})
