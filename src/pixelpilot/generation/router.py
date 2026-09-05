"""Intent router — classifies a user utterance as 'edit' or 'generate'.

No LLM call, no I/O. Pure text classification via curated keyword sets.

Design principles:
- EDIT_SIGNALS win on ANY match → the existing scripting path can never be
  accidentally bypassed by an ambiguous request.
- A generate intent requires a clear generate-verb + object-noun with zero
  edit signals.
- Default is 'edit' — unknown utterances fall through to the existing path.
"""

from __future__ import annotations

import re
from typing import Literal


class IntentRouter:
    """Classify user text as ``'edit'`` or ``'generate'``.

    Usage::

        router = IntentRouter()
        intent = router.classify("draw a red car")  # -> "generate"
        intent = router.classify("blur this photo")  # -> "edit"
    """

    # Verbs that strongly suggest scratch generation
    GENERATE_VERBS: frozenset[str] = frozenset({
        "draw", "paint", "illustrate", "sketch", "create", "make",
        "generate", "render", "design", "compose", "build",
        "produce", "fabricate", "construct",
    })

    # Nouns/concepts that appear in generation requests
    GENERATE_NOUNS: frozenset[str] = frozenset({
        # vehicles
        "car", "truck", "bus", "bike", "bicycle", "motorcycle", "train",
        "plane", "airplane", "boat", "ship", "rocket",
        # nature
        "tree", "forest", "flower", "mountain", "river", "ocean", "sky",
        "sun", "moon", "star", "cloud", "rainbow", "grass", "beach",
        "sunset", "sunrise", "waterfall", "lake", "volcano", "desert",
        # buildings
        "house", "building", "castle", "bridge", "tower", "city",
        # people / creatures
        "person", "man", "woman", "child", "face", "animal",
        "dog", "cat", "bird", "fish", "dragon", "monster",
        # abstract / composition
        "landscape", "scene", "background", "drawing", "illustration",
        "logo", "icon", "shape", "character", "portrait", "map",
        # primitives (explicit draw requests)
        "circle", "square", "triangle", "rectangle", "polygon", "star",
    })

    # Phrases / words that strongly indicate the user is working on an
    # EXISTING image.  Any match here locks the intent to 'edit'.
    EDIT_SIGNALS: frozenset[str] = frozenset({
        # direct references to existing content
        "this", "the photo", "the image", "the picture", "the canvas",
        "my photo", "my image", "existing", "current", "open",
        # editing operations
        "blur", "sharpen", "crop", "resize", "rotate", "flip",
        "brightness", "contrast", "saturation", "hue", "exposure",
        "filter", "adjust", "fix", "correct", "enhance", "retouch",
        "remove", "erase", "delete", "cut", "mask",
        "select", "layer", "layers", "opacity", "blend",
        "color balance", "levels", "curves", "noise", "denoise",
        "convert", "grayscale", "black and white", "desaturate",
        "undo", "redo", "clone", "heal", "patch",
        # photo-specific
        "photo", "photograph", "picture", "portrait", "image",
        "jpeg", "jpg", "png", "tiff", "raw",
    })

    # Multi-word edit signals (checked before tokenisation)
    _EDIT_PHRASES: tuple[str, ...] = (
        "the photo", "the image", "the picture", "the canvas",
        "my photo", "my image", "color balance", "black and white",
    )

    def classify(self, user_text: str) -> Literal["edit", "generate"]:
        """Return ``'generate'`` only when the intent is unambiguously generative.

        Falls back to ``'edit'`` on any ambiguity.
        """
        lowered = user_text.lower()

        # 1. Check multi-word edit phrases first (before tokenising)
        for phrase in self._EDIT_PHRASES:
            if phrase in lowered:
                return "edit"

        tokens = set(re.findall(r"[a-z]+", lowered))

        # 2. Any edit signal → edit wins immediately
        if tokens & self.EDIT_SIGNALS:
            return "edit"

        # 3. Require both a generate verb AND an object noun
        has_verb = bool(tokens & self.GENERATE_VERBS)
        has_noun = bool(tokens & self.GENERATE_NOUNS)

        if has_verb and has_noun:
            return "generate"

        # 4. Default
        return "edit"

    def explain(self, user_text: str) -> dict:
        """Return a debug dict explaining why a classification was made.

        Useful for unit tests and CLI ``/status`` output.
        """
        lowered = user_text.lower()
        tokens = set(re.findall(r"[a-z]+", lowered))

        # phrase hits
        phrase_hits = [p for p in self._EDIT_PHRASES if p in lowered]

        edit_hits = sorted(tokens & self.EDIT_SIGNALS)
        verb_hits = sorted(tokens & self.GENERATE_VERBS)
        noun_hits = sorted(tokens & self.GENERATE_NOUNS)

        intent = self.classify(user_text)
        return {
            "intent": intent,
            "edit_phrase_hits": phrase_hits,
            "edit_signal_hits": edit_hits,
            "generate_verb_hits": verb_hits,
            "generate_noun_hits": noun_hits,
        }
