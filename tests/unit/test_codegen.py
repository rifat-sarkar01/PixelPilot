"""Unit tests for the IR and code generators."""

from pixelpilot.codegen import GimpCodeGen, KritaCodeGen
from pixelpilot.codegen.ir import Operation, ScriptPlan, parse_ir


def _gimp_plan() -> ScriptPlan:
    plan = ScriptPlan(editor="gimp", title="Blur + new layer")
    plan.add(Operation("layer.new", {"name": "Copy", "opacity": 70, "blend_mode": "screen"}))
    plan.add(Operation("filter.gaussian_blur", {"radius": 5.0}))
    return plan


def test_ir_roundtrip():
    plan = _gimp_plan()
    restored = parse_ir(plan.to_json())
    assert restored.editor == "gimp"
    assert len(restored.operations) == 2
    assert restored.operations[0].type == "layer.new"
    assert restored.operations[0].params["blend_mode"] == "screen"


def test_gimp_codegen_renders_operations():
    script = GimpCodeGen().render(_gimp_plan())
    assert "gimp_layer_new" in script
    assert "plug_in_gauss" in script
    assert "gimp_image_undo_group_start" in script
    assert "gimp_displays_flush" in script


def test_gimp_codegen_unknown_op_is_commented():
    plan = ScriptPlan(editor="gimp")
    plan.add(Operation("totally.unknown_op", {"x": 1}))
    script = GimpCodeGen().render(plan)
    assert "[unhandled] totally.unknown_op" in script


def test_krita_codegen_renders_operations():
    plan = ScriptPlan(editor="krita", title="Glow")
    plan.add(Operation("filter.gaussian_blur", {"radius": 20}))
    plan.add(Operation("layer.set_blend_mode", {"mode": "screen"}))
    script = KritaCodeGen().render(plan)
    assert "app.filters()['gaussian blur']" in script
    assert "setBlendingMode('screen')" in script
    assert "refreshProjection()" in script


def test_krita_scale():
    plan = ScriptPlan(editor="krita")
    plan.add(Operation("transform.scale", {"width": 800, "height": 600}))
    script = KritaCodeGen().render(plan)
    assert "doc.scaleImage(800, 600, 1)" in script
