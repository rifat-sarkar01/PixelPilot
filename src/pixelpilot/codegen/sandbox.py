"""Runtime sandboxing (implementation_plan.md §10.2 Layer 5).

Executes generated scripts in a restricted environment:
* a pruned builtins dict (no eval/exec/open/import machinery)
* a watchdog timeout that works cross-platform (threading-based, Windows-safe)
* no implicit filesystem or network access
"""

from __future__ import annotations

import builtins
import threading
import time
from typing import Any


class ScriptTimeout(TimeoutError):
    """Raised when a script exceeds its configured execution time."""


class ScriptExecutionError(RuntimeError):
    """Raised when the sandboxed script raises an exception."""


# Builtins that are safe for editor scripts.
_SAFE_BUILTIN_NAMES = {
    "print",
    "len",
    "range",
    "str",
    "int",
    "float",
    "list",
    "dict",
    "set",
    "tuple",
    "bool",
    "isinstance",
    "issubclass",
    "hasattr",
    "getattr",
    "setattr",
    "delattr",
    "sum",
    "min",
    "max",
    "abs",
    "round",
    "enumerate",
    "zip",
    "sorted",
    "map",
    "filter",
    "any",
    "all",
    "format",
    "repr",
    "type",
    "id",
    "chr",
    "ord",
    "hex",
    "oct",
    "bin",
    "divmod",
    "pow",
    "complex",
    "bytes",
    "bytearray",
    "memoryview",
    "slice",
    "iter",
    "next",
    "reversed",
    "Exception",
    "ValueError",
    "TypeError",
    "RuntimeError",
    "KeyError",
    "IndexError",
    "AttributeError",
    "NameError",
    "ZeroDivisionError",
    "OverflowError",
    "NotImplementedError",
    "ArithmeticError",
    "LookupError",
    "StopIteration",
}


def _safe_builtins() -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for name in _SAFE_BUILTIN_NAMES:
        if hasattr(builtins, name):
            safe[name] = getattr(builtins, name)
    # Keep common non-dangerous constants.
    safe["None"] = None
    safe["True"] = True
    safe["False"] = False
    return safe


def _exec_with_timeout(code: str, namespace: dict[str, Any], timeout: float) -> None:
    finished = threading.Event()
    result_box: dict[str, Any] = {}

    def _run() -> None:
        try:
            exec(compile(code, "<pixelpilot-sandbox>", "exec"), namespace)  # noqa: S102 - sandbox core
        except BaseException as exc:  # noqa: BLE001 - must observe *all* failures
            result_box["error"] = exc
        finally:
            finished.set()

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    if not finished.wait(timeout=timeout):
        raise ScriptTimeout(f"Script exceeded the {timeout:.0f}s execution timeout.")
    if "error" in result_box:
        exc = result_box["error"]
        raise ScriptExecutionError(f"{type(exc).__name__}: {exc}") from exc


def run_sandboxed(
    code: str,
    timeout: float = 60.0,
    extra_globals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute ``code`` in a restricted namespace.

    Returns a dict with ``execution_time`` (seconds) and ``result``. Raises
    :class:`ScriptTimeout` or :class:`ScriptExecutionError` on failure.
    """
    namespace: dict[str, Any] = {"__builtins__": _safe_builtins()}
    if extra_globals:
        namespace.update(extra_globals)

    start = time.monotonic()
    _exec_with_timeout(code, namespace, timeout)
    elapsed = time.monotonic() - start
    return {"execution_time": elapsed, "result": None}
