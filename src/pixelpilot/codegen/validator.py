"""Safety validator - AST analysis, import allowlisting, API hallucination detection.

Implements the static-analysis layers from ``implementation_plan.md`` §10.2:

* Layer 1: extract code from LLM output (fenced block / tool call)
* Layer 2: AST parse + forbidden-import/builtin enforcement
* Layer 3: API-call validation against the knowledge-base catalog
* Layer 6: undo-group enforcement advice (informational)

Runtime sandboxing (Layer 5) lives in :mod:`pixelpilot.codegen.sandbox`.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from pixelpilot.knowledge import known_api_names

ALLOWED_IMPORTS = {
    "gimp",
    "gimpfu",
    "krita",
    "Krita",
    "math",
    "random",
    "colorsys",
    "json",
    "re",
    "struct",
}

FORBIDDEN_IMPORTS = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "http",
    "urllib",
    "shutil",
    "pathlib",
    "pickle",
    "marshal",
    "ctypes",
    "base64",
    "requests",
    "httpx",
    "smtplib",
    "ftplib",
}

FORBIDDEN_BUILTINS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "globals",
    "locals",
    "vars",
    "memoryview",
    "breakpoint",
    "delattr",
    "setattr",
    "getattr",  # allow getattr? no - can be used to reach forbidden things.
}

FORBIDDEN_RAW_PATTERNS = [
    re.compile(r"\bimport\s+os\b"),
    re.compile(r"\bimport\s+sys\b"),
    re.compile(r"\bimport\s+subprocess\b"),
    re.compile(r"\bimport\s+socket\b"),
    re.compile(r"\bimport\s+urllib\b"),
    re.compile(r"\bimport\s+http\b"),
    re.compile(r"\bos\.system\b"),
    re.compile(r"\bsubprocess\."),
    re.compile(r"\bsocket\."),
    re.compile(r"urllib\.\w*\.?(urlopen|request)"),
    re.compile(r"\b__import__\b"),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\bcompile\s*\("),
    re.compile(r"https?://"),
    re.compile(r"\bopen\s*\("),
]

FENCED_CODE_RE = re.compile(
    r"```(?:python|py|gimp|krita)?[^\n]*\n(.*?)```", re.DOTALL
)


def extract_code_block(text: str) -> str | None:
    """Layer 1: pull the first fenced Python code block out of a response."""
    if not text:
        return None
    match = FENCED_CODE_RE.search(text)
    if match:
        return match.group(1).strip()
    # Unterminated fence (e.g. output hit the token limit): take everything
    # after the first opening fence if it parses as Python.
    start = text.find("```")
    if start != -1:
        rest = text[start:]
        nl = rest.find("\n")
        if nl != -1:
            try:
                ast.parse(rest[nl + 1 :])
            except SyntaxError:
                pass
            else:
                return rest[nl + 1 :].strip()
    # No fence found - if the whole thing parses as Python, accept it as-is.
    try:
        ast.parse(text)
    except SyntaxError:
        return None
    return text.strip()


@dataclass
class SafetyReport:
    script: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unknown_api_calls: list[str] = field(default_factory=list)
    api_calls_checked: int = 0

    @property
    def passed(self) -> bool:
        return not self.errors

    def summary(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "unknown_api_calls": self.unknown_api_calls,
            "api_calls_checked": self.api_calls_checked,
        }


class SafetyValidator:
    """Static safety analysis for generated editor scripts."""

    def __init__(
        self,
        editor: str = "gimp",
        max_script_lines: int = 500,
        check_api: bool = True,
        api_catalog: set | None = None,
    ) -> None:
        self.editor = editor
        self.max_script_lines = max_script_lines
        self.check_api = check_api
        self.api_catalog = api_catalog or known_api_names(editor)

    # ------------------------------------------------------------------ public

    def validate(self, script: str | None) -> SafetyReport:
        report = SafetyReport(script=script)
        if not script or not script.strip():
            report.errors.append("Empty script - nothing to validate.")
            return report

        report.script = script
        self._check_raw_text(script, report)
        self._check_length(script, report)

        try:
            tree = ast.parse(script)
        except SyntaxError as exc:
            report.errors.append(f"Syntax error: {exc.msg} (line {exc.lineno})")
            return report

        self._check_imports(tree, report)
        self._check_builtins(tree, report)
        if self.check_api:
            self._check_api_calls(tree, report)
        return report

    # --------------------------------------------------------------- raw checks

    def _check_raw_text(self, script: str, report: SafetyReport) -> None:
        for pattern in FORBIDDEN_RAW_PATTERNS:
            if pattern.search(script):
                report.errors.append(
                    f"Forbidden pattern detected: {pattern.pattern!r}"
                )

    def _check_length(self, script: str, report: SafetyReport) -> None:
        lines = script.count("\n") + 1
        if lines > self.max_script_lines:
            report.errors.append(
                f"Script exceeds {self.max_script_lines} lines ({lines} lines)."
            )

    # ------------------------------------------------------------------ imports

    def _check_imports(self, tree: ast.AST, report: SafetyReport) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in FORBIDDEN_IMPORTS:
                        report.errors.append(f"Forbidden import: {alias.name}")
                    elif top not in ALLOWED_IMPORTS:
                        report.errors.append(
                            f"Import not on allowlist: {alias.name} "
                            f"(allowed: {sorted(ALLOWED_IMPORTS)})"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                top = module.split(".")[0]
                if top in FORBIDDEN_IMPORTS:
                    report.errors.append(f"Forbidden import from: {module}")
                elif top not in ALLOWED_IMPORTS:
                    report.errors.append(
                        f"Import from not on allowlist: {module}"
                    )

    # ----------------------------------------------------------------- builtins

    def _check_builtins(self, tree: ast.AST, report: SafetyReport) -> None:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in FORBIDDEN_BUILTINS
            ):
                report.errors.append(f"Forbidden builtin call: {node.func.id}()")
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                report.errors.append(f"'{type(node).__name__}' statement is not allowed.")
    # -------------------------------------------------------------------- APIs

    def _collect_api_calls(self, tree: ast.AST) -> list[str]:
        calls: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                calls.append(func.id)
            elif isinstance(func, ast.Attribute):
                parts = [func.attr]
                cur = func.value
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                calls.append(".".join(reversed(parts)))
        return calls

    def _check_api_calls(self, tree: ast.AST, report: SafetyReport) -> None:
        calls = self._collect_api_calls(tree)
        report.api_calls_checked = len(calls)
        known = self.api_catalog
        unknown: list[str] = []
        for call in calls:
            # Bare calls like `print`, `str`, `range` are Python builtins, not editor APIs.
            if self._is_plain_builtin(call):
                continue
            if not self._api_call_known(call, known):
                unknown.append(call)
        for call in unknown:
            report.warnings.append(
                f"Unknown API call (possible hallucination): {call}()"
            )
        report.unknown_api_calls = unknown

    @classmethod
    def _api_call_known(cls, call: str, known: set) -> bool:
        if call in known:
            return True
        normalized = call.replace("-", "_")
        if normalized in known:
            return True
        leaf = normalized.split(".")[-1]
        if leaf in known:
            return True
        # `pdb.gimp_image_list` / `gimp.image_list` -> `pdb_gimp_image_list`
        joined = "_".join(normalized.split("."))
        if joined in known:
            return True
        # `gimp.image_list` -> `gimp_image_list` (matches catalog spelling).
        if normalized.startswith(("gimp.", "pdb.")):
            remainder = "_".join(normalized.split(".")[1:])
            return remainder in known
        return False

    @staticmethod
    def _is_plain_builtin(name: str) -> bool:
        if "." in name:
            return False
        try:
            return name in dir(__builtins__) or name in {
                "print", "range", "len", "str", "int", "float", "list", "dict",
                "set", "tuple", "bool", "isinstance", "issubclass", "hasattr",
                "sum", "min", "max", "abs", "round", "enumerate", "zip", "sorted",
                "map", "filter", "any", "all", "format", "repr", "type", "id",
                "Exception", "ValueError", "TypeError", "RuntimeError", "None",
                "True", "False",
            }
        except Exception:  # noqa: BLE001 - unknown builtins namespace; treat as unknown
            return False


def should_ask_confirmation(mode: str, report: SafetyReport) -> bool:
    """Map safety mode -> whether user confirmation is required."""
    if mode == "auto":
        return False
    if mode == "dry-run":
        return True
    # preview / strict always confirm; strict additionally refuses unsafe scripts.
    if mode == "strict" and not report.passed:
        return True
    return True
