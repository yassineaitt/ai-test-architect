from pathlib import Path

import pytest

from ai_test_architect.schemas import SuggestedFix, TriageReport
from ai_test_architect.triage.inputs import TriageInputError, load_failures, load_logs
from ai_test_architect.triage.report import to_markdown

EX = Path(__file__).parents[1] / "examples" / "triage"


def test_load_failures_from_example_junit() -> None:
    failures, total = load_failures([EX / "junit.xml"])
    assert total == 4
    assert [(f.kind, f.name) for f in failures] == [
        ("failure", "test_request_adoption_accepted"),
        ("error", "test_adoption_conflict_when_pet_adopted"),
    ]
    first = failures[0]
    assert first.full_name == "tests.api.test_adoptions::test_request_adoption_accepted"
    assert first.file == "tests/api/test_adoptions.py"
    assert "got 500" in first.message
    assert first.to_prompt_text().startswith("[FAILURE] tests.api.test_adoptions::")


def test_load_failures_rejects_garbage(tmp_path: Path) -> None:
    (tmp_path / "x.xml").write_text("<not-junit>")
    with pytest.raises(TriageInputError):
        load_failures([tmp_path / "x.xml"])


def test_load_logs_tails_and_labels(tmp_path: Path) -> None:
    log = tmp_path / "svc.log"
    log.write_text("\n".join(f"line {i}" for i in range(1000)))
    out = load_logs([log], tail_lines=10)
    assert out.startswith("--- svc.log (last 10 of 1000 lines, 990 omitted)")
    assert out.endswith("line 999")
    with pytest.raises(TriageInputError):
        load_logs([tmp_path / "missing.log"])


def test_markdown_report_contains_all_sections() -> None:
    report = TriageReport(
        summary="Adoption endpoint fails because a migration was skipped.",
        root_cause="MIGRATIONS_ENABLED=false left the adoption_requests table missing.",
        category="environment",
        confidence=1.4,  # clamped
        evidence=['relation "adoption_requests" does not exist'],
        suggested_fix=SuggestedFix(
            target="deploy/env", description="Enable migrations", patch="-A\n+B"
        ),
        next_steps=["Re-run migrations", "Re-run the suite"],
    )
    md = to_markdown(report)
    assert "**Confidence:** 100%" in md
    assert "```diff\n-A\n+B\n```" in md
    assert "1. Re-run migrations" in md
    assert "### Evidence" in md


def test_markdown_report_without_fix() -> None:
    report = TriageReport(
        summary="s", root_cause="r", category="unknown", confidence=-1, evidence=[], next_steps=[]
    )
    md = to_markdown(report)
    assert "Suggested fix" not in md
    assert "**Confidence:** 0%" in md
