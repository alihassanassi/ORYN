"""research/sources/ollama_registry.py — Local Ollama model registry monitor.

Watches local Ollama for installed models and compares against
a curated list of notable new releases. Surfaces upgrade recommendations.
"""
from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

# Models worth flagging when they appear in the Ollama library.
# Update this list as new notable models are released.
_NOTABLE_MODELS = [
    "qwen3:32b", "qwen3:72b",
    "gemma3:27b", "gemma3:9b",
    "phi4:14b", "phi4-mini:latest",
    "llama4:scout", "llama4:maverick",
    "deepseek-r2:14b", "deepseek-r2:32b",
    "mistral-large:latest",
    "codestral:latest",
]

# VRAM estimates (GB) for sizing check
_VRAM_MAP = {
    "3b": 2.5, "7b": 4.5, "8b": 5.0, "9b": 6.0,
    "12b": 7.5, "14b": 9.0, "27b": 16.0, "32b": 20.0,
    "70b": 40.0, "72b": 45.0,
    "mini": 3.0, "scout": 8.0, "maverick": 24.0,
}


class OllamaRegistrySource:
    """Detects new notable Ollama models not yet installed locally."""

    def __init__(self):
        self._seen: set[str] = set()
        self._local_cache: set[str] = set()

    def _get_local_models(self) -> set[str]:
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/tags",
                headers={"User-Agent": "JARVIS/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
            return {m["name"] for m in data.get("models", [])}
        except Exception:
            return self._local_cache

    def fetch(self) -> list[dict]:
        local = self._get_local_models()
        self._local_cache = local
        items: list[dict] = []

        for model in _NOTABLE_MODELS:
            if model in local:
                continue  # already installed
            if model in self._seen:
                continue  # already reported
            self._seen.add(model)

            # Estimate VRAM
            model_lower = model.lower()
            vram = 99.0
            for tag, gb in sorted(_VRAM_MAP.items(), key=lambda x: len(x[0]), reverse=True):
                if tag in model_lower:
                    vram = gb
                    break

            # Only surface models that fit in 16GB - 4GB Chatterbox headroom
            fits = vram <= 12.0
            base = model.split(":")[0]
            items.append({
                "type":            "llm_release",
                "title":           model,
                "severity":        "info",
                "details":         f"New model available: {model}. VRAM: ~{vram}GB. {'Fits hardware.' if fits else 'Exceeds available headroom.'}",
                "url":             f"https://ollama.com/library/{base}",
                "affects_targets": False,
                "raw":             {
                    "model":        model,
                    "vram_gb":      vram,
                    "fits":         fits,
                    "install_cmd":  f"ollama pull {model}" if fits else None,
                },
            })
        return items
