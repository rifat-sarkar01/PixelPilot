"""Error recovery loop (implementation_plan.md §4.5.3).

When a script fails, the error + original script + canvas state are fed back to the
code model for a corrected script. Retries up to ``max_retries``, then gives up.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pixelpilot.bridge.state import CanvasState
from pixelpilot.codegen.validator import SafetyValidator, extract_code_block
from pixelpilot.config import Settings
from pixelpilot.ollama.client import OllamaClient
from pixelpilot.prompts.system import SystemPromptBuilder

FIX_PROMPT = """The following script failed with this error:

{error}

Original script:
```python
{script}
```

Canvas state:
{canvas_state}

Relevant API procedures (use these EXACT signatures - do not invent calls):
{procedures}

Please fix the script so it runs correctly, following every rule above exactly as
strictly as you did the first time (no wrapper functions, selection cleared after
each fill, coordinates as fractions of the real canvas size, etc). Output ONLY the
corrected code inside a single ```python fenced code block."""


@dataclass
class RecoveryResult:
    script: str | None = None
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    success: bool = False


class ErrorRecovery:
    """Feed errors back to the code model until the script is fixed."""

    def __init__(
        self,
        client: OllamaClient,
        settings: Settings,
        editor: str = "gimp",
        model: str | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.editor = editor
        self.model = model or settings.ollama.code_model
        self.max_retries = max_retries or settings.feedback.max_retries

    def recover(
        self,
        original_script: str,
        error: str,
        canvas_state: CanvasState | None = None,
        procedures: list[dict] | None = None,
    ) -> RecoveryResult:
        from pixelpilot.knowledge import get_procedure_by_name

        result = RecoveryResult()
        script = original_script
        current_error = error

        if not procedures:
            procedures = []

        # Collect procedures referenced in the script to ensure their exact signatures are in context
        try:
            import ast
            tree = ast.parse(original_script)
            validator = SafetyValidator(editor=self.editor)
            script_calls = validator._collect_api_calls(tree)
            known_procs = list(procedures)
            known_proc_names = {p.get("name") for p in known_procs}
            for call in script_calls:
                leaf = call.split(".")[-1].replace("_", "-")
                entry = get_procedure_by_name(leaf, editor=self.editor)
                if not entry:
                    entry = get_procedure_by_name(call.replace(".", "-"), editor=self.editor)
                if entry and entry.get("name") not in known_proc_names:
                    known_procs.append(entry)
                    known_proc_names.add(entry.get("name"))
            procedures = known_procs
        except Exception:
            pass

        proc_text = self._format_procedures(procedures) or "(none retrieved - rely on your knowledge)"
        system_rules = SystemPromptBuilder(editor=self.editor).editor_rules()

        for attempt in range(self.max_retries):
            result.attempts = attempt + 1
            result.errors.append(current_error)
            prompt = FIX_PROMPT.format(
                error=current_error,
                script=script,
                canvas_state=canvas_state.to_compact_json() if canvas_state else "{}",
                procedures=proc_text,
            )
            try:
                messages = [
                    {"role": "system", "content": system_rules},
                    {"role": "user", "content": prompt},
                ]
                response = self.client.chat(
                    self.model,
                    messages,
                    stream=self.settings.ollama.stream,
                    temperature=self.settings.ollama.temperature,
                )
                if self.settings.ollama.stream and hasattr(response, "__iter__") and not isinstance(response, dict):
                    from pixelpilot.ollama.streaming import collect_chat_stream
                    raw = collect_chat_stream(response)
                elif isinstance(response, dict):
                    raw = (response.get("message") or {}).get("content", "")
                else:
                    raw = str(response)
                fixed = extract_code_block(raw)
            except Exception as exc:  # noqa: BLE001 - cannot reach the model
                result.errors.append(f"Model call failed: {exc}")
                break

            if not fixed:
                result.errors.append("Model returned no code block.")
                current_error = (
                    "Your response did not contain a valid Python script inside a "
                    "```python fenced block. Output ONLY the complete Python script inside a single ```python block."
                )
                continue

            report = SafetyValidator(editor=self.editor).validate(fixed)
            if report.passed:
                result.script = fixed
                result.success = True
                return result
            script = fixed
            current_error = "Safety validation failed: " + "; ".join(report.errors)

        return result

    @staticmethod
    def _format_procedures(procedures: list[dict]) -> str:
        lines = []
        for proc in procedures:
            name = proc.get("name", "?")
            sig = proc.get("signature") or proc.get("gimp3_signature") or ""
            desc = proc.get("description", "")
            entry = f"- {name}"
            if sig:
                entry += f" : {sig}"
            if desc:
                entry += f"  -- {desc}"
            lines.append(entry)
        return "\n".join(lines)
