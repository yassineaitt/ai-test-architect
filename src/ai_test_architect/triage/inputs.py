"""Collect failures from JUnit XML and the relevant slice of log files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from junitparser import Error, Failure, JUnitXml, TestCase


class TriageInputError(ValueError):
    pass


@dataclass(frozen=True)
class FailedTest:
    suite: str
    classname: str
    name: str
    kind: str  # failure | error
    message: str
    text: str
    time: float
    file: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.classname}::{self.name}" if self.classname else self.name

    def to_prompt_text(self) -> str:
        head = f"[{self.kind.upper()}] {self.full_name} ({self.time:.2f}s)"
        if self.file:
            head += f"  file={self.file}"
        return f"{head}\nmessage: {self.message}\n{self.text}".rstrip()


def load_failures(paths: list[Path]) -> tuple[list[FailedTest], int]:
    """Return (failed tests, total tests) across one or more JUnit XML files."""
    failures: list[FailedTest] = []
    total = 0
    for path in paths:
        try:
            root: Any = JUnitXml.fromfile(str(path))
        except Exception as exc:
            msg = f"{path} is not readable JUnit XML: {exc}"
            raise TriageInputError(msg) from exc
        # fromfile returns a <testsuites> container or a bare <testsuite>; normalise to a list.
        suites = list(root) if root._elem.tag == "testsuites" else [root]
        for suite in suites:
            for case in suite:
                total += 1
                failures.extend(_extract(suite.name or path.stem, case))
    return failures, total


def _extract(suite_name: str, case: TestCase) -> list[FailedTest]:
    out: list[FailedTest] = []
    for result in case.result:
        if isinstance(result, Failure | Error):
            out.append(
                FailedTest(
                    suite=suite_name,
                    classname=case.classname or "",
                    name=case.name or "",
                    kind="failure" if isinstance(result, Failure) else "error",
                    message=(result.message or "").strip(),
                    text=(result.text or "").strip(),
                    time=float(case.time or 0.0),
                    file=case._elem.attrib.get("file"),
                )
            )
    return out


def load_logs(paths: list[Path], *, tail_lines: int = 400) -> str:
    """Concatenate the tail of each log; most failures explain themselves at the end."""
    chunks: list[str] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            msg = f"cannot read log {path}: {exc}"
            raise TriageInputError(msg) from exc
        tail = lines[-tail_lines:]
        omitted = len(lines) - len(tail)
        header = f"--- {path.name} (last {len(tail)} of {len(lines)} lines"
        header += f", {omitted} omitted)" if omitted else ")"
        chunks.append("\n".join([header, *tail]))
    return "\n\n".join(chunks)
