"""voice/backends/chatterbox_backend.py — Chatterbox neural TTS backend.

Model:   Resemble AI Chatterbox (MIT license)
VRAM:    ~6.8 GB on CUDA
Cloning: zero-shot from 5–30 s reference WAV
Tags:    [laugh] [cough] [chuckle] [sigh] (Turbo variant)

Fallback position: PRIMARY — used before Kokoro when a VoiceProfile
requests backend="chatterbox".  If this backend fails to load or
synthesize, the TTS orchestrator falls through to Kokoro → Piper → SAPI.

Install: pip install chatterbox-tts>=0.1.6
         (torch with CUDA is managed separately — do NOT pip install torch here)
"""
from __future__ import annotations

import os as _os
_os.environ.setdefault("HF_HUB_OFFLINE", "1")
_os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from voice.backends.base import TTSBackend

logger = logging.getLogger(__name__)

_CHATTERBOX_AVAILABLE = False
try:
    from chatterbox.tts import ChatterboxTTS  # noqa: F401 — availability probe
    _CHATTERBOX_AVAILABLE = True
except ImportError:
    pass


class ChatterboxBackend(TTSBackend):
    """
    Chatterbox neural TTS backend.

    Implements the TTSBackend interface for drop-in use by the TTS orchestrator.
    Chatterbox-specific parameters (reference audio path, exaggeration) are stored
    as instance variables and updated by the orchestrator before synthesis.
    """

    def __init__(self, device: Optional[str] = None):
        if device:
            self._device = device
        else:
            try:
                import torch
                if torch.cuda.is_available():
                    self._device = "cuda"
                    logger.info("[Chatterbox] CUDA available — loading on GPU.")
                else:
                    self._device = "cpu"
                    logger.warning(
                        "[Chatterbox] CUDA unavailable — loading on CPU. "
                        "Performance will be degraded."
                    )
            except ImportError:
                self._device = "cpu"
                logger.warning(
                    "[Chatterbox] torch not importable — loading on CPU. "
                    "Performance will be degraded."
                )
        self._model         = None
        self._ready_flag    = False
        self._lock          = threading.Lock()
        # Voice-cloning reference audio path (None = use model default voice)
        self._ref_path      : Optional[str] = None
        # Emotion exaggeration: 0.0 = flat/neutral, 1.0 = dramatic
        self._exaggeration  : float = 0.5

    # ── Abstract method implementations ──────────────────────────────────────

    def get_backend_name(self) -> str:
        return "chatterbox"

    def is_ready(self) -> bool:
        return self._ready_flag and self._model is not None

    def list_voices(self) -> list[str]:
        """Return WAV clip stems found in the reference_clips directory."""
        clips: list[str] = []
        try:
            import config as _cfg
            ref_dir = Path(getattr(_cfg, "CHATTERBOX_REFERENCE_DIR", "voice/reference_clips"))
            if ref_dir.exists():
                clips = sorted(p.stem for p in ref_dir.glob("*.wav"))
        except Exception:
            pass
        return clips if clips else ["default (no reference clips found)"]

    def set_voice(self, voice_id: str) -> str:
        """Set the reference audio path for voice cloning.

        voice_id may be:
          - An absolute or relative path to a .wav file
          - A stem name (e.g. "jarvis_reference") resolved against CHATTERBOX_REFERENCE_DIR
          - Empty string / None to disable cloning
        """
        if not voice_id:
            self._ref_path = None
            return "Chatterbox: voice cloning disabled — using model default voice."

        p = Path(voice_id)
        if p.exists():
            self._ref_path = str(p)
            return f"Chatterbox: reference audio set to '{p.name}'."

        # Try resolving against reference clips directory
        try:
            import config as _cfg
            ref_dir = Path(getattr(_cfg, "CHATTERBOX_REFERENCE_DIR", "voice/reference_clips"))
            candidate = ref_dir / (voice_id if voice_id.endswith(".wav") else f"{voice_id}.wav")
            if candidate.exists():
                self._ref_path = str(candidate)
                return f"Chatterbox: reference audio set to '{candidate.name}'."
        except Exception:
            pass

        # Store the path anyway — file may arrive later
        self._ref_path = voice_id
        return f"Chatterbox: reference path stored (file not yet present): {voice_id}"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def initialize(self) -> bool:
        """Load the Chatterbox model into VRAM. Returns True on success.

        Called once during background init by the TTS orchestrator.
        Thread-safe — only one call succeeds; subsequent calls are no-ops.
        """
        if self._ready_flag:
            return True

        if not _CHATTERBOX_AVAILABLE:
            print(
                "[Chatterbox] chatterbox-tts not installed — "
                "run: pip install chatterbox-tts>=0.1.6",
                flush=True,
            )
            return False

        try:
            import time
            from chatterbox.tts import ChatterboxTTS
            print(f"[Chatterbox] loading model on {self._device}...", flush=True)
            t0 = time.time()
            try:
                self._model = ChatterboxTTS.from_pretrained(device=self._device)
            except RuntimeError as e:
                if "out of memory" in str(e).lower():
                    import torch
                    torch.cuda.empty_cache()
                    logger.warning(
                        "[Chatterbox] CUDA OOM (%s) — falling back to CPU", e
                    )
                    self._device = "cpu"
                    self._model = ChatterboxTTS.from_pretrained(device=self._device)
                else:
                    raise
            print(
                f"[Chatterbox] ready in {time.time() - t0:.1f}s "
                f"(sr={self._model.sr}, device={self._device})",
                flush=True,
            )
            self._ready_flag = True
            return True
        except Exception as exc:
            print(f"[Chatterbox] initialize failed: {exc}", flush=True)
            return False

    def warmup(self) -> None:
        """Pre-generate one short utterance to warm up the inference graph."""
        if not self.is_ready():
            return
        try:
            self._model.generate(
                "Chatterbox online.",
                audio_prompt_path=None,
                exaggeration=0.5,
            )
            print("[Chatterbox] warmup complete.", flush=True)
        except Exception as exc:
            print(f"[Chatterbox] warmup error (non-fatal): {exc}", flush=True)

    def interrupt(self) -> None:
        """Stop any currently playing audio via sounddevice."""
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def stop(self) -> None:
        self.interrupt()

    # ── Synthesis ─────────────────────────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        profile=None,
    ) -> Optional[tuple[np.ndarray, int]]:
        """Synthesize text → (float32 audio array, sample_rate) or None.

        Parameters
        ----------
        text     : Text to synthesize.
        voice_id : Reference audio path for voice cloning.  When None, uses
                   the stored self._ref_path.  Falls back to model default
                   voice if neither is a valid file.
        speed    : Not used by Chatterbox (no speed control).
                   Exaggeration is set separately via set_exaggeration().
        profile  : Optional VoiceProfile.  When provided and
                   chatterbox_fallback_to_kokoro is True and no reference
                   audio file is present, synthesis is declined (returns None)
                   so the orchestrator falls through to Kokoro.
        """
        if not self.is_ready():
            return None

        # Resolve reference audio path
        ref: Optional[str] = None
        for candidate in (voice_id, self._ref_path):
            if candidate and Path(candidate).exists():
                ref = candidate
                break

        # If a profile requests fallback-to-Kokoro when the clip is absent,
        # decline to synthesize so the orchestrator falls through to Kokoro.
        if ref is None and profile is not None:
            fallback_flag = getattr(profile, "chatterbox_fallback_to_kokoro", False)
            if fallback_flag:
                kokoro_voice = getattr(profile, "voice_id", "") or "bm_george"
                logger.info(
                    "[TTS] No Chatterbox reference clip for %s – using Kokoro %s",
                    getattr(profile, "name", "unknown"),
                    kokoro_voice,
                )
                return None

        try:
            with self._lock:
                wav = self._model.generate(
                    text,
                    audio_prompt_path=ref,
                    exaggeration=self._exaggeration,
                )
            # wav is a torch Tensor [1, N] or [N]; convert to float32 numpy
            samples: np.ndarray = wav.squeeze().cpu().float().numpy()
            return samples.astype(np.float32), int(self._model.sr)

        except Exception as exc:
            print(f"[Chatterbox] synthesize error: {exc}", flush=True)
            return None

    # ── Chatterbox-specific helpers (not in base interface) ──────────────────

    def set_exaggeration(self, val: float) -> None:
        """Set emotion exaggeration level (clamped to [0.0, 1.0])."""
        self._exaggeration = max(0.0, min(1.0, float(val)))

    def get_voices_display(self) -> str:
        """Return a human-readable status string for get_voices() output."""
        clips = self.list_voices()
        ref   = self._ref_path or "none (model default voice)"
        return (
            f"Mode: Chatterbox neural TTS ({self._device.upper()})\n"
            f"Active reference: {ref}\n"
            f"Exaggeration: {self._exaggeration:.2f}\n"
            f"Reference clips available: {', '.join(clips)}"
        )


# ── Module-level helpers ───────────────────────────────────────────────────────

def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _cuda_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"
