"""Scrub credentials from anything that is about to be sent to the model.

Logs, specs and DOM snapshots routinely contain tokens. The CLI never forwards user input
to the API without passing it through :func:`redact` first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REDACTED = "[REDACTED]"

# Order matters: specific token formats first, then generic key=value forms.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("bearer", re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-=+/]{8,}")),
    (
        "key-value",
        re.compile(
            r"(?i)\b((?:api[_\-]?key|access[_\-]?key|secret(?:[_\-]?key)?|token|password|passwd|"
            r"pwd|authorization|x-api-key|cookie|set-cookie))\b(\s*[:=]\s*)(['\"]?)"
            r"(?!bearer\b|basic\b|\[REDACTED\])([^'\"\s,;]{4,})"
        ),
    ),
)


@dataclass(frozen=True)
class Redaction:
    """Result of a redaction pass."""

    text: str
    replacements: int
    kinds: tuple[str, ...]


def redact(text: str) -> Redaction:
    """Replace credential-looking substrings with ``[REDACTED]``.

    Key/value forms keep the key and the separator so the model still understands the
    structure (``Authorization: [REDACTED]``).
    """
    total = 0
    kinds: list[str] = []
    for kind, pattern in _PATTERNS:
        if kind == "key-value":
            text, n = pattern.subn(
                lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}", text
            )
        elif kind == "bearer":
            text, n = pattern.subn(lambda m: f"{m.group(1)} {REDACTED}", text)
        else:
            text, n = pattern.subn(REDACTED, text)
        if n:
            total += n
            kinds.append(kind)
    return Redaction(text=text, replacements=total, kinds=tuple(kinds))


def truncate(text: str, max_chars: int, *, keep: str = "tail") -> str:
    """Bound input size, keeping the head or the tail and leaving a visible marker."""
    if len(text) <= max_chars:
        return text
    marker = f"\n…[truncated {len(text) - max_chars} characters]…\n"
    if keep == "head":
        return text[:max_chars] + marker
    return marker + text[-max_chars:]
