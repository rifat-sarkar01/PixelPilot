"""Unit tests for the safety validator."""


from pixelpilot.codegen import SafetyValidator, extract_code_block
from pixelpilot.codegen.validator import should_ask_confirmation


def test_extract_fenced_block():
    text = "Here you go:\n```python\nprint('hi')\n```\nEnjoy!"
    assert extract_code_block(text) == "print('hi')"


def test_extract_accepts_plain_python():
    code = "print('hi')\n"
    assert extract_code_block(code) == "print('hi')"


def test_extract_rejects_non_python():
    assert extract_code_block("No code here, just prose.") is None


def test_extract_tolerates_junk_on_fence_line():
    text = "```python\nprint('hi')\n```"
    assert extract_code_block(text) == "print('hi')"


def test_extract_unterminated_fence():
    text = "```python\nprint('hi')\nprint('still going')\n"
    assert extract_code_block(text) == "print('hi')\nprint('still going')"


def test_extract_unterminated_fence_non_python_returns_none():
    text = "```python\njust prose without code"
    assert extract_code_block(text) is None


def test_good_script_passes():
    script = '''from gimpfu import *

def run():
    image = gimp.image_list()[0]
    drawable = image.active_drawable
    pdb.gimp_image_undo_group_start(image)
    try:
        pdb.plug_in_gauss(image, drawable, 5.0, 5.0, 0)
        pdb.gimp_displays_flush()
    finally:
        pdb.gimp_image_undo_group_end(image)

run()
'''
    report = SafetyValidator(editor="gimp").validate(script)
    assert report.passed, report.errors
    assert report.api_calls_checked > 0


def test_forbidden_os_import_fails():
    script = "import os\nos.listdir('/')\n"
    report = SafetyValidator().validate(script)
    assert not report.passed
    assert any("os" in e for e in report.errors)


def test_forbidden_subprocess_fails():
    script = "import subprocess\nsubprocess.run(['ls'])\n"
    report = SafetyValidator().validate(script)
    assert not report.passed
    assert any("subprocess" in e.lower() for e in report.errors)


def test_forbidden_eval_fails():
    report = SafetyValidator().validate("result = eval('1+1')\n")
    assert not report.passed


def test_forbidden_open_fails():
    report = SafetyValidator().validate("f = open('/etc/passwd', 'w')\n")
    assert not report.passed


def test_network_pattern_fails():
    report = SafetyValidator().validate(
        "import urllib.request\nurllib.request.urlopen('http://x')\n"
    )
    assert not report.passed


def test_syntax_error_fails():
    report = SafetyValidator().validate("def broken(:\n")
    assert not report.passed
    assert any("Syntax" in e for e in report.errors)


def test_unknown_api_warning():
    script = "pdb.gimp_fake_hallucinated_procedure(image)\n"
    report = SafetyValidator(editor="gimp").validate(script)
    assert report.passed  # warnings only
    assert any("gimp_fake_hallucinated_procedure" in c for c in report.unknown_api_calls)


def test_krita_known_api_accepted():
    script = '''from krita import Krita

def run():
    app = Krita.instance()
    doc = app.activeDocument()
    node = doc.activeNode()
    node.setOpacity(0.7)
    doc.refreshProjection()

run()
'''
    report = SafetyValidator(editor="krita").validate(script)
    assert report.passed, report.errors


def test_max_lines_enforced():
    script = "\n".join(f"x = {i}" for i in range(600))
    report = SafetyValidator(max_script_lines=500).validate(script)
    assert not report.passed
    assert any("500 lines" in e for e in report.errors)


def test_confirmation_modes():
    passed = SafetyReportStub()
    assert should_ask_confirmation("auto", passed) is False
    assert should_ask_confirmation("preview", passed) is True
    assert should_ask_confirmation("dry-run", passed) is True
    assert should_ask_confirmation("strict", passed) is True


def test_stdlib_calls_from_allowed_modules_are_not_flagged_as_hallucinations():
    # math/random/colorsys/json/re/struct are explicitly permitted imports (see
    # ALLOWED_IMPORTS) - the API-hallucination check only has a catalog of
    # GIMP/Krita procedures, so it previously flagged every single call on
    # these modules (math.cos, math.radians, ...) as "possible hallucination",
    # burying real hallucinations in noise.
    script = (
        "import math\n"
        "angle = math.radians(25)\n"
        "x = math.cos(angle)\n"
        "y = math.sin(angle)\n"
    )
    report = SafetyValidator(editor="gimp").validate(script)
    assert report.warnings == []
    assert report.unknown_api_calls == []


def test_genuinely_unknown_pdb_call_is_still_flagged():
    script = "pdb.gimp_totally_made_up_call(1, 2, 3)\n"
    report = SafetyValidator(editor="gimp").validate(script)
    assert any("gimp_totally_made_up_call" in w for w in report.warnings)
    assert any("gimp_totally_made_up_call" in c for c in report.unknown_api_calls)


class SafetyReportStub:
    passed = True
