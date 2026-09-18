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

# Calls rooted at these modules are ordinary, well-known standard-library calls
# (explicitly permitted by ALLOWED_IMPORTS above) - the API-hallucination check
# below only has a catalog of GIMP/Krita procedures, so it has no way to
# recognize e.g. `math.cos` as legitimate and previously flagged every such
# call as an "unknown API call", drowning real hallucinations in noise.
SAFE_STDLIB_MODULES = ALLOWED_IMPORTS - {"gimp", "gimpfu", "krita", "Krita"}

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
    # Python 3.6+ f-strings are forbidden in GIMP Python-Fu (Python 2.7).
    # The prefix must begin a string token.  The previous pattern treated any
    # prose ending in ``f`` (for example ``background of "the car"``) as an
    # f-string, causing otherwise valid scripts to be rejected.
    re.compile(r"(?<![A-Za-z0-9_])(?:[fF][rR]?|[rR][fF])(?:['\"]|\"\"\"|''')"),
]

FENCED_CODE_RE = re.compile(
    r"```(?:python|py|gimp|krita)?[^\n]*\n(.*?)```", re.DOTALL
)

# ---------------------------------------------------------------------------
# Auto-fixer: repair common LLM mistakes before validation
# ---------------------------------------------------------------------------

# Map of hallucinated API names → correct GIMP PDB names.
# Keys are the wrong call as the LLM writes it (without ``pdb.`` prefix);
# values are the correct PDB procedure name.
_API_HALLUCINATION_FIXES: dict[str, str] = {
    "plug_in_fuzzy_select": "gimp_fuzzy_select",
    "plug_in_fuzzy_select_by_color": "gimp_by_color_select",
    "gimp_image_get_pixel": "gimp_drawable_get_pixel",
    "gimp_layer_get_alpha": "gimp_layer_add_alpha",
    "plug_in_color_select": "gimp_by_color_select",
    "gimp_image_select_by_color": "gimp_by_color_select",
}

# Pre-compiled regex for each hallucinated name (matches pdb.XXX or bare XXX).
_API_FIX_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(wrong) + r"\b"), correct)
    for wrong, correct in _API_HALLUCINATION_FIXES.items()
]


class ScriptAutoFixer:
    """Repair common LLM mistakes in generated scripts.

    Runs **before** safety validation so that trivially fixable issues
    (f-strings, hallucinated API names) don't trigger a full re-generation
    round-trip through the LLM.  Every fix is logged so the user sees what
    was changed.
    """

    def auto_fix(self, script: str) -> tuple[str, list[str]]:
        """Return ``(fixed_script, list_of_fix_descriptions)``.

        If nothing was changed, the original script is returned unmodified.
        """
        fixes: list[str] = []
        result = script

        # 1. Convert f-strings to %-formatting
        result, fstring_fixes = self._fix_fstrings(result)
        fixes.extend(fstring_fixes)

        # 2. Fix hallucinated API names
        result, api_fixes = self._fix_api_names(result)
        fixes.extend(api_fixes)

        return result, fixes

    # ---------------------------------------------------------------- f-strings

    @staticmethod
    def _fix_fstrings(script: str) -> tuple[str, list[str]]:
        """Replace f-strings with %-formatting (Python 2.7 compatible).

        Uses AST inspection to find f-strings, then rewrites the source
        lines.  Falls back to a regex approach when AST parsing fails.
        """
        try:
            tree = ast.parse(script)
        except SyntaxError:
            return script, []

        fstring_nodes: list[ast.JoinedStr] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                fstring_nodes.append(node)

        if not fstring_nodes:
            return script, []

        # Regex replacement: match f"..." / f'...' and their raw variants.
        # This is intentionally broad — the AST already confirmed f-strings
        # exist, so we only need a best-effort text rewrite.
        fstring_re = re.compile(
            r'(?<![A-Za-z0-9_])([fF][rR]?|[rR][fF])'
            r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"[^"\n]*"|\'[^\'\n]*\')'
        )

        count = 0

        def _rewrite(m: re.Match) -> str:
            nonlocal count
            raw_body = m.group(2)
            # Determine quote style
            if raw_body.startswith('"""') or raw_body.startswith("'''"):
                q = raw_body[:3]
                body = raw_body[3:-3]
            else:
                q = raw_body[0]
                body = raw_body[1:-1]

            # Replace {expr} with %s and collect expressions
            exprs: list[str] = []
            brace_re = re.compile(r'\{([^{}]+)\}')

            def _sub_expr(em: re.Match) -> str:
                exprs.append(em.group(1).strip())
                return "%s"

            new_body = brace_re.sub(_sub_expr, body)

            count += 1
            if len(exprs) == 1:
                return f"{q}{new_body}{q} % ({exprs[0]},)"
            elif exprs:
                args = ", ".join(exprs)
                return f"{q}{new_body}{q} % ({args},)"
            else:
                # f-string with no interpolations — just drop the f prefix
                return f"{q}{new_body}{q}"

        result = fstring_re.sub(_rewrite, script)
        if count > 0:
            return result, [f"converted {count} f-string(s) to %-formatting (Python 2.7)"]
        return script, []

    # --------------------------------------------------------- API name fixes

    @staticmethod
    def _fix_api_names(script: str) -> tuple[str, list[str]]:
        """Replace hallucinated GIMP API names with correct equivalents."""
        fixes: list[str] = []
        result = script
        for pattern, correct in _API_FIX_PATTERNS:
            if pattern.search(result):
                result = pattern.sub(correct, result)
                wrong = pattern.pattern.strip("\\b")
                fixes.append(f"replaced {wrong} → {correct}")
        return result, fixes


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
        # The bundled catalog covers the generated helpers and common APIs.
        # When a connected GIMP supplies its PDB, merge it rather than replacing
        # these entries: the bridge helpers are also executable API surface.
        self.api_catalog = known_api_names(editor) | set(api_catalog or ())

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

    def _collect_local_definitions(self, tree: ast.AST) -> set[str]:
        local_defs: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local_defs.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        local_defs.add(target.id)
            elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
                local_defs.add(node.target.id)
        return local_defs

    def _check_api_calls(self, tree: ast.AST, report: SafetyReport) -> None:
        calls = self._collect_api_calls(tree)
        report.api_calls_checked = len(calls)
        known = self.api_catalog
        local_defs = self._collect_local_definitions(tree)
        unknown: list[str] = []
        for call in calls:
            # Bare calls like `print`, `str`, `range` are Python builtins, not editor APIs.
            if self._is_plain_builtin(call):
                continue
            # Locally defined functions / classes / callable variables in the script
            if call in local_defs:
                continue
            # `math.cos`, `random.randint`, etc. are ordinary stdlib calls from an
            # explicitly allowed import, not GIMP/Krita API surface - nothing to
            # look up in the editor procedure catalog.
            root = call.split(".", 1)[0]
            if root in SAFE_STDLIB_MODULES:
                continue
            if not self._api_call_known(call, known):
                unknown.append(call)
        for call in unknown:
            message = f"Unknown API call (possible hallucination): {call}()"
            # A made-up call on the live editor API is not merely advisory:
            # executing it can leave a partially drawn canvas behind.  Keep
            # warnings for other unfamiliar callables, but block PDB/GIMP
            # calls until the model uses a known procedure.
            if call.startswith(("pdb.", "gimp.")):
                report.errors.append(message)
            else:
                report.warnings.append(message)
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
