"""Write a generated suite to disk safely and give it a deterministic scaffold."""

from __future__ import annotations

import ast
from pathlib import Path

from ai_test_architect.schemas import GeneratedTestFile, GeneratedTestSuite

CONFTEST = '''"""Shared fixtures for the generated API tests (written by ai-test-architect)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import pytest


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get("API_BASE_URL")
    if not url:
        pytest.skip("API_BASE_URL is not set")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def api(base_url: str) -> Iterator[httpx.Client]:
    headers = {"Accept": "application/json"}
    token = os.environ.get("API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(base_url=base_url, headers=headers, timeout=15.0) as client:
        yield client
'''


class WriteError(RuntimeError):
    pass


def syntax_errors(files: list[GeneratedTestFile]) -> dict[str, str]:
    """Compile every generated file; return {path: error} for the ones that do not parse."""
    problems: dict[str, str] = {}
    for f in files:
        try:
            ast.parse(f.content, filename=f.path)
        except SyntaxError as exc:
            problems[f.path] = f"line {exc.lineno}: {exc.msg}"
    return problems


def write_suite(suite: GeneratedTestSuite, out_dir: Path, *, overwrite: bool = False) -> list[Path]:
    """Write files under ``out_dir`` (never outside it) and add a conftest if missing."""
    out_dir = out_dir.resolve()
    written: list[Path] = []
    files = list(suite.files)
    if not any(f.path.endswith("conftest.py") for f in files):
        files.append(GeneratedTestFile(path="tests/conftest.py", content=CONFTEST))
    for f in files:
        target = (out_dir / f.path).resolve()
        if out_dir not in target.parents:
            msg = f"refusing to write outside {out_dir}: {f.path}"
            raise WriteError(msg)
        if target.exists() and not overwrite:
            msg = f"{target} exists (use --overwrite)"
            raise WriteError(msg)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content.rstrip("\n") + "\n", encoding="utf-8")
        written.append(target)
    return written
