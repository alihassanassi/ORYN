"""
voice/stt.py — Speech-to-text via faster-whisper.

Uses Realtek mic by default (configurable via MIC_KW).
GPU (CUDA float16) if available, else CPU int8.
Loaded in background thread so app opens instantly.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional


class STT:
    MIC_KW      = "realtek"
    SAMPLE_RATE = 16_000
    RECORD_SECS = 6

    def __init__(self):
        self._model   : Optional[object] = None
        self._mic_idx : Optional[int]    = None
        self._ready   : bool             = False
        threading.Thread(target=self._init, daemon=True).start()

    def _init(self):
        try:
            from faster_whisper import WhisperModel
            try:
                import torch
                if torch.cuda.is_available():
                    self._model = WhisperModel("small", device="cuda",
                                               compute_type="float16")
                else:
                    raise RuntimeError("no cuda")
            except Exception:
                self._model = WhisperModel("base", device="cpu",
                                           compute_type="int8", num_workers=4)
            self._mic_idx = self._find_mic()
            # Restore saved mic preference from settings store
            try:
                import storage.settings_store as _ss
                saved = _ss.get("audio.input_device_index")
                if saved is not None:
                    import sounddevice as sd
                    devs = sd.query_devices()
                    idx  = int(saved)
                    if 0 <= idx < len(devs) and devs[idx]["max_input_channels"] > 0:
                        self._mic_idx = idx
                        print(f"[STT] Restored mic: [{idx}] {devs[idx]['name']}", flush=True)
            except Exception:
                pass
            self._ready   = True
        except ImportError:
            pass
        except Exception:
            pass

    def _find_mic(self) -> Optional[int]:
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0 and self.MIC_KW in d["name"].lower():
                    return i
        except Exception:
            pass
        return None

    @property
    def ready(self) -> bool:
        return self._ready

    def status(self) -> dict:
        """Return status dict for settings panel display."""
        mic_name: Optional[str] = None
        try:
            if self._mic_idx is not None:
                import sounddevice as sd
                devices = sd.query_devices()
                if 0 <= self._mic_idx < len(devices):
                    mic_name = devices[self._mic_idx]["name"]
        except Exception:
            pass
        return {
            "ready":   self._ready,
            "mic":     mic_name,
            "mic_idx": self._mic_idx,
        }

    def list_input_devices(self) -> list:
        """Return list of (index, name) for all sounddevice input devices."""
        try:
            import sounddevice as sd
            return [
                (i, d["name"])
                for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0
            ]
        except Exception as exc:
            print(f"[STT] list_input_devices error: {exc}", flush=True)
            return []

    def set_input_device(self, device_index) -> str:
        """Switch microphone input device at runtime. device_index=None = system default."""
        if device_index is None:
            self._mic_idx = None
            try:
                import storage.settings_store as _ss
                _ss.set("audio.input_device_index", None)
            except Exception:
                pass
            return "Microphone set to system default."
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            idx  = int(device_index)
            if not (0 <= idx < len(devs)) or devs[idx]["max_input_channels"] < 1:
                return f"Invalid input device index {idx}."
            self._mic_idx = idx
            try:
                import storage.settings_store as _ss
                _ss.set("audio.input_device_index", idx)
            except Exception:
                pass
            return f"Microphone \u2192 [{idx}] '{devs[idx]['name']}'"
        except Exception as exc:
            return f"Failed to set input device: {exc}"

    def listen(self,
               on_result: Callable[[Optional[str]], None],
               on_start:  Optional[Callable] = None):
        if not self._ready:
            on_result(None)
            return
        threading.Thread(target=self._record, args=(on_result, on_start),
                         daemon=True).start()

    def _record(self, on_result, on_start):
        try:
            import sounddevice as sd
            import numpy as np
            if on_start:
                on_start()
            kw: dict = {"samplerate": self.SAMPLE_RATE, "channels": 1, "dtype": "float32"}
            if self._mic_idx is not None:
                kw["device"] = self._mic_idx
            audio = sd.rec(int(self.RECORD_SECS * self.SAMPLE_RATE), **kw)
            sd.wait()
            flat = audio.flatten().astype(np.float32)
            peak = float(np.max(np.abs(flat)))
            if peak < 0.005:
                on_result(None)
                return
            segs, _ = self._model.transcribe(
                flat, language="en", beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
            )
            text = " ".join(s.text for s in segs).strip()
            on_result(text or None)
        except Exception:
            on_result(None)
