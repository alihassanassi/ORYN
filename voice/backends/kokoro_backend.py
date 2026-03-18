"""voice/backends/kokoro_backend.py — Kokoro ONNX neural TTS backend.

Requires: pip install kokoro-onnx
Model files: kokoro-v0_19.onnx + voices.bin (or voices-v1.0.bin)
Download: https://huggingface.co/hexgrad/Kokoro-82M/tree/main
Place both files in config.KOKORO_MODEL_DIR (default: C:\\kokoro).

Available voice IDs (kokoro-onnx v0.19):
  bm_george   — British Male George   (default JARVIS voice)
  bm_lewis    — British Male Lewis
  am_michael  — American Male Michael
  am_adam     — American Male Adam
  af_bella    — American Female Bella
  af_sarah    — American Female Sarah
  bf_emma     — British Female Emma
  bf_isabella — British Female Isabella
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from voice.backends.base import TTSBackend

# Human-readable descriptions for available voice IDs
KOKORO_VOICES: dict[str, str] = {
    "bm_george":   "British Male — George",
    "bm_lewis":    "British Male — Lewis",
    "am_michael":  "American Male — Michael",
    "am_adam":     "American Male — Adam",
    "af_bella":    "American Female — Bella",
    "af_sarah":    "American Female — Sarah",
    "bf_emma":     "British Female — Emma",
    "bf_isabella": "British Female — Isabella",
}


class KokoroBackend(TTSBackend):
    """Kokoro ONNX neural TTS backend.

    High quality, fully local, fast (~50 ms synthesis after warmup).
    Primary backend for JARVIS.
    """

    def __init__(
        self,
        model_dir: Path,
        default_voice: str = "bm_george",
        default_speed: float = 1.0,
    ):
        self._model_dir    = model_dir
        self._voice        = default_voice
        self._speed        = default_speed
        self._kokoro       = None
        self._ready        = False

    def get_backend_name(self) -> str:
        return "kokoro"

    def is_ready(self) -> bool:
        return self._ready

    def initialize(self) -> bool:
        """Load Kokoro model files. Call once during background init. Returns True on success."""
        try:
            from kokoro_onnx import Kokoro  # noqa: PLC0415

            model_f  = self._model_dir / "kokoro-v0_19.onnx"
            voices_f = None
            for candidate in ("voices-v1.0.bin", "voices.bin"):
                p = self._model_dir / candidate
                if p.exists():
                    voices_f = p
                    break

            print(f"[Kokoro] model={model_f}  exists={model_f.exists()}", flush=True)
            print(f"[Kokoro] voices={voices_f}", flush=True)

            if not model_f.exists():
                print("[Kokoro] Model file missing — skipping.", flush=True)
                return False
            if voices_f is None:
                print(
                    f"[Kokoro] Voices file not found in {self._model_dir}.\n"
                    "  Required: voices.bin or voices-v1.0.bin\n"
                    "  Download: https://huggingface.co/hexgrad/Kokoro-82M/tree/main",
                    flush=True,
                )
                return False

            self._kokoro = Kokoro(str(model_f), str(voices_f))
            self._ready  = True
            print(f"[Kokoro] Ready — default_voice={self._voice}", flush=True)
            return True

        except ImportError:
            print("[Kokoro] kokoro-onnx not installed — run: pip install kokoro-onnx", flush=True)
            return False
        except Exception as exc:
            print(f"[Kokoro] Init failed: {exc}", flush=True)
            return False

    def warmup(self) -> None:
        """Prewarm the ONNX inference graph across configured persona voices."""
        if not self._ready or not self._kokoro:
            return

        warmup_voices: set[str] = {self._voice}
        try:
            import config as _cfg
            for pv in getattr(_cfg, "PERSONA_VOICES", {}).values():
                warmup_voices.add(pv["voice"])
        except Exception:
            pass

        for wv in warmup_voices:
            try:
                self._kokoro.create(".", voice=wv, speed=1.0, lang="en-us")
                print(f"[Kokoro] Prewarm OK — voice={wv}", flush=True)
            except Exception as we:
                print(f"[Kokoro] Prewarm skipped voice={wv}: {we}", flush=True)

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
    ) -> Optional[tuple[np.ndarray, int]]:
        """Synthesize text and return (samples_float32, sample_rate)."""
        if not self._ready or not self._kokoro:
            return None
        try:
            v = voice_id if (voice_id and voice_id in KOKORO_VOICES) else self._voice
            s = speed if speed != 1.0 else self._speed
            samples, sample_rate = self._kokoro.create(
                text, voice=v, speed=s, lang="en-us"
            )
            return np.asarray(samples, dtype=np.float32), int(sample_rate)
        except Exception as exc:
            print(f"[Kokoro] Synthesis error: {exc}", flush=True)
            return None

    def interrupt(self) -> None:
        """Signal audio stop (sounddevice stop is handled by the orchestrator)."""

    def list_voices(self) -> list[str]:
        return list(KOKORO_VOICES.keys())

    def set_voice(self, voice_id: str) -> str:
        matched = (
            voice_id if voice_id in KOKORO_VOICES
            else next(
                (v for v in KOKORO_VOICES if voice_id.lower() in v.lower()),
                None,
            )
        )
        if not matched:
            opts = ", ".join(sorted(KOKORO_VOICES))
            return f"Voice '{voice_id}' not recognised. Options: {opts}"
        self._voice = matched
        return f"Voice switched to {matched} ({KOKORO_VOICES[matched]})."

    def get_voice(self) -> str:
        return self._voice

    def set_speed(self, speed: float) -> None:
        self._speed = max(0.5, min(2.0, speed))

    def get_voices_display(self) -> str:
        lines = "\n".join(
            f"  {vid:<14} — {desc}" + (" [active]" if vid == self._voice else "")
            for vid, desc in KOKORO_VOICES.items()
        )
        return f"Available voices:\n{lines}"
