"""Unit tests for generation/router.py — IntentRouter."""

from __future__ import annotations

import pytest

from pixelpilot.generation.router import IntentRouter


@pytest.fixture
def router() -> IntentRouter:
    return IntentRouter()


# ---------------------------------------------------------------------------
# Generate intents
# ---------------------------------------------------------------------------

class TestGenerateIntents:
    GENERATE_CASES = [
        "draw a car",
        "draw a red car",
        "paint a tree",
        "illustrate a house",
        "sketch a dragon",
        "create a landscape",
        "generate a scene",
        "render a sunset",
        "design a logo",
        "make a tree",
        "build a city",
        "draw a circle",
        "draw a dog",
        "draw a cat",
        "draw a person",
        "illustrate a mountain landscape",
        "create a background with clouds",
        "make a cartoon face",
    ]

    @pytest.mark.parametrize("text", GENERATE_CASES)
    def test_classified_as_generate(self, router, text):
        assert router.classify(text) == "generate", f"Expected 'generate' for: {text!r}"


# ---------------------------------------------------------------------------
# Edit intents
# ---------------------------------------------------------------------------

class TestEditIntents:
    EDIT_CASES = [
        # Direct edit operations
        "blur this image",
        "sharpen the photo",
        "crop the picture",
        "resize the canvas",
        "rotate 90 degrees",
        "flip horizontally",
        "adjust the brightness",
        "increase contrast",
        "fix the saturation",
        "remove the background",
        "erase that area",
        "select all layers",
        "desaturate the image",
        # References to existing content
        "make this photo brighter",
        "the image is too dark",
        "convert my photo to black and white",
        # Edit operations mixed with nouns that appear in generate sets
        "draw a circle on this photo",     # "this" is an edit signal
        "add a tree to the image",         # "the image" is an edit signal
        "blur the existing background",    # "existing" is an edit signal
        "make the current layer transparent",
        # Ambiguous — default to edit
        "make it darker",
        "fix the colors",
        "undo that",
    ]

    @pytest.mark.parametrize("text", EDIT_CASES)
    def test_classified_as_edit(self, router, text):
        assert router.classify(text) == "edit", f"Expected 'edit' for: {text!r}"


# ---------------------------------------------------------------------------
# Default fallback
# ---------------------------------------------------------------------------

class TestDefaultFallback:
    AMBIGUOUS_CASES = [
        "",                        # empty string
        "hello",                   # no signals at all
        "something",               # no signals at all
        "make it better",          # no noun
        "I need help",
    ]

    @pytest.mark.parametrize("text", AMBIGUOUS_CASES)
    def test_defaults_to_edit(self, router, text):
        assert router.classify(text) == "edit", f"Expected default 'edit' for: {text!r}"


# ---------------------------------------------------------------------------
# Edit signal wins over generate signals (safety property)
# ---------------------------------------------------------------------------

class TestEditWinsOnAmbiguity:
    def test_draw_on_this_photo(self, router):
        """'this' is an edit signal; the whole request should be 'edit'."""
        assert router.classify("draw a circle on this photo") == "edit"

    def test_create_with_existing(self, router):
        assert router.classify("create a tree in the existing image") == "edit"

    def test_generate_noun_but_photo_referenced(self, router):
        assert router.classify("add a car to my photo") == "edit"

    def test_blur_with_draw_noun(self, router):
        assert router.classify("blur the car in the photo") == "edit"


# ---------------------------------------------------------------------------
# Case-insensitivity
# ---------------------------------------------------------------------------

class TestCaseInsensitive:
    def test_uppercase_generate(self, router):
        assert router.classify("DRAW A TREE") == "generate"

    def test_mixed_case_edit(self, router):
        assert router.classify("BLUR This Image") == "edit"

    def test_title_case_generate(self, router):
        assert router.classify("Draw A Car") == "generate"


# ---------------------------------------------------------------------------
# explain() debug output
# ---------------------------------------------------------------------------

class TestExplain:
    def test_explain_generate(self, router):
        result = router.explain("draw a tree")
        assert result["intent"] == "generate"
        assert "draw" in result["generate_verb_hits"]
        assert "tree" in result["generate_noun_hits"]
        assert not result["edit_signal_hits"]

    def test_explain_edit(self, router):
        result = router.explain("blur this photo")
        assert result["intent"] == "edit"
        assert "blur" in result["edit_signal_hits"]

    def test_explain_phrase_hit(self, router):
        result = router.explain("make the photo brighter")
        assert result["intent"] == "edit"
        assert "the photo" in result["edit_phrase_hits"]
