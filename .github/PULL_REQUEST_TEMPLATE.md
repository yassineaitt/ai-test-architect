## What

## Why

## How to verify

- [ ] `uv run ruff check . && uv run mypy`
- [ ] `uv run pytest --cov` (coverage stays ≥ 85 %)
- [ ] `uv run ai-test-architect <command> ... --dry-run` still shows redacted prompts

## Checklist

- [ ] No network calls in tests (the Anthropic client is mocked at the transport)
- [ ] Prompt changes documented in `docs/prompt-design.md`
- [ ] Output schema changes keep the "simple JSON Schema" rule (no range constraints)
