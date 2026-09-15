"""Regression checks for the custom Ollama Modelfiles."""

from pixelpilot.ollama.modelfiles import vision_modelfile_text


def test_vision_model_is_built_on_the_multimodal_llava_base():
    assert vision_modelfile_text().startswith("FROM llava:13b\n")
