"""Render a triage report as Markdown (for PR comments) or JSON."""

from __future__ import annotations

from ai_test_architect.schemas import TriageReport


def to_markdown(report: TriageReport, *, title: str = "Test failure triage") -> str:
    pct = f"{report.confidence:.0%}"
    lines = [
        f"## {title}",
        "",
        f"**Summary:** {report.summary}",
        "",
        f"**Category:** `{report.category}` · **Confidence:** {pct}",
        "",
        "### Root cause",
        report.root_cause,
        "",
    ]
    if report.evidence:
        lines += ["### Evidence", *[f"- `{e}`" for e in report.evidence], ""]
    if report.suggested_fix:
        fix = report.suggested_fix
        lines += ["### Suggested fix", f"**Target:** `{fix.target}`", "", fix.description, ""]
        if fix.patch.strip():
            lines += ["```diff", fix.patch.rstrip(), "```", ""]
    if report.next_steps:
        lines += ["### Next steps", *[f"1. {s}" for s in report.next_steps], ""]
    return "\n".join(lines).rstrip() + "\n"
