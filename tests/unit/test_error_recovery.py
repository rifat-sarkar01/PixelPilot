"""Regression tests for the error-recovery rewrite loop.

Previously ErrorRecovery.recover() called client.generate() with a bare
FIX_PROMPT string and nothing else - no system rules, no "don't wrap code in
a helper function", no selection/coordinate guidance, none of the rules the
first-pass generation gets. That's why rewrites regressed (e.g. reintroducing
a `def run_pixelpilot():` wrapper) even when the original script obeyed every
rule. The fix routes recovery through the same chat + system-message path the
main generation call uses.
"""

from __future__ import annotations

from pixelpilot.config import Settings
from pixelpilot.feedback.error_recovery import ErrorRecovery


class _FakeClient:
    """Records every chat() call so tests can assert on what was sent."""

    def __init__(self, fixed_script: str) -> None:
        self.fixed_script = fixed_script
        self.chat_calls: list[dict] = []

    def chat(self, model, messages, stream=False, **kwargs):
        self.chat_calls.append({"model": model, "messages": messages})
        return {"message": {"content": f"```python\n{self.fixed_script}\n```"}}

    def generate(self, *args, **kwargs):  # pragma: no cover - must not be used
        raise AssertionError("recover() must use chat(), not generate() - it drops the system rules")


def test_recover_sends_system_rules_via_chat():
    fixed = (
        "from gimpfu import *\n"
        "image = gimp.image_list()[0]\n"
        "drawable = image.active_drawable\n"
        "pdb.gimp_displays_flush()\n"
    )
    client = _FakeClient(fixed)
    recovery = ErrorRecovery(client=client, settings=Settings(), editor="gimp")

    result = recovery.recover(
        original_script="broken script",
        error="RuntimeError: boom",
    )

    assert result.success
    assert result.script.strip() == fixed.strip()
    assert len(client.chat_calls) == 1

    messages = client.chat_calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    # The system message must actually carry the real editor rules, not be empty.
    assert "selection_none" in messages[0]["content"]
    assert "wrapper function" in messages[0]["content"] or "run_pixelpilot" in messages[0]["content"]
    # The failing error/script must still reach the model via the user turn.
    assert "RuntimeError: boom" in messages[1]["content"]
    assert "broken script" in messages[1]["content"]


def test_recover_gives_up_after_max_retries_on_repeated_validation_failure():
    # A script that fails safety validation every time (forbidden import) -
    # recovery should stop after max_retries rather than looping forever.
    bad_script = "import subprocess\nsubprocess.run(['ls'])\n"
    client = _FakeClient(bad_script)
    recovery = ErrorRecovery(client=client, settings=Settings(), editor="gimp", max_retries=2)

    result = recovery.recover(original_script="broken script", error="some error")

    assert not result.success
    assert result.attempts == 2
    assert len(client.chat_calls) == 2
