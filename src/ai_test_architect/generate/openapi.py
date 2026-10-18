"""Load, validate and compact an OpenAPI 3 document for prompting.

The full spec is rarely needed: the model works from a per-operation digest (method,
path, parameters, request body schema, response schemas, examples). The digest is also
what gets redacted and size-bounded before it reaches the API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from openapi_spec_validator import validate

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


class SpecError(ValueError):
    """The document could not be loaded or is not a valid OpenAPI 3 spec."""


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    operation_id: str
    tag: str
    summary: str
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] | None = None
    responses: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.method.upper()} {self.path}"


@dataclass(frozen=True)
class SpecDigest:
    title: str
    version: str
    servers: list[str]
    operations: list[Operation]
    schemas: dict[str, Any]

    def to_prompt_text(self) -> str:
        """Compact, deterministic text form (sorted keys, no whitespace noise)."""
        lines = [
            f"API: {self.title} v{self.version}",
            f"Servers: {', '.join(self.servers) or '(none)'}",
            "",
        ]
        for op in self.operations:
            lines.append(f"### {op.label}  (operationId={op.operation_id}, tag={op.tag})")
            if op.summary:
                lines.append(op.summary)
            if op.parameters:
                lines.append(
                    "parameters: "
                    + json.dumps(op.parameters, sort_keys=True, separators=(",", ":"))
                )
            if op.request_body is not None:
                lines.append(
                    "requestBody: "
                    + json.dumps(op.request_body, sort_keys=True, separators=(",", ":"))
                )
            lines.append(
                "responses: " + json.dumps(op.responses, sort_keys=True, separators=(",", ":"))
            )
            lines.append("")
        if self.schemas:
            lines.append("### components.schemas")
            lines.append(json.dumps(self.schemas, sort_keys=True, separators=(",", ":")))
        return "\n".join(lines)


def load_spec(path: Path) -> dict[str, Any]:
    """Read YAML or JSON and validate it as OpenAPI 3.x."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read {path}: {exc}"
        raise SpecError(msg) from exc
    try:
        doc = json.loads(raw) if path.suffix.lower() == ".json" else yaml.safe_load(raw)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        msg = f"{path} is not valid JSON/YAML: {exc}"
        raise SpecError(msg) from exc
    if not isinstance(doc, dict) or not str(doc.get("openapi", "")).startswith("3."):
        msg = f"{path} is not an OpenAPI 3.x document (missing 'openapi: 3.x')"
        raise SpecError(msg)
    try:
        validate(doc)
    except Exception as exc:  # the validator raises several unrelated types
        msg = f"{path} failed OpenAPI validation: {exc}"
        raise SpecError(msg) from exc
    return doc


def digest(doc: dict[str, Any], *, tags: set[str] | None = None) -> SpecDigest:
    """Flatten paths into operations, optionally filtered by tag."""
    info = doc.get("info", {})
    servers = [s.get("url", "") for s in doc.get("servers", []) if isinstance(s, dict)]
    ops: list[Operation] = []
    for path, item in sorted(doc.get("paths", {}).items()):
        if not isinstance(item, dict):
            continue
        shared_params = item.get("parameters", [])
        for method in HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            op_tags = op.get("tags") or ["default"]
            tag = str(op_tags[0])
            if tags and tag not in tags:
                continue
            ops.append(
                Operation(
                    method=method,
                    path=path,
                    operation_id=str(op.get("operationId") or f"{method}_{_slug(path)}"),
                    tag=tag,
                    summary=str(op.get("summary") or op.get("description") or ""),
                    parameters=[*shared_params, *op.get("parameters", [])],
                    request_body=op.get("requestBody"),
                    responses=op.get("responses", {}),
                )
            )
    return SpecDigest(
        title=str(info.get("title", "API")),
        version=str(info.get("version", "")),
        servers=servers,
        operations=ops,
        schemas=doc.get("components", {}).get("schemas", {}),
    )


def _slug(path: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in path).strip("_")
