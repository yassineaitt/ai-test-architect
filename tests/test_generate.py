from pathlib import Path

import pytest

from ai_test_architect.generate.openapi import SpecError, digest, load_spec
from ai_test_architect.generate.writer import CONFTEST, WriteError, syntax_errors, write_suite
from ai_test_architect.schemas import GeneratedTestFile, GeneratedTestSuite

EXAMPLE = Path(__file__).parents[1] / "examples" / "openapi" / "petstore.yaml"


def test_load_and_digest_example_spec() -> None:
    doc = load_spec(EXAMPLE)
    d = digest(doc)
    assert d.title == "Pet Shelter API"
    assert [op.label for op in d.operations] == [
        "GET /pets",
        "POST /pets",
        "GET /pets/{petId}",
        "DELETE /pets/{petId}",
        "POST /pets/{petId}/adoptions",
    ]
    get_pet = next(op for op in d.operations if op.operation_id == "getPet")
    assert get_pet.parameters[0]["name"] == "petId"  # path-level params are merged
    text = d.to_prompt_text()
    assert "### POST /pets  (operationId=createPet, tag=pets)" in text
    assert "components.schemas" in text


def test_digest_filters_by_tag() -> None:
    d = digest(load_spec(EXAMPLE), tags={"adoptions"})
    assert [op.operation_id for op in d.operations] == ["requestAdoption"]


def test_load_rejects_non_openapi_and_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "swagger2.yaml").write_text(
        "swagger: '2.0'\ninfo: {title: x, version: '1'}\npaths: {}\n"
    )
    with pytest.raises(SpecError, match="not an OpenAPI 3"):
        load_spec(tmp_path / "swagger2.yaml")
    (tmp_path / "broken.yaml").write_text("openapi: 3.0.0\ninfo: [unclosed\n")
    with pytest.raises(SpecError, match="not valid JSON/YAML"):
        load_spec(tmp_path / "broken.yaml")
    (tmp_path / "invalid.json").write_text('{"openapi": "3.0.0", "paths": {}}')  # missing info
    with pytest.raises(SpecError, match="failed OpenAPI validation"):
        load_spec(tmp_path / "invalid.json")
    with pytest.raises(SpecError, match="cannot read"):
        load_spec(tmp_path / "missing.yaml")


def test_syntax_errors_reports_bad_files() -> None:
    files = [
        GeneratedTestFile(path="tests/test_ok.py", content="def test_a():\n    assert True\n"),
        GeneratedTestFile(path="tests/test_bad.py", content="def test_b(:\n    pass\n"),
    ]
    assert list(syntax_errors(files)) == ["tests/test_bad.py"]


def test_write_suite_adds_conftest_and_refuses_overwrite(tmp_path: Path) -> None:
    suite = GeneratedTestSuite(
        files=[GeneratedTestFile(path="tests/test_pets.py", content="def test_x():\n    pass")],
        covered_operations=["GET /pets"],
        assumptions=[],
    )
    written = write_suite(suite, tmp_path)
    assert sorted(p.name for p in written) == ["conftest.py", "test_pets.py"]
    assert (tmp_path / "tests" / "conftest.py").read_text() == CONFTEST
    with pytest.raises(WriteError, match="exists"):
        write_suite(suite, tmp_path)
    write_suite(suite, tmp_path, overwrite=True)


def test_generated_paths_cannot_escape_output_dir(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe path"):
        GeneratedTestFile(path="../evil.py", content="")
    with pytest.raises(ValueError, match=r"expected a \.py"):
        GeneratedTestFile(path="tests/notes.txt", content="")
