import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_test_architect import cli
from ai_test_architect.llm import LLMRefusedError
from ai_test_architect.schemas import (
    GeneratedTestFile,
    GeneratedTestSuite,
    LocatorCandidate,
    LocatorSuggestions,
    SuggestedFix,
    TriageReport,
)

EX = Path(__file__).parents[1] / "examples"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _inject_fake(fake_llm, monkeypatch):
    monkeypatch.setattr(cli, "_llm_override", fake_llm)
    monkeypatch.delenv("AI_TEST_ARCHITECT_MODEL", raising=False)
    monkeypatch.delenv("AI_TEST_ARCHITECT_EFFORT", raising=False)


def test_version_and_help() -> None:
    assert "ai-test-architect 0.1.0" in runner.invoke(cli.app, ["--version"]).output
    out = runner.invoke(cli.app, ["--help"]).output
    assert "generate" in out
    assert "triage" in out
    assert "heal" in out


# ---- generate -----------------------------------------------------------------


def test_generate_dry_run_prints_prompt_without_calling_model(fake_llm) -> None:
    res = runner.invoke(cli.app, ["generate", str(EX / "openapi/petstore.yaml"), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "OpenAPI digest" in res.output
    assert "operationId=createPet" in res.output
    assert fake_llm.calls == []


def test_generate_writes_files_and_conftest(fake_llm, tmp_path: Path) -> None:
    fake_llm.responses[GeneratedTestSuite] = GeneratedTestSuite(
        files=[
            GeneratedTestFile(
                path="tests/test_pets.py", content="def test_list(api):\n    assert api\n"
            )
        ],
        covered_operations=["GET /pets"],
        assumptions=["API_TOKEN grants write access"],
    )
    res = runner.invoke(
        cli.app,
        [
            "generate",
            str(EX / "openapi/petstore.yaml"),
            "--out",
            str(tmp_path),
            "--tag",
            "pets",
            "--model",
            "m-x",
        ],
    )
    assert res.exit_code == 0, res.output
    assert (tmp_path / "tests/test_pets.py").exists()
    assert (tmp_path / "tests/conftest.py").exists()
    assert "assumption" in res.output
    call = fake_llm.calls[0]
    assert call["schema"] is GeneratedTestSuite
    assert "requestAdoption" not in call["user"]  # tag filter applied
    assert "listPets" in call["user"]


def test_generate_refuses_syntax_errors(fake_llm, tmp_path: Path) -> None:
    fake_llm.responses[GeneratedTestSuite] = GeneratedTestSuite(
        files=[GeneratedTestFile(path="tests/test_bad.py", content="def (:\n")],
        covered_operations=[],
        assumptions=[],
    )
    res = runner.invoke(
        cli.app, ["generate", str(EX / "openapi/petstore.yaml"), "--out", str(tmp_path)]
    )
    assert res.exit_code == 3
    assert not (tmp_path / "tests").exists()


def test_generate_json_output_and_bad_tag(fake_llm) -> None:
    fake_llm.responses[GeneratedTestSuite] = GeneratedTestSuite(
        files=[], covered_operations=[], assumptions=[]
    )
    res = runner.invoke(cli.app, ["generate", str(EX / "openapi/petstore.yaml"), "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout)["files"] == []
    res = runner.invoke(cli.app, ["generate", str(EX / "openapi/petstore.yaml"), "--tag", "nope"])
    assert res.exit_code == 1
    assert "no operations matched" in res.output


def test_generate_invalid_spec_and_settings(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("swagger: '2.0'\n")
    assert runner.invoke(cli.app, ["generate", str(bad)]).exit_code == 1
    res = runner.invoke(cli.app, ["generate", str(EX / "openapi/petstore.yaml"), "--effort", "max"])
    assert res.exit_code == 2  # typer rejects the enum value


# ---- triage -------------------------------------------------------------------


def test_triage_redacts_logs_and_renders_markdown(fake_llm, tmp_path: Path) -> None:
    fake_llm.responses[TriageReport] = TriageReport(
        summary="Migration skipped.",
        root_cause="adoption_requests table missing",
        category="environment",
        confidence=0.9,
        evidence=['relation "adoption_requests" does not exist'],
        suggested_fix=SuggestedFix(target="deploy", description="enable migrations", patch=""),
        next_steps=["run migrations"],
    )
    out = tmp_path / "triage.md"
    res = runner.invoke(
        cli.app,
        [
            "triage",
            str(EX / "triage/junit.xml"),
            "--log",
            str(EX / "triage/app.log"),
            "--out",
            str(out),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "redacted" in res.output  # password + bearer token in the example log
    prompt = fake_llm.calls[0]["user"]
    assert "s3cr3t-pass" not in prompt
    assert "eyJhbGci" not in prompt
    assert "2 failed of 4 tests" in prompt
    assert "## Test failure triage" in out.read_text()


def test_triage_no_failures_short_circuits(fake_llm, tmp_path: Path) -> None:
    xml = tmp_path / "ok.xml"
    xml.write_text(
        '<testsuite name="s" tests="1"><testcase classname="c" name="t" time="0.1"/></testsuite>'
    )
    res = runner.invoke(cli.app, ["triage", str(xml)])
    assert res.exit_code == 0
    assert "nothing to triage" in res.output
    assert fake_llm.calls == []


def test_triage_json_and_dry_run(fake_llm) -> None:
    fake_llm.responses[TriageReport] = TriageReport(
        summary="s", root_cause="r", category="flaky", confidence=0.3, evidence=[], next_steps=[]
    )
    res = runner.invoke(cli.app, ["triage", str(EX / "triage/junit.xml"), "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout)["category"] == "flaky"
    res = runner.invoke(cli.app, ["triage", str(EX / "triage/junit.xml"), "--dry-run"])
    assert res.exit_code == 0
    assert "Failures (JUnit)" in res.output


def test_triage_bad_input(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xml"
    bad.write_text("<nope>")
    assert runner.invoke(cli.app, ["triage", str(bad)]).exit_code == 1


# ---- heal ---------------------------------------------------------------------


def test_heal_shows_candidates(fake_llm) -> None:
    fake_llm.responses[LocatorSuggestions] = LocatorSuggestions(
        broken_selector="#submit-btn",
        likely_cause="id removed in redesign",
        candidates=[
            LocatorCandidate(
                playwright="page.getByTestId('submit-adoption')",
                strategy="test-id",
                confidence=0.95,
                rationale="unique test id",
            ),
            LocatorCandidate(
                playwright="page.getByRole('button', { name: 'Send request' })",
                strategy="role",
                confidence=0.9,
                rationale="unique accessible name",
            ),
        ],
        recommended="page.getByTestId('submit-adoption')",
        notes=["form wrapper also has a test id"],
    )
    res = runner.invoke(
        cli.app,
        [
            "heal",
            "#submit-btn",
            "--dom",
            str(EX / "heal/page.html"),
            "--context",
            str(EX / "heal/context.md"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "submit-adoption" in res.output
    prompt = fake_llm.calls[0]["user"]
    assert "Selector tokens still present in the DOM" in prompt
    assert "adoption.spec.ts" in prompt  # context forwarded
    assert "window.__x" not in prompt  # script stripped


def test_heal_exits_nonzero_when_element_is_gone(fake_llm) -> None:
    fake_llm.responses[LocatorSuggestions] = LocatorSuggestions(
        broken_selector="#gone", likely_cause="removed", candidates=[], recommended="", notes=[]
    )
    res = runner.invoke(cli.app, ["heal", "#gone", "--dom", str(EX / "heal/page.html")])
    assert res.exit_code == 4


def test_heal_json_and_dry_run(fake_llm) -> None:
    fake_llm.responses[LocatorSuggestions] = LocatorSuggestions(
        broken_selector="x", likely_cause="c", candidates=[], recommended="", notes=[]
    )
    res = runner.invoke(cli.app, ["heal", "x", "--dom", str(EX / "heal/page.html"), "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout)["broken_selector"] == "x"
    assert (
        runner.invoke(
            cli.app, ["heal", "x", "--dom", str(EX / "heal/page.html"), "--dry-run"]
        ).exit_code
        == 0
    )


# ---- error mapping --------------------------------------------------------------


def test_model_refusal_maps_to_exit_2(monkeypatch) -> None:
    class Refusing:
        def complete(self, *, system, user, schema):
            raise LLMRefusedError("general_harms", "no")

    monkeypatch.setattr(cli, "_llm_override", Refusing())
    res = runner.invoke(cli.app, ["heal", "x", "--dom", str(EX / "heal/page.html")])
    assert res.exit_code == 2
    assert "declined" in res.output
