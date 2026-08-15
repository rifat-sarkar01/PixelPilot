"""Unit tests for SystemPromptBuilder's visual-plan injection."""

from __future__ import annotations

from pixelpilot.prompts.system import SystemPromptBuilder


def test_visual_plan_is_injected_into_system_prompt():
    builder = SystemPromptBuilder(editor="gimp")
    plan_text = "Scene: blank canvas.\n- car body: color [178, 34, 34], size 60% width, position center"

    messages = builder.build_messages("draw a car", visual_plan=plan_text)

    system_content = messages[0]["content"]
    assert messages[0]["role"] == "system"
    assert plan_text in system_content


def test_no_visual_plan_shows_explicit_fallback_not_raw_placeholder():
    builder = SystemPromptBuilder(editor="gimp")

    messages = builder.build_messages("draw a car", visual_plan=None)

    system_content = messages[0]["content"]
    # string.Template.safe_substitute leaves "$visual_plan" verbatim if a
    # value isn't supplied - guard against ever regressing to that.
    assert "$visual_plan" not in system_content
    assert "no vision plan" in system_content.lower()
