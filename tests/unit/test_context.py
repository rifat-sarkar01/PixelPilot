"""Unit tests for the context budget manager."""

from pixelpilot.prompts.context import ContextBudget, estimate_tokens, truncate_text


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100


def test_truncate_keeps_tail_by_default():
    text = "x" * 4000
    result = truncate_text(text, 100)
    assert estimate_tokens(result) <= 100
    assert result.endswith("x" * 100)
    assert result.startswith("\n...[truncated]")


def test_truncate_from_start():
    text = "x" * 4000
    result = truncate_text(text, 100, from_start=True)
    assert estimate_tokens(result) <= 100
    assert result.startswith("x" * 100)
    assert result.endswith("...[truncated]\n")


def test_budget_scaling():
    base = ContextBudget(8192)
    big = ContextBudget(16384)
    assert big.budgets["history"].max_tokens == base.budgets["history"].max_tokens * 2


def test_fit_truncates_oversized_component():
    budget = ContextBudget(8192)
    long_text = "word " * 5000
    fitted = budget.fit("canvas_state", long_text)
    assert estimate_tokens(fitted) <= budget.budgets["canvas_state"].max_tokens


def test_summarize_history_collapses_old_turns():
    history = [
        {"role": "user", "content": f"request number {i}"}
        for i in range(20)
    ]
    budget = ContextBudget(8192)
    summary = budget.summarize_history(history, max_turns=3, max_tokens=500)
    assert "earlier conversation summary" in summary
    assert estimate_tokens(summary) <= 500
