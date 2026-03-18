"""voice/backends/piper_backend.py — Piper neural TTS backend.

Piper is a local neural TTS binary.
Download from: https://github.com/rhasspy/piper/releases
Extract to: C:\\piper\\ (so piper.exe is at C:\\piper\\piper.exe)
Download voice models to: C:\\piper\\voices\\
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from voice.backends.base import TTSBackend


class PiperBackend(TTSBackend):
    """Piper neural TTS backend (runs as subprocess)."""

    SAMPLE_RATE = 22050

    def __init__(
        self,
        piper_exe: Path,
        voices_dir: Path,
        voice_prefs: list[str],
    ):
        self._exe        = piper_exe
        self._voices_dir = voices_dir
        self._prefs      = voice_prefs
        self._model      : Optional[Path] = None
        self._proc       : Optional[subprocess.Popen] = None
        self._buf        = bytearray()
        self._lock       = threading.Lock()
        self._ready      = False
        self._speed      : float = 1.0

    def get_backend_name(self) -> str:
        return "piper"

    def is_ready(self) -> bool:
        return self._ready

    def initialize(self) -> bool:
        """Check Piper binary and find a voice model. Returns True on success."""
        if not self._exe.exists():
            print(f"[Piper] Binary not found at {self._exe}", flush=True)
            return False
        model = self._find_model()
        if not model:
            print(f"[Piper] No voice models in {self._voices_dir}", flush=True)
            return False
        self._model  = model
        self._ready  = True
        print(f"[Piper] Ready — model={model.stem}", flush=True)
        return True

    def _find_model(self) -> Optional[Path]:
        if not self._voices_dir.exists():
            self._voices_dir.mkdir(parents=True, exist_ok=True)
            return None
        for pref in self._prefs:
            candidate = self._voices_dir / f"{pref}.onnx"
            if candidate.exists():
                return candidate
        onnx = list(self._voices_dir.glob("*.onnx"))
        return onnx[0] if onnx else None

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
    ) -> Optional[tuple[np.ndarray, int]]:
        """Synthesize via Piper subprocess. Returns (float32 samples, sample_rate)."""
        if not self._ready or not self._model:
            return None
        try:
            self._ensure_proc()
            with self._lock:
                start_pos = len(self._buf)

            self._proc.stdin.write(text.encode("utf-8") + b"\n")
            self._proc.stdin.flush()

            import time
            deadline = time.monotonic() + 20.0
            settled_since = None
            prev_len = start_pos
            while time.monotonic() < deadline:
                time.sleep(0.02)
                with self._lock:
                    cur_len = len(self._buf)
                if cur_len > start_pos:
                    if cur_len == prev_len:
                        if settled_since is None:
                            settled_since = time.monotonic()
                        elif time.monotonic() - settled_since > 0.05:
                            break
                    else:
                        settled_since = None
                prev_len = cur_len

            with self._lock:
                pcm_bytes = bytes(self._buf[start_pos:])
                del self._buf[:start_pos + len(pcm_bytes)]

            if not pcm_bytes:
                return None

            int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
            float32 = int16.astype(np.float32) / 32768.0
            return float32, self.SAMPLE_RATE

        except Exception as exc:
            print(f"[Piper] Synthesis error: {exc}", flush=True)
            self._proc = None
            return None

    def set_speed(self, speed: float) -> None:
        """Store speed and restart subprocess so --length-scale takes effect on next synthesize()."""
        new = max(0.5, min(2.0, float(speed)))
        if new != self._speed:
            self._speed = new
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
            self._proc = None

    def _ensure_proc(self):
        if self._proc and self._proc.poll() is None:
            return
        with self._lock:
            self._buf.clear()
        cmd = [str(self._exe), "--model", str(self._model), "--output_raw"]
        if self._speed != 1.0:
            cmd += ["--length-scale", str(round(1.0 / self._speed, 4))]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        proc = self._proc
        try:
            while proc and proc.poll() is None:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                with self._lock:
                    self._buf.extend(chunk)
        except Exception:
            pass

    def interrupt(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None

    def list_voices(self) -> list[str]:
        if not self._voices_dir.exists():
            return []
        return [p.stem for p in self._voices_dir.glob("*.onnx")]

    def set_voice(self, voice_id: str) -> str:
        candidate = self._voices_dir / f"{voice_id}.onnx"
        if candidate.exists():
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
            self._proc  = None
            self._model = candidate
            self._ready = True
            return f"Voice switched to {voice_id}."
        available = self.list_voices()
        return (f"Model '{voice_id}' not found in {self._voices_dir}. "
                f"Available: {available}")
