from pathlib import Path

from ai_test_architect.heal.dom import selector_mentions, summarize_dom

EX = Path(__file__).parents[1] / "examples" / "heal"


def test_summarize_dom_keeps_locator_relevant_elements_only() -> None:
    html = (EX / "page.html").read_text()
    summary = summarize_dom(html)
    assert 'data-testid="submit-adoption"' in summary
    assert "'Send request'" in summary
    assert 'placeholder="you@example.com"' in summary
    assert "window.__x" not in summary  # scripts dropped
    assert "<div" not in summary  # plain containers dropped
    assert summary.splitlines()[0].lstrip().startswith("<header")


def test_summarize_dom_caps_element_count() -> None:
    html = "".join(f"<button>b{i}</button>" for i in range(50))
    summary = summarize_dom(html, max_elements=10)
    assert summary.count("<button") == 10
    assert "40 more elements omitted" in summary


def test_selector_mentions_finds_surviving_tokens() -> None:
    html = (EX / "page.html").read_text()
    assert selector_mentions(html, "#submit-btn") == []
    # "text" survives because it is a substring of <textarea>; the heuristic is deliberately cheap.
    assert selector_mentions(html, "[data-testid='cancel-adoption'] >> text=Cancel") == [
        "Cancel",
        "cancel-adoption",
        "data-testid",
        "text",
    ]
