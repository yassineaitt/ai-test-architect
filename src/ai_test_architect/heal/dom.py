"""Reduce a DOM snapshot to the interactive elements that matter for locators.

A full page can be megabytes of markup. The model only needs elements a Playwright
locator could target: controls, landmarks and anything carrying test ids, roles or
labels. Each element is emitted as one compact line with its locator-relevant
attributes and visible text, which keeps prompts small and comparisons easy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

INTERACTIVE_TAGS = frozenset(
    {"a", "button", "input", "select", "textarea", "label", "option", "summary", "details", "form"}
)
LANDMARK_TAGS = frozenset(
    {"nav", "main", "header", "footer", "aside", "section", "dialog", "table", "h1", "h2", "h3"}
)
LOCATOR_ATTRS = (
    "data-testid",
    "data-test",
    "data-qa",
    "data-cy",
    "id",
    "name",
    "role",
    "aria-label",
    "aria-labelledby",
    "placeholder",
    "title",
    "alt",
    "type",
    "href",
    "for",
    "class",
)
MAX_TEXT = 80
MIN_TOKEN_LEN = 3


@dataclass
class DomElement:
    tag: str
    attrs: dict[str, str]
    text: str = ""
    depth: int = 0

    def to_line(self) -> str:
        parts = [f"<{self.tag}"]
        parts.extend(f'{k}="{v}"' for k in LOCATOR_ATTRS if (v := self.attrs.get(k)))
        line = " ".join(parts) + ">"
        if self.text:
            line += f" {self.text[:MAX_TEXT]!r}"
        return "  " * min(self.depth, 6) + line


@dataclass
class _Collector(HTMLParser):
    elements: list[DomElement] = field(default_factory=list)
    _stack: list[DomElement | None] = field(default_factory=list)
    _skip_depth: int = 0

    def __post_init__(self) -> None:
        super().__init__(convert_charrefs=True)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "noscript"}:
            self._skip_depth += 1
        if self._skip_depth:
            self._stack.append(None)
            return
        attr_map = {k: (v or "") for k, v in attrs}
        interesting = (
            tag in INTERACTIVE_TAGS
            or tag in LANDMARK_TAGS
            or any(
                a in attr_map
                for a in ("data-testid", "data-test", "data-qa", "data-cy", "role", "aria-label")
            )
        )
        el = DomElement(tag=tag, attrs=attr_map, depth=len(self._stack)) if interesting else None
        if el is not None:
            self.elements.append(el)
        self._stack.append(el)
        if tag in {"input", "img", "br", "hr", "meta", "link"}:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        for el in reversed(self._stack):
            if el is not None:
                if len(el.text) < MAX_TEXT:
                    el.text = (el.text + " " + text).strip()
                break


def summarize_dom(html: str, *, max_elements: int = 400) -> str:
    """Return one line per locator-relevant element, in document order."""
    collector = _Collector()
    collector.feed(html)
    collector.close()
    lines = [el.to_line() for el in collector.elements[:max_elements]]
    if len(collector.elements) > max_elements:
        lines.append(f"…[{len(collector.elements) - max_elements} more elements omitted]")
    return "\n".join(lines)


def selector_mentions(html: str, selector: str) -> list[str]:
    """Cheap heuristic: which tokens of the broken selector still appear anywhere in the DOM."""
    tokens = {t.strip("#.[]='\"()>:, ") for t in selector.replace("=", " ").split()}
    return sorted(t for t in tokens if len(t) >= MIN_TOKEN_LEN and t in html)
