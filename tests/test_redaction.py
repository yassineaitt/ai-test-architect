from ai_test_architect.redaction import REDACTED, redact, truncate


def test_redacts_known_token_formats() -> None:
    text = (
        "key sk-ant-api03-abcdefghijklmnop\n"
        "Authorization: Bearer abcdef0123456789\n"
        "aws AKIAABCDEFGHIJKLMNOP\n"
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop\n"
        "gh ghp_abcdefghijklmnopqrstuvwxyz123456\n"
    )
    out = redact(text)
    assert "sk-ant" not in out.text
    assert "AKIA" not in out.text
    assert "ghp_" not in out.text
    assert "eyJ" not in out.text
    assert "Bearer [REDACTED]" in out.text
    assert out.replacements >= 5
    assert "anthropic-key" in out.kinds


def test_redacts_key_value_pairs_but_keeps_keys() -> None:
    out = redact('password=hunter22 token: "abcd1234" X-Api-Key: zzzz-1234 cookie=session=abc')
    assert out.text.startswith(f"password={REDACTED}")
    assert f'token: "{REDACTED}' in out.text
    assert f"X-Api-Key: {REDACTED}" in out.text
    assert "hunter22" not in out.text


def test_leaves_ordinary_text_alone() -> None:
    text = "GET /pets returned 200 in 12ms; token bucket refilled"
    out = redact(text)
    assert out.text == text
    assert out.replacements == 0


def test_truncate_keeps_tail_by_default_and_marks_it() -> None:
    text = "a" * 50 + "b" * 50
    out = truncate(text, 20)
    assert out.endswith("b" * 20)
    assert "truncated 80 characters" in out
    assert truncate("short", 20) == "short"


def test_truncate_can_keep_head() -> None:
    out = truncate("head" * 10 + "tail" * 10, 8, keep="head")
    assert out.startswith("headhead")
