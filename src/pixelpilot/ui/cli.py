"""CLI / REPL interface (implementation_plan.md §4.6.1 / Phase 1).

Interactive chat: user intent -> RAG context -> Ollama code model -> safety validation
-> script preview -> execution (if an editor bridge is reachable).
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from pixelpilot import __version__
from pixelpilot.bridge import CanvasStateTracker, GimpBridge, KritaBridge
from pixelpilot.bridge.base import BridgeConnectionError, BridgeExecutionError
from pixelpilot.bridge.launcher import LauncherError, launch_and_wait
from pixelpilot.codegen import (
    GimpCodeGen,
    KritaCodeGen,
    SafetyValidator,
    extract_code_block,
)
from pixelpilot.config import Settings, ensure_config_file, load_settings
from pixelpilot.ollama.client import OllamaClient
from pixelpilot.rag.retriever import Retriever

COMMANDS = {
    "/quit": "Exit PixelPilot",
    "/exit": "Alias for /quit",
    "/help": "Show this help",
    "/clear": "Clear the conversation context",
    "/undo": "Undo the last operation in the editor",
    "/status": "Show connection and model status",
    "/connect": "(Re)connect to the editor, launching it if needed",
}

_HELP_TEXT = "\n".join(f"  {cmd:<12} {desc}" for cmd, desc in COMMANDS.items())


class PixelPilotCLI:
    def __init__(self, settings: Settings, args: argparse.Namespace) -> None:
        self.settings = settings
        self.console = Console()
        self.args = args

        self.editor = args.editor or settings.editor.default
        self.mode = args.mode or settings.safety.mode
        self.vision_enabled = settings.feedback.vision_enabled and not args.no_vision

        self.code_model = args.model or settings.ollama.code_model
        self.client = OllamaClient(settings.ollama.base_url)
        self.ollama_ok = self.client.ping()
        self.bridge = self._create_bridge()
        self.bridge_ok = False
        self.tracker = CanvasStateTracker()
        self.history: list[dict[str, str]] = []
        self.retriever: Retriever | None = None
        self._vision_recovery_rounds = 0

    # ------------------------------------------------------------------ setup

    def _create_bridge(self):
        if self.editor == "krita":
            return KritaBridge(
                host=self.settings.editor.krita.host,
                port=self.settings.editor.krita.port,
            )
        return GimpBridge(
            host=self.settings.editor.gimp.host,
            port=self.settings.editor.gimp.port,
        )

    def _try_connect_bridge(self, auto_launch: bool = True) -> None:
        if self._connect_once():
            return

        backend = getattr(self.settings.editor, self.editor)
        if auto_launch and self.editor == "gimp" and backend.auto_launch:
            self._auto_launch_gimp(backend)
            self._connect_once()

    def _connect_once(self) -> bool:
        """Try a single connection attempt. Returns True on success."""
        try:
            self.bridge.connect()
            self.bridge_ok = True
            state = self.bridge.get_canvas_state()
            self.tracker.update(state)
            return True
        except BridgeConnectionError:
            self.bridge_ok = False
            return False
        except BridgeExecutionError:
            # Bridge is reachable but has no canvas yet (e.g. no open images).
            self.bridge_ok = True
            return True

    def _auto_launch_gimp(self, backend) -> None:
        self.console.print(
            "[dim]GIMP not detected - looking for a local install and launching it "
            "with the PixelPilot bridge...[/dim]"
        )

        def _tick() -> None:
            self.console.print("[dim]  still waiting for GIMP to start...[/dim]")

        try:
            came_up = launch_and_wait(
                host=backend.host,
                port=backend.port,
                binary_path=backend.binary_path,
                timeout=backend.launch_timeout,
                on_progress=_tick,
            )
        except LauncherError as exc:
            self.console.print(f"[yellow]{exc}[/yellow]")
            return

        if came_up:
            self.console.print("[green]GIMP is up.[/green]")
        else:
            self.console.print(
                "[yellow]GIMP did not come up in time. It may still be starting - "
                "try /connect again in a moment, or check that the PixelPilot plugin "
                "is installed.[/yellow]"
            )

    # ------------------------------------------------------------------- run

    def run(self) -> int:
        ensure_config_file()
        self.console.rule(f"[bold blue]PixelPilot v{__version__}[/bold blue]")
        self._print_status()
        self._try_connect_bridge()

        history_path = Path(self.settings.session.history_file).expanduser()
        history_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            session = PromptSession(history=FileHistory(str(history_path)))
        except Exception:
            session = None

        if not self.ollama_ok:
            self.console.print(
                "\n[bold yellow]Ollama is not reachable - running in DEMO mode.[/bold yellow]\n"
                "Start it with `ollama serve`, then run: pixelpilot\n"
            )

        while True:
            try:
                if session is not None:
                    text = session.prompt(f"[{self.editor}] You: ")
                else:
                    text = input(f"[{self.editor}] You: ")
            except (KeyboardInterrupt, EOFError):
                self.console.print("\nBye!")
                return 0

            text = text.strip()
            if not text:
                continue
            if text.startswith("/"):
                if self._handle_command(text):
                    continue
                if text in ("/quit", "/exit"):
                    return 0
                continue
            self._handle_message(text)

    # --------------------------------------------------------------- commands

    def _handle_command(self, text: str) -> bool:
        """Handle a slash command. Returns True if handled."""
        if text == "/help":
            self.console.print(_HELP_TEXT)
        elif text == "/clear":
            self.history = []
            self.console.print("[dim]Conversation context cleared.[/dim]")
        elif text == "/status":
            self._print_status()
        elif text == "/undo":
            self._bridge_undo()
        elif text == "/connect":
            self._try_connect_bridge()
            self._print_status()
        else:
            return False
        return True

    def _bridge_undo(self) -> None:
        if not self.bridge_ok:
            self.console.print("[yellow]Editor bridge not connected - can't undo.[/yellow]")
            return
        try:
            self.bridge.undo()
            self.console.print("[green]Undone.[/green]")
        except BridgeConnectionError as exc:
            self.console.print(f"[red]{exc}[/red]")

    # ---------------------------------------------------------------- status

    def _print_status(self) -> None:
        ollama = "OK" if self.ollama_ok else "UNREACHABLE"
        editor = self.editor
        table = Table.grid(padding=(0, 2))
        table.add_row("Ollama", f"{self.settings.ollama.base_url}  [{ollama}]")
        table.add_row("Code model", self.code_model)
        table.add_row(
            "Vision model",
            f"{self.settings.ollama.vision_model}  "
            f"{'[enabled]' if self.vision_enabled else '[disabled]'}",
        )
        bridge_state = "connected" if self.bridge_ok else "NOT CONNECTED"
        backend = getattr(self.settings.editor, self.editor)
        table.add_row("Editor", f"{editor}  [{bridge_state}]")
        table.add_row("Bridge address", f"{backend.host}:{backend.port}")
        table.add_row("Safety mode", self.mode)
        self.console.print(Panel(table, title="Status", border_style="blue"))
        if not self.bridge_ok:
            hint = (
                "Run /connect to launch GIMP with the PixelPilot bridge."
                if editor == "gimp"
                else f"Open {editor.title()} with the PixelPilot plugin enabled, then run /connect."
            )
            self.console.print(f"[dim]{hint}[/dim]")

    # ------------------------------------------------------------- messaging

    def _handle_message(self, text: str) -> None:
        self.history.append({"role": "user", "content": text})

        # 1. RAG context (skipped in demo mode).
        procedures: list[dict] = []
        example: dict | None = None
        if self.ollama_ok:
            try:
                procedures, example = self._retrieve_context(text)
            except Exception as exc:  # noqa: BLE001
                self.console.print(f"[dim]RAG retrieval skipped: {exc}[/dim]")

        # 2. Generate the script.
        if self.ollama_ok:
            script = self._generate_script(text, procedures, example)
        else:
            script = self._demo_generate(text)

        if not script:
            self.console.print("[red]No script was generated.[/red]")
            return

        # 3. Validate.
        validator = SafetyValidator(editor=self.editor)
        report = validator.validate(script)
        self._show_script(script, report)

        # 4. Confirmation + execution.
        if report.passed:
            if self._confirm_execute(report):
                self._execute(script)
        else:
            self.console.print(
                "[red]Script failed safety validation - not executing.[/red]"
            )

        self.history.append({"role": "assistant", "content": "script generated"})
        self._prune_history()

    def _retrieve_context(self, text: str):
        if self.retriever is None:
            self.retriever = Retriever(self.client, self._make_store(), self.settings)
        results = self.retriever.retrieve_all(self.editor, text)
        procedures = results.get("procedures", [])
        examples = results.get("examples", [])
        return procedures, (examples[0] if examples else None)

    def _make_store(self):
        from pixelpilot.rag.indexer import _make_store

        return _make_store(self.settings)

    def _generate_script(self, text: str, procedures: list[dict], example: dict | None) -> str | None:
        from pixelpilot.prompts.system import SystemPromptBuilder

        builder = SystemPromptBuilder(
            editor=self.editor, num_ctx=self.settings.ollama.num_ctx, vision=self.vision_enabled
        )
        messages = builder.build_messages(
            text,
            canvas_state=self.tracker.state.to_dict() if not self.tracker.state.is_empty() else None,
            procedures=procedures,
            example=example,
            history=self.history[-self.settings.session.max_history_turns * 2 :],
        )
        for attempt in range(3):
            try:
                response = self.client.chat(
                    self.code_model,
                    messages,
                    stream=self.settings.ollama.stream,
                    temperature=self.settings.ollama.temperature,
                )
                if self.settings.ollama.stream:
                    from pixelpilot.ollama.streaming import collect_chat_stream

                    content = collect_chat_stream(response)
                else:
                    content = (response.get("message") or {}).get("content", "")
            except Exception as exc:  # noqa: BLE001
                self.console.print(f"[red]Model call failed: {exc}[/red]")
                return None
            script = extract_code_block(content)
            if script:
                return script
            if attempt < 2:
                self.console.print(
                    "[yellow]Model did not return a fenced script - retrying...[/yellow]"
                )
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response did not contain the Python script in a "
                            "fenced code block. Respond with ONLY the full Python script "
                            "inside a single ```python fenced code block, with no explanation."
                        ),
                    }
                )
        return None

    def _demo_generate(self, text: str) -> str:
        """Deterministic fallback so the pipeline is explorable without Ollama."""
        lowered = text.lower()
        codegen = GimpCodeGen() if self.editor == "gimp" else KritaCodeGen()
        plan = self._plan_from_keywords(lowered)
        if plan is None:
            self.console.print("[yellow]Demo mode: I only know a few canned operations "
                               "(blur, desaturate, brightness, resize, flip).[/yellow]")
            return None
        return codegen.render(plan)

    def _plan_from_keywords(self, text: str):
        from pixelpilot.codegen import Operation, ScriptPlan

        plan = ScriptPlan(editor=self.editor, title="demo")
        if "blur" in text:
            plan.add(Operation("filter.gaussian_blur", {"radius": 5.0}, "Gaussian blur"))
        elif "desaturate" in text or "black and white" in text or "grayscale" in text:
            plan.add(Operation("colors.desaturate", {"mode": "luminosity"}, "Desaturate"))
        elif "bright" in text or "contrast" in text:
            plan.add(Operation("colors.brightness_contrast", {"brightness": 15, "contrast": 10}))
        elif "resize" in text or "scale" in text:
            plan.add(Operation("transform.scale", {"width": 800, "height": 600}))
        elif "flip" in text:
            plan.add(Operation("transform.flip", {"direction": "horizontal"}))
        else:
            return None
        return plan

    # --------------------------------------------------------------- preview

    def _show_script(self, script: str, report) -> None:
        syntax = Syntax(script, "python", line_numbers=True, word_wrap=True)
        self.console.print(Panel(syntax, title=f"Script preview ({len(script.splitlines())} lines)"))

        status = "[green]passed[/green]" if report.passed else "[red]failed[/red]"
        self.console.print(f"Safety: {status}")
        for warning in report.warnings:
            self.console.print(f"  [yellow]warn: {warning}[/yellow]")
        for error in report.errors:
            self.console.print(f"  [red]error: {error}[/red]")

    def _confirm_execute(self, report) -> bool:
        if self.mode == "dry-run":
            self.console.print("[dim]Dry-run mode - script not executed.[/dim]")
            return False
        if self.mode == "auto":
            return True
        try:
            answer = input("Execute? [Y/n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return False
        return answer in ("", "y", "yes")

    # -------------------------------------------------------------- execution

    def _execute(self, script: str) -> None:
        if not self.bridge_ok:
            # GIMP may have finished starting (or been opened manually) since
            # the last attempt - try a cheap reconnect before giving up.
            self._connect_once()
        if not self.bridge_ok:
            self.console.print(
                f"[yellow]Editor bridge not connected - script validated but not executed.[/yellow]\n"
                f"Run /connect to launch {self.editor.title()} with the PixelPilot bridge, "
                f"or open it manually with the plugin enabled."
            )
            return
        self.console.print("[dim]Executing...[/dim]")
        try:
            result = self.bridge.execute_script(script)
            self.console.print(f"[green]Executed.[/green] {result}")
        except Exception as exc:  # noqa: BLE001
            self.console.print(f"[red]Execution failed: {exc}[/red]")
            self._error_recovery(script, str(exc))
            return

        # Always save a PNG snapshot of the result so the user has the image
        # even if the generated script never wrote a file.
        self._save_snapshot()

        # Feedback: screenshot + vision (or text fallback).
        if self.vision_enabled:
            self._vision_feedback(script)
        else:
            self._text_feedback()

    def _save_snapshot(self) -> None:
        try:
            png = self.bridge.capture_screenshot()
        except BridgeConnectionError:
            return
        out_dir = Path("outputs").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"pixelpilot_{ts}.png"
        path.write_bytes(png)
        self.console.print(f"[green]Snapshot saved:[/green] {path}")

    def _vision_feedback(self, script: str) -> None:
        try:
            screenshot = self.bridge.capture_screenshot()
        except BridgeConnectionError as exc:
            self.console.print(f"[dim]Screenshot unavailable: {exc}[/dim]")
            return
        from pixelpilot.feedback.vision import VisionAnalyzer

        analyzer = VisionAnalyzer(
            self.client, model=self.settings.ollama.vision_model, enabled=self.vision_enabled
        )
        self.console.print("[dim]Analyzing result with vision model...[/dim]")
        result = analyzer.analyze(screenshot, context=f"Last script:\n{script[:500]}")
        if result.get("success"):
            self.console.print("[green]Vision: the result looks correct.[/green]")
            return
        assessment = result.get("assessment", "")
        fixes = result.get("fixes", [])
        self.console.print(f"[yellow]Vision assessment:[/yellow] {assessment}")
        for fix in fixes:
            self.console.print(f"  - {fix}")
        self._vision_recovery(script, assessment, fixes)

    def _vision_recovery(self, script: str, assessment: str, fixes: list[str]) -> None:
        """Ask the code model to rewrite the script when the vision model reports
        the rendered result does not match the request. Bounded rounds."""
        if self.mode == "dry-run":
            return
        if self._vision_recovery_rounds >= 2:
            self.console.print("[dim]Max vision-recovery rounds reached - stopping.[/dim]")
            return
        self._vision_recovery_rounds += 1

        from pixelpilot.codegen.validator import SafetyValidator, extract_code_block
        from pixelpilot.feedback.error_recovery import ErrorRecovery
        from pixelpilot.ollama.streaming import collect_chat_stream

        procedures: list[dict] = []
        if self.retriever is not None and self.ollama_ok:
            try:
                procedures = self.retriever.retrieve_all(self.editor, assessment).get(
                    "procedures", []
                )
            except Exception:  # noqa: BLE001 - retrieval must not break recovery
                procedures = []
        fixes_text = ("\nSuggested fixes:\n- " + "\n- ".join(fixes)) if fixes else ""
        prompt = (
            "A vision model reviewed the result of your GIMP script and it does not match "
            "the requested image.\n"
            f"Vision assessment: {assessment}\n"
            f"{fixes_text}\n"
            "\nOriginal script:\n```python\n"
            f"{script}\n```\n"
            "\nCurrent canvas state:\n"
            f"{self.tracker.state.to_compact_json()}\n"
            "\nRelevant API procedures (use these EXACT signatures - do not invent calls):\n"
            + (
                ErrorRecovery._format_procedures(procedures)
                if procedures
                else "(none retrieved - rely on your knowledge)"
            )
            + "\n\nWrite a corrected, complete script that produces the desired image. "
            "If the current canvas holds a wrong result, create a BRAND NEW image with "
            "pdb.gimp_image_new, show it with pdb.gimp_display_new, and never use opaque "
            "RGB_IMAGE layers (they hide everything below) - use RGBA_IMAGE. "
            "Output ONLY the corrected code inside a single ```python fenced code block."
        )
        self.console.print(
            f"[yellow]Vision found issues - asking the model to fix "
            f"(round {self._vision_recovery_rounds}/2)...[/yellow]"
        )
        try:
            response = self.client.chat(
                self.code_model,
                [{"role": "user", "content": prompt}],
                stream=self.settings.ollama.stream,
                temperature=self.settings.ollama.temperature,
            )
            if self.settings.ollama.stream:
                content = collect_chat_stream(response)
            else:
                content = (response.get("message") or {}).get("content", "")
        except Exception as exc:  # noqa: BLE001 - cannot reach the model
            self.console.print(f"[red]Vision-recovery model call failed: {exc}[/red]")
            return
        fixed = extract_code_block(content)
        if not fixed:
            self.console.print("[dim]Model produced no corrected script.[/dim]")
            return
        report = SafetyValidator(editor=self.editor).validate(fixed)
        self._show_script(fixed, report)
        if report.passed and self._confirm_execute(report):
            self._execute(fixed)

    def _text_feedback(self) -> None:
        from pixelpilot.feedback.text_fallback import TextFallbackAnalyzer

        try:
            screenshot = self.bridge.capture_screenshot()
        except BridgeConnectionError:
            screenshot = None
        self.tracker.update(self.bridge.get_canvas_state())
        analyzer = TextFallbackAnalyzer()
        desc = analyzer.describe(self.tracker.state, screenshot, self.tracker.summarize_changes())
        self.console.print(f"[dim]{desc}[/dim]")

    def _error_recovery(self, script: str, error: str) -> None:
        if self.mode == "dry-run":
            return
        from pixelpilot.feedback.error_recovery import ErrorRecovery

        recovery = ErrorRecovery(self.client, self.settings, editor=self.editor)
        self.console.print(f"[yellow]Attempting error recovery (max {recovery.max_retries})...[/yellow]")
        procedures: list[dict] = []
        if self.ollama_ok:
            try:
                procedures, _ = self._retrieve_context(error)
            except Exception as exc:  # noqa: BLE001
                self.console.print(f"[dim]RAG retrieval skipped: {exc}[/dim]")
        result = recovery.recover(script, error, self.tracker.state, procedures=procedures)
        if result.success and result.script:
            self.console.print("[green]Recovery produced a fixed script.[/green]")
            self._show_script(result.script, SafetyValidator(editor=self.editor).validate(result.script))
            if self._confirm_execute(SafetyValidator(editor=self.editor).validate(result.script)):
                self._execute(result.script)
        else:
            self.console.print("[red]Recovery failed - please ask the user to intervene.[/red]")

    # ---------------------------------------------------------------- history

    def _prune_history(self) -> None:
        max_turns = self.settings.session.max_history_turns
        if len(self.history) > max_turns * 2:
            self.history = self.history[-(max_turns * 2) :]


def run_cli(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    return PixelPilotCLI(settings, args).run()
