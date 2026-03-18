"""voice/backends/base.py — Abstract base class for all TTS backends.

All backends must subclass TTSBackend and implement the abstract methods.
The TTS orchestrator (voice/tts.py) discovers backends by checking is_ready()
after calling initialize().
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np


class TTSBackend(ABC):
    """Abstract TTS backend interface."""

    @abstractmethod
    def get_backend_name(self) -> str:
        """Return the short name of this backend (e.g. 'kokoro', 'piper', 'sapi')."""

    @abstractmethod
    def is_ready(self) -> bool:
        """Return True if the backend has been initialised and is ready to synthesize."""

    @abstractmethod
    def initialize(self) -> bool:
        """Load models / check availability. Returns True on success.
        Called once during TTS orchestrator background init. Must not block the GUI.
        """

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
    ) -> Optional[tuple[np.ndarray, int]]:
        """Synthesize text to audio.

        Returns (samples_float32, sample_rate) or None on failure.
        The returned samples must be a float32 numpy array in the range [-1.0, 1.0].
        """

    @abstractmethod
    def interrupt(self) -> None:
        """Interrupt any currently playing audio. Non-blocking."""

    @abstractmethod
    def list_voices(self) -> list[str]:
        """Return a list of available voice identifiers."""

    @abstractmethod
    def set_voice(self, voice_id: str) -> str:
        """Set the active voice. Returns a confirmation or error string."""

    def warmup(self) -> None:
        """Optional: pre-warm inference graph. Called after initialize() succeeds.
        Default is a no-op; override if prewarm improves first-call latency.
        """

    def get_voices_display(self) -> str:
        """Return a human-readable string listing available voices.
        Default implementation calls list_voices().
        """
        voices = self.list_voices()
        if not voices:
            return f"Mode: {self.get_backend_name()}\nNo voices available."
        lines = "\n".join(f"  {v}" for v in voices)
        return f"Mode: {self.get_backend_name()}\nAvailable voices:\n{lines}"
