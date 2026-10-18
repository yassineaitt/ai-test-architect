# Prompt design and guardrails

This document explains *why* the prompts and the model call look the way they do. The
implementation lives in `src/ai_test_architect/llm/` and `src/ai_test_architect/redaction.py`.

## One call shape for every command

```
local inputs ──► redact() ──► truncate() ──► user prompt (sections)
                                                   │
system prompt (constant) ──────────────────────────┼──► messages.create(
                                                   │       output_config.format = JSON Schema,
                                                   │       output_config.effort = "low")
                                                   ▼
                              stop_reason check ──► pydantic validate ──► typed object
```

Each command (`generate`, `triage`, `heal`) differs only in how it collects inputs and what
schema it expects back. Everything between is shared and tested once.

## Guardrail 1 - no secrets in prompts

* Every piece of user-supplied content passes through `redact()` before it is placed in a
  prompt. It scrubs Anthropic/OpenAI-style keys, GitHub tokens, AWS access keys, JWTs,
  `Bearer`/`Basic` credentials and generic `key=value` / `Key: value` pairs for names such as
  `password`, `token`, `secret`, `authorization`, `cookie`.
* Keys are kept, values are replaced with `[REDACTED]`, so the model still sees the structure
  (`Authorization: Bearer [REDACTED]`) and can reason about auth failures.
* The CLI reports how many values were scrubbed on stderr. `--dry-run` prints the exact,
  already-redacted prompt and exits without calling the API.
* The API key itself is never read by this code. The SDK resolves it from the environment;
  nothing logs headers or request bodies.

## Guardrail 2 - bounded inputs

`build_user_prompt()` gives every section an equal share of `max_input_chars` (default
60 000) and truncates with a visible marker, keeping the **tail** for logs/failures (where
the useful part is) and the **head** for specs and DOM summaries (where structure is).
Before that, inputs are already reduced at the source:

| Command    | Reduction                                                                    |
| ---------- | ---------------------------------------------------------------------------- |
| `generate` | The spec is flattened to a per-operation digest with sorted, minified JSON   |
| `triage`   | Only failed/errored test cases are sent; logs are tailed (`--tail`, default 400 lines) |
| `heal`     | The DOM is reduced to interactive/landmark elements and locator attributes; scripts, styles and SVG are dropped |

## Guardrail 3 - deterministic, schema-validated output

* The request carries `output_config.format` with a JSON Schema derived from the Pydantic
  model (via the SDK's public `anthropic.transform_schema`). The API constrains generation to
  that schema.
* The response is validated **again** on the client with the same Pydantic model. A mismatch
  raises `LLMOutputError` with field paths instead of silently producing a partial object.
* Schemas are intentionally plain: strings, numbers, booleans, enums (`Literal`), lists and
  nested objects, `extra="forbid"`. Range rules (confidence in `[0, 1]`) are enforced by
  validators, not schema keywords, so the schema stays within the API's supported subset.
* `effort` defaults to `low`. On Claude Sonnet 5.5 (the default model) sampling parameters
  such as `temperature` are not configurable, so repeatability comes from low effort plus the
  schema, not from a temperature of 0. `--effort medium|high` is available for harder inputs.

## Guardrail 4 - stop reasons before content

`stop_reason` is inspected before any content is parsed:

| `stop_reason` | Behaviour                                                                  |
| ------------- | -------------------------------------------------------------------------- |
| `refusal`     | `LLMRefusedError` with the category from `stop_details`; CLI exit code 2   |
| `max_tokens`  | `LLMTruncatedError`; CLI tells you to raise `--max-tokens` or narrow input |
| `end_turn`    | Parse and validate                                                         |
| anything else | `LLMOutputError`                                                           |

## Guardrail 5 - generated code is checked before it is written

`generate` compiles every returned file with `ast.parse`. Files with syntax errors are
reported and nothing is written (exit code 3). Paths are validated by the schema (`.py`, no
absolute paths, no `..`) and resolved under `--out` before writing.

## System prompt conventions

* Constants in `llm/prompts.py`; no f-strings, no timestamps, no machine-specific values, so
  the prefix is identical across runs (cache-friendly and diffable).
* Each prompt states the role, the rules as a short list, and what to do when evidence is
  insufficient ("say so and lower confidence", "return an empty candidate list").
* The prompts ask for *calibrated* confidence and *quoted* evidence; the schemas make both
  mandatory fields so the model cannot omit them.

## Model selection

`claude-sonnet-5-5` by default (`--model`, `AI_TEST_ARCHITECT_MODEL`). The code only uses
features common to current models (`output_config.format`, `output_config.effort`), so any
model that supports structured outputs works.
