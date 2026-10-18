"""Command-line interface.

Three commands share one shape: gather local inputs → redact + bound them → one structured
model call → validate → write/print. ``--dry-run`` stops before the model call and prints the
exact prompt, so the tool is inspectable (and demoable) without an API key.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, NoReturn

import anthropic
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_test_architect import __version__
from ai_test_architect.config import Effort, Settings
from ai_test_architect.generate.openapi import SpecError, digest, load_spec
from ai_test_architect.generate.writer import WriteError, syntax_errors, write_suite
from ai_test_architect.heal.dom import selector_mentions, summarize_dom
from ai_test_architect.llm import AnthropicStructuredLLM, LLMError, StructuredLLM
from ai_test_architect.llm.prompts import (
    GENERATE_SYSTEM,
    HEAL_SYSTEM,
    TRIAGE_SYSTEM,
    build_user_prompt,
)
from ai_test_architect.redaction import Redaction
from ai_test_architect.schemas import GeneratedTestSuite, LocatorSuggestions, TriageReport
from ai_test_architect.triage.inputs import TriageInputError, load_failures, load_logs
from ai_test_architect.triage.report import to_markdown

app = typer.Typer(
    name="ai-test-architect",
    help="Claude-powered helpers for test engineers: generate, triage, heal.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()
err_console = Console(stderr=True)

# Tests inject a fake through this seam; production leaves it None.
_llm_override: StructuredLLM | None = None

ModelOpt = Annotated[
    str | None, typer.Option("--model", "-m", help="Model id (env AI_TEST_ARCHITECT_MODEL).")
]
EffortOpt = Annotated[
    Effort | None,
    typer.Option("--effort", help="low | medium | high (env AI_TEST_ARCHITECT_EFFORT)."),
]
MaxTokensOpt = Annotated[
    int | None, typer.Option("--max-tokens", min=1024, help="Response budget.")
]
DryRunOpt = Annotated[
    bool,
    typer.Option("--dry-run", help="Print the redacted prompt and exit without calling the API."),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Print the validated result as JSON.")]


def _version(value: bool) -> None:
    if value:
        console.print(f"ai-test-architect {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    """Claude-powered helpers for test engineers."""


def _llm(settings: Settings) -> StructuredLLM:
    return _llm_override or AnthropicStructuredLLM(settings)


def _settings(model: str | None, effort: Effort | None, max_tokens: int | None) -> Settings:
    try:
        return Settings.from_env(model=model, effort=effort, max_tokens=max_tokens)
    except ValueError as exc:
        _fail(f"invalid settings: {exc}")


def _fail(message: str, code: int = 1) -> NoReturn:
    err_console.print(f"[bold red]error:[/] {message}")
    raise typer.Exit(code)


def _report_redaction(red: Redaction) -> None:
    if red.replacements:
        err_console.print(
            f"[yellow]redacted {red.replacements} credential-like value(s) "
            f"({', '.join(red.kinds)}) before sending[/]"
        )


def _dry_run(system: str, user: str, settings: Settings) -> None:
    console.print(
        Panel(system.rstrip(), title=f"system · model={settings.model} effort={settings.effort}")
    )
    console.print(Panel(user, title="user (redacted, bounded)"))
    raise typer.Exit(0)


def _call[T: GeneratedTestSuite | TriageReport | LocatorSuggestions](
    settings: Settings, system: str, user: str, schema: type[T]
) -> T:
    try:
        result = _llm(settings).complete(system=system, user=user, schema=schema)
    except LLMError as exc:
        _fail(str(exc), code=2)
    except anthropic.AuthenticationError:
        _fail("authentication failed: set ANTHROPIC_API_KEY (or run `ant auth login`).", code=2)
    except anthropic.RateLimitError:
        _fail("rate limited by the API; retry shortly.", code=2)
    except anthropic.APIStatusError as exc:
        _fail(f"API error {exc.status_code}: {exc.message}", code=2)
    except anthropic.APIConnectionError:
        _fail("could not reach the Anthropic API (network).", code=2)
    usage = result.usage
    err_console.print(
        f"[dim]{result.model} · {usage.input_tokens} in / {usage.output_tokens} out tokens[/]"
    )
    return result.parsed


# ---- generate -----------------------------------------------------------------


@app.command()
def generate(
    spec: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="OpenAPI 3 spec (YAML/JSON).")
    ],
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Directory to write the suite into.")
    ] = Path("generated-tests"),
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Only operations with this tag (repeatable).")
    ] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Replace existing files.")] = False,
    model: ModelOpt = None,
    effort: EffortOpt = None,
    max_tokens: MaxTokensOpt = None,
    dry_run: DryRunOpt = False,
    as_json: JsonOpt = False,
) -> None:
    """Generate pytest API tests from an OpenAPI 3 specification."""
    settings = _settings(model, effort, max_tokens)
    try:
        d = digest(load_spec(spec), tags=set(tag) if tag else None)
    except SpecError as exc:
        _fail(str(exc))
    if not d.operations:
        _fail("no operations matched (check --tag).")
    user, red = build_user_prompt(
        {"OpenAPI digest": d.to_prompt_text()},
        max_input_chars=settings.max_input_chars,
        keep="head",
    )
    _report_redaction(red)
    if dry_run:
        _dry_run(GENERATE_SYSTEM, user, settings)

    suite = _call(settings, GENERATE_SYSTEM, user, GeneratedTestSuite)
    if problems := syntax_errors(suite.files):
        for path, problem in problems.items():
            err_console.print(f"[red]generated file does not parse:[/] {path}: {problem}")
        _fail("refusing to write files with syntax errors; re-run or raise --effort.", code=3)
    if as_json:
        sys.stdout.write(suite.model_dump_json(indent=2) + "\n")
        return
    try:
        written = write_suite(suite, out, overwrite=overwrite)
    except WriteError as exc:
        _fail(str(exc))
    table = Table(title=f"Generated {len(written)} file(s) in {out}")
    table.add_column("file")
    for p in written:
        table.add_row(str(p.relative_to(out.resolve())))
    console.print(table)
    console.print(f"[green]covered:[/] {', '.join(suite.covered_operations) or '(none listed)'}")
    for a in suite.assumptions:
        console.print(f"[yellow]assumption:[/] {a}")


# ---- triage -------------------------------------------------------------------


@app.command()
def triage(
    junit: Annotated[
        list[Path], typer.Argument(exists=True, dir_okay=False, help="JUnit XML file(s).")
    ],
    log: Annotated[
        list[Path] | None,
        typer.Option(
            "--log", "-l", exists=True, dir_okay=False, help="Log file(s) to include (tail)."
        ),
    ] = None,
    tail: Annotated[
        int, typer.Option("--tail", min=20, help="Lines kept from the end of each log.")
    ] = 400,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the Markdown report here.")
    ] = None,
    model: ModelOpt = None,
    effort: EffortOpt = None,
    max_tokens: MaxTokensOpt = None,
    dry_run: DryRunOpt = False,
    as_json: JsonOpt = False,
) -> None:
    """Explain a failed run: root cause, category, confidence and a proposed fix."""
    settings = _settings(model, effort, max_tokens)
    try:
        failures, total = load_failures(junit)
        logs = load_logs(log or [], tail_lines=tail)
    except TriageInputError as exc:
        _fail(str(exc))
    if not failures:
        console.print(f"[green]No failures in {total} test(s); nothing to triage.[/]")
        return
    sections = {
        "Run summary": f"{len(failures)} failed of {total} tests",
        "Failures (JUnit)": "\n\n".join(f.to_prompt_text() for f in failures),
    }
    if logs:
        sections["Logs (tail)"] = logs
    user, red = build_user_prompt(sections, max_input_chars=settings.max_input_chars)
    _report_redaction(red)
    if dry_run:
        _dry_run(TRIAGE_SYSTEM, user, settings)

    report = _call(settings, TRIAGE_SYSTEM, user, TriageReport)
    if as_json:
        sys.stdout.write(report.model_dump_json(indent=2) + "\n")
        return
    md = to_markdown(report)
    if out:
        out.write_text(md, encoding="utf-8")
        console.print(f"[green]wrote[/] {out}")
    else:
        sys.stdout.write(md)


# ---- heal ---------------------------------------------------------------------


@app.command()
def heal(
    selector: Annotated[
        str, typer.Argument(help="The Playwright selector that no longer matches.")
    ],
    dom: Annotated[
        Path,
        typer.Option(
            "--dom", exists=True, dir_okay=False, help="HTML snapshot of the current page."
        ),
    ],
    context: Annotated[
        Path | None,
        typer.Option(
            "--context", exists=True, dir_okay=False, help="Failing test/step/error text."
        ),
    ] = None,
    max_elements: Annotated[
        int, typer.Option("--max-elements", min=20, help="DOM elements kept in the prompt.")
    ] = 400,
    model: ModelOpt = None,
    effort: EffortOpt = None,
    max_tokens: MaxTokensOpt = None,
    dry_run: DryRunOpt = False,
    as_json: JsonOpt = False,
) -> None:
    """Suggest self-healing Playwright locators for a broken selector."""
    settings = _settings(model, effort, max_tokens)
    html = dom.read_text(encoding="utf-8", errors="replace")
    surviving = selector_mentions(html, selector)
    sections = {
        "Broken selector": selector,
        "Selector tokens still present in the DOM": ", ".join(surviving) or "(none)",
        "Current DOM (locator-relevant elements)": summarize_dom(html, max_elements=max_elements),
    }
    if context:
        sections["Failing test context"] = context.read_text(encoding="utf-8", errors="replace")
    user, red = build_user_prompt(sections, max_input_chars=settings.max_input_chars, keep="head")
    _report_redaction(red)
    if dry_run:
        _dry_run(HEAL_SYSTEM, user, settings)

    suggestions = _call(settings, HEAL_SYSTEM, user, LocatorSuggestions)
    if as_json:
        sys.stdout.write(suggestions.model_dump_json(indent=2) + "\n")
        return
    console.print(f"[bold]Likely cause:[/] {suggestions.likely_cause}")
    table = Table(title=f"Candidates for {selector}")
    table.add_column("confidence", justify="right")
    table.add_column("strategy")
    table.add_column("locator")
    table.add_column("why")
    for c in sorted(suggestions.candidates, key=lambda c: -c.confidence):
        table.add_row(f"{c.confidence:.0%}", c.strategy, c.playwright, c.rationale)
    console.print(table)
    if suggestions.recommended:
        console.print(Panel(suggestions.recommended, title="recommended", border_style="green"))
    for n in suggestions.notes:
        console.print(f"[dim]note:[/] {n}")
    if not suggestions.candidates:
        raise typer.Exit(4)


def main() -> None:  # pragma: no cover - console entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
