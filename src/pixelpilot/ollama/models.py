"""Model management and VRAM-aware auto-selection.

Implements the auto-selection logic from ``implementation_plan.md`` §2.6:
1. Query GPU VRAM (pynvml or nvidia-smi)
2. Query installed models
3. Pick the largest code model that fits in VRAM
4. If VRAM remains, pick the largest vision model
5. If no vision model fits, disable vision feedback
6. If no models installed, fall back to configured defaults
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

from pixelpilot.config import Settings

# Model families recognised by PixelPilot, ordered best -> acceptable.
CODE_MODEL_FAMILIES: list[str] = [
    "qwen2.5-coder",
    "deepseek-coder",
    "codestral",
    "starcoder",
    "llama3.1",
    "llama3.3",
    "qwen2.5",
    "qwen3-coder",
    "llama3",
    "mistral",
    "phi3",
    "phi4",
]

VISION_MODEL_FAMILIES: list[str] = [
    "llama3.2-vision",
    "llava",
    "moondream",
    "gemma3",
    "minicpm-v",
]

EMBED_MODEL_PREFERENCE: list[str] = [
    "nomic-embed-text",
    "mxbai-embed-large",
    "all-minilm",
    "bge-m3",
    "snowflake-arctic-embed",
]


@dataclass
class ModelInfo:
    name: str
    size: int = 0  # bytes on disk
    digest: str = ""
    modified_at: str = ""
    details: dict | None = None

    @classmethod
    def from_ollama_tags(cls, raw: dict) -> ModelInfo:
        return cls(
            name=raw.get("name", ""),
            size=raw.get("size", 0),
            digest=raw.get("digest", ""),
            modified_at=raw.get("modified_at", ""),
            details=raw.get("details"),
        )

    @property
    def short_name(self) -> str:
        return self.name.split(":", 1)[0]

    @property
    def tag(self) -> str:
        return self.name.split(":", 1)[1] if ":" in self.name else ""

    @property
    def size_gb(self) -> float:
        return self.size / (1024 ** 3)

    def belongs_to_family(self, families: list[str]) -> bool:
        short = self.short_name.lower()
        return any(short == fam or short.startswith(fam.split(".")[0]) for fam in families)


def list_installed_models(client) -> list[ModelInfo]:
    """Return installed models from ``GET /api/tags``."""
    tags = client.list_models()
    return [ModelInfo.from_ollama_tags(raw) for raw in tags]


def estimate_vram_gb(parameter_size_gb: float, quant_level: str = "") -> float:
    """Rough VRAM estimate from parameter size and quantization level."""
    quant_multiplier = {
        "q2": 0.45,
        "q3": 0.55,
        "q4": 0.65,
        "q5": 0.75,
        "q6": 0.85,
        "q8": 1.0,
        "f16": 1.25,
    }
    for key, mult in quant_multiplier.items():
        if key in quant_level.lower():
            return parameter_size_gb * mult
    # Unknown quant - assume Q4 ~ 60-65% of f16 size.
    return parameter_size_gb * 0.65


def detect_gpu_vram_gb() -> float | None:
    """Return total VRAM in GB, or None if no NVIDIA GPU / tooling is available."""
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        pynvml.nvmlShutdown()
        return mem.total / (1024 ** 3)
    except Exception:  # noqa: S110, BLE001 - pynvml optional; never crash hardware detection
        pass

    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    try:
        out = subprocess.run(
            [nvidia_smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode != 0:
            return None
        return float(out.stdout.strip().splitlines()[0]) / 1024.0
    except Exception:  # noqa: BLE001 - fallback path must never raise
        return None


def _pick_largest(models: list[ModelInfo], families: list[str]) -> ModelInfo | None:
    candidates = [m for m in models if m.belongs_to_family(families)]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.size)


def _pick_for_vram(
    models: list[ModelInfo],
    families: list[str],
    vram_gb: float | None,
    fraction: float = 0.8,
) -> ModelInfo | None:
    candidates = [m for m in models if m.belongs_to_family(families)]
    if not candidates:
        return None
    if vram_gb is None:
        return max(candidates, key=lambda m: m.size)
    budget = vram_gb * fraction
    fitting = [m for m in candidates if estimate_vram_gb(m.size_gb, m.tag) <= budget]
    if fitting:
        return max(fitting, key=lambda m: m.size)
    return min(candidates, key=lambda m: m.size)


@dataclass
class ModelRecommendation:
    code_model: str = ""
    vision_model: str = ""
    embed_model: str = "nomic-embed-text"
    vram_gb: float | None = None
    vision_enabled: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def as_dict(self) -> dict:
        return {
            "code_model": self.code_model,
            "vision_model": self.vision_model,
            "embed_model": self.embed_model,
            "vision_enabled": self.vision_enabled,
        }


def recommend_models(models: list[ModelInfo], settings: Settings) -> ModelRecommendation:
    """Recommend the best installed models for the available hardware."""
    if not settings.ollama.auto_select_models:
        return ModelRecommendation(
            code_model=settings.ollama.code_model,
            vision_model=settings.ollama.vision_model if settings.feedback.vision_enabled else "",
            embed_model=settings.ollama.embed_model,
            vision_enabled=settings.feedback.vision_enabled,
        )

    vram = detect_gpu_vram_gb()
    rec = ModelRecommendation(vram_gb=vram)

    code = _pick_for_vram(models, CODE_MODEL_FAMILIES, vram, fraction=0.5)
    if code is not None:
        rec.code_model = code.name
    else:
        code = _pick_largest(models, CODE_MODEL_FAMILIES) or _pick_largest(models, [])
        rec.code_model = code.name if code else settings.ollama.code_model

    vision = _pick_for_vram(models, VISION_MODEL_FAMILIES, vram, fraction=0.35)
    if vision is not None:
        rec.vision_model = vision.name
        rec.vision_enabled = settings.feedback.vision_enabled
    else:
        # No fitting vision model - disable vision feedback, as per plan §2.6 step 5.
        rec.vision_enabled = False
        rec.notes.append("No vision model that fits in VRAM - text-only feedback enabled.")

    embed = _pick_largest(models, EMBED_MODEL_PREFERENCE) or next(
        (m for m in models if "embed" in m.short_name), None
    )
    if embed is not None:
        rec.embed_model = embed.name

    return rec
