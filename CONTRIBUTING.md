# Contributing

## Setup

```bash
uv sync                                       # Python 3.12 venv + dev deps
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
cp .env.example .env                          # only needed to call the real API
```

## Local gate

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest --cov                            # fails under 85 % coverage
```

The test suite never touches the network: `tests/conftest.py` provides a `FakeLLM` for
command tests and an Anthropic client wired to an `httpx2.MockTransport` for client tests.
Keep it that way; a test that needs a key is a test that will not run in CI.

## Commit messages

Conventional Commits, checked by the `commit-msg` hook: `feat`, `fix`, `test`, `ci`, `build`,
`docs`, `chore`, `refactor`, `perf`.

## Where things go

| Change                                   | File(s)                                   | Rule                                                        |
| ---------------------------------------- | ----------------------------------------- | ----------------------------------------------------------- |
| New model-facing behaviour               | `llm/prompts.py`                          | System prompts are constants; no dates, no env values       |
| New output shape                         | `schemas.py`                              | Simple types only; validators for ranges; `extra="forbid"`  |
| Input handling (files, parsing, bounding)| `generate/`, `triage/`, `heal/`           | Pure functions, unit-tested without the model              |
| Anything that touches credentials        | `redaction.py`                            | Add a pattern **and** a test with a realistic sample        |
| New command or flag                      | `cli.py`                                  | Must support `--dry-run` and `--json`                       |

## Review checklist

- Prompt text changed? Update `docs/prompt-design.md` and the prompt tests.
- Schema changed? Confirm `anthropic.transform_schema` still accepts it (unit test does).
- Never log or print the API key, request headers, or raw model input.
