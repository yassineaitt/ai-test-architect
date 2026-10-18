from ai_test_architect.llm.prompts import (
    GENERATE_SYSTEM,
    HEAL_SYSTEM,
    TRIAGE_SYSTEM,
    build_user_prompt,
)


def test_build_user_prompt_redacts_and_reports() -> None:
    prompt, red = build_user_prompt(
        {"Logs": "Authorization: Bearer abcdefghijkl\nGET /x 500", "Spec": "openapi: 3.0.0"},
        max_input_chars=10_000,
    )
    assert "## Logs" in prompt
    assert "## Spec" in prompt
    assert "abcdefghijkl" not in prompt
    assert red.replacements == 1
    assert red.kinds == ("bearer",)


def test_build_user_prompt_bounds_each_section() -> None:
    prompt, _ = build_user_prompt({"A": "x" * 5_000, "B": "y" * 5_000}, max_input_chars=2_000)
    assert prompt.count("truncated") == 2


def test_system_prompts_have_no_volatile_content() -> None:
    for text in (GENERATE_SYSTEM, TRIAGE_SYSTEM, HEAL_SYSTEM):
        assert "{" not in text  # no f-string holes
        assert "2026" not in text  # no dates
