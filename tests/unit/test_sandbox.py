"""Unit tests for the runtime sandbox."""

import pytest

from pixelpilot.codegen.sandbox import (
    ScriptExecutionError,
    ScriptTimeout,
    run_sandboxed,
)


def test_plain_script_runs():
    result = run_sandboxed("x = 2 + 3\n", timeout=5)
    assert "execution_time" in result


def test_dangerous_builtin_blocked():
    with pytest.raises(ScriptExecutionError):
        run_sandboxed("result = eval('1+1')\n", timeout=5)


def test_import_machinery_blocked():
    with pytest.raises(ScriptExecutionError):
        run_sandboxed("import os\n", timeout=5)


def test_timeout_enforced():
    with pytest.raises(ScriptTimeout):
        run_sandboxed("while True:\n    pass\n", timeout=1)


def test_extra_globals_injected():
    result = run_sandboxed("total = compute(1, 2)\n", timeout=5,
                           extra_globals={"compute": lambda a, b: a + b})
    assert result["result"] is None
