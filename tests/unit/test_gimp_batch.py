from __future__ import annotations

import subprocess
from pathlib import Path

from pixelpilot.bridge.gimp_batch import apply_python_edit


def test_apply_python_edit_runs_short_batch_expression(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "input.png"
    output_path = tmp_path / "output.png"
    input_path.write_bytes(b"input")
    seen: dict[str, list[str]] = {}

    monkeypatch.setattr("pixelpilot.bridge.gimp_batch.find_gimp_binary", lambda _: "gimp.exe")

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        output_path.write_bytes(b"output")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("pixelpilot.bridge.gimp_batch.subprocess.run", fake_run)

    result = apply_python_edit(
        input_path,
        output_path,
        "from gimpfu import *\nimage = gimp.image_list()[0]",
    )

    assert result == output_path
    assert seen["cmd"][:3] == ["gimp.exe", "-i", str(input_path)]
    assert "--batch-interpreter=python-fu-eval" in seen["cmd"]
    expression = seen["cmd"][seen["cmd"].index("-b") + 1]
    assert expression.startswith("exec(compile(open(")
    assert "gimp.image_list" not in expression
