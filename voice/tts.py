"""
voice/tts.py — TTS orchestration layer.

Public entry point for all text-to-speech in JARVIS. This module is the
orchestrator: it delegates synthesis to backend classes, applies text
normalization via TextNormalizer, selects voice profiles, and optionally
applies post-processing FX.

Architecture:
  TTS (orchestrator)
    → TextNormalizer      (voice/text_normalizer.py)
    → VoiceProfile        (voice/profiles.py)
    → TTSBackend subclass (voice/backends/)
    → postfx.apply()      (voice/postfx.py)

Backend priority (first available wins during init):
  1. Kokoro ONNX   — neural, fully local, ~50 ms synthesis after warmup
  2. Piper         — neural, local binary, secondary neural option
  3. Windows SAPI  — always available, last resort

ElevenLabs cloud TTS is preserved as an optional first-priority override
when config.ELEVENLABS_API_KEY is set.

Public API (backward compatible):
  tts.speak(text)
  tts.get_mode()             → str
  tts.get_voices()           → str
  tts.set_voice_kokoro(id)   → str
  tts.set_voice_piper(name)  → str
  tts.status()               → dict
  tts.is_speaking            → bool  (property)
  tts.get_active_profile()   → str   (new)
  tts.set_profile(name)      → str   (new)
  tts.list_profiles()        → list  (new)
  tts.list_output_devices()  → list  (Phase 2)
  tts.get_output_device()    → tuple (Phase 2)
  tts.set_output_device(idx) → str   (Phase 2)

Threading model:
  - Background init thread: loads backends without blocking the UI.
  - Speaker loop thread: consumes utterances from a single-slot queue.
  - Latest-wins: a new speak() call replaces any pending utterance and
    interrupts the currently playing one.
  - No GUI thread blocking at any point.
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import config as _config
from config import (
    KOKORO_MODEL_DIR, KOKORO_VOICE, KOKORO_SPEED,
    PIPER_EXE, PIPER_VOICES, PIPER_VOICE_PREFS,
    AUDIO_OUTPUT_KW, AUDIO_OUTPUT_INDEX, AUDIO_DEBUG,
)

from voice.backends.kokoro_backend import KokoroBackend
from voice.backends.piper_backend  import PiperBackend
from voice.backends.sapi_backend   import SAPIBackend
from voice.text_normalizer         import TextNormalizer
from voice.profiles                import (
    PROFILES, VoiceProfile, get_profile,
    get_profile_for_persona, list_profiles as _list_profiles,
)
import voice.postfx as _postfx


class TTS:
    """
    TTS orchestrator with automatic backend selection: Kokoro → Piper → SAPI.
    All public methods are thread-safe.
    """

    def __init__(self):
        self._ready           : bool          = False
        self._mode            : str           = "none"

        # ── Active profile ──────────────────────────────────────────────────
        # None = auto-derive from ACTIVE_PERSONA on every call
        self._active_profile_name: Optional[str] = getattr(
            _config, "VOICE_DEFAULT_PROFILE", None
        )

        # ── Backends ─────────────────────────────────────────────────────────
        # Chatterbox: loaded lazily in _init() — None until init completes
        self._chatterbox = None

        self._kokoro = KokoroBackend(
            model_dir     = KOKORO_MODEL_DIR,
            default_voice = KOKORO_VOICE,
            default_speed = KOKORO_SPEED,
        )
        self._piper = PiperBackend(
            piper_exe   = PIPER_EXE,
            voices_dir  = PIPER_VOICES,
            voice_prefs = PIPER_VOICE_PREFS,
        )
        self._sapi = SAPIBackend()

        # ── Audio output routing ─────────────────────────────────────────────
        self._out_idx      : Optional[int] = None
        self._out_name     : str           = "system default"
        self._out_fallback : bool          = False

        # ── Normalizer ────────────────────────────────────────────────────────
        self._normalizer = TextNormalizer()

        # ── Queue / interrupt ─────────────────────────────────────────────────
        self._pending    : Optional[tuple] = None   # (text, t_ready, profile)
        self._pend_lock  = threading.Lock()
        self._speak_evt  = threading.Event()

        # Legacy event tracking for is_speaking property backward compat
        self._kokoro_playing = threading.Event()
        self._speaking       = threading.Event()

        # _chatterbox_ready_evt: set by _init_chatterbox when Chatterbox finishes
        # loading (success or failure).  The primary fallback chain waits on it
        # so Kokoro doesn't start until we know whether Chatterbox is available,
        # but crucially Chatterbox and _find_output() run in parallel — removing
        # the sequential block that was causing the 9-second delay.
        self._chatterbox_ready_evt = threading.Event()

        threading.Thread(target=self._speaker_loop,    daemon=True,
                         name="TTS-speaker").start()
        threading.Thread(target=self._init_chatterbox, daemon=True,
                         name="TTS-chatterbox-init").start()
        threading.Thread(target=self._init,            daemon=True,
                         name="TTS-init").start()

    # ── Chatterbox early init (runs in parallel with _find_output) ────────────

    def _init_chatterbox(self):
        """Load Chatterbox in its own thread so it starts immediately at boot.

        Runs concurrently with _find_output() inside _init().  Sets
        _chatterbox_ready_evt when done (regardless of success/failure) so the
        primary fallback chain in _init() can proceed without extra delay.
        """
        try:
            from voice.backends.chatterbox_backend import ChatterboxBackend
            _cb = ChatterboxBackend()
            if _cb.initialize():
                _cb.warmup()
                self._chatterbox = _cb
                print(
                    f"[TTS] Chatterbox backend ready on {_cb._device}.",
                    flush=True,
                )
            else:
                print("[TTS] Chatterbox init failed — skipping.", flush=True)
        except Exception as exc:
            print(f"[TTS] Chatterbox unavailable: {exc} — skipping.", flush=True)
        finally:
            self._chatterbox_ready_evt.set()

    # ── Init ─────────────────────────────────────────────────────────────────

    def _init(self):
        self._out_idx, self._out_name, self._out_fallback = self._find_output()

        # Wait for Chatterbox to finish loading before proceeding to the primary
        # fallback chain.  Timeout is generous (120s) to handle slow CUDA loads
        # on first boot; after that Chatterbox is cached and loads in ~5s.
        self._chatterbox_ready_evt.wait(timeout=120)

        # ── Early-ready: if the active profile prefers Chatterbox and it loaded,
        # mark TTS ready NOW so the boot greeting fires without waiting for Kokoro
        # warmup (~10s).  Kokoro will continue loading in the background and will
        # become available for any calls after that.
        _default_profile = getattr(_config, "VOICE_DEFAULT_PROFILE", None)
        _chatterbox_preferred = (
            _default_profile
            and "chatterbox" in str(_default_profile).lower()
            and self._chatterbox is not None
            and self._chatterbox.is_ready()
        )
        if _chatterbox_preferred:
            self._mode  = "chatterbox"
            self._ready = True
            self._restore_settings()
            print("[TTS] early-ready via Chatterbox — Kokoro warmup continues in background.",
                  flush=True)

        # ── Primary fallback chain ────────────────────────────────────────────
        if self._kokoro.initialize():
            self._kokoro.warmup()
            if not self._ready:
                self._mode  = "kokoro"
                self._ready = True
        elif self._piper.initialize():
            if not self._ready:
                self._mode  = "piper"
                self._ready = True
        elif self._sapi.initialize():
            if not self._ready:
                self._mode  = "sapi"
                self._ready = True
        elif self._chatterbox and self._chatterbox.is_ready():
            # Edge case: only Chatterbox loaded
            if not self._ready:
                self._mode  = "chatterbox"
                self._ready = True

        if self._ready and not _chatterbox_preferred:
            self._restore_settings()

    def _restore_settings(self) -> None:
        """Apply persisted settings_store values after backends are ready.
        Runs inside the _init daemon thread — safe to call backend methods here."""
        try:
            import storage.settings_store as _ss
            saved_profile = _ss.get("audio.voice_name")
            if saved_profile and saved_profile != "auto":
                print(f"[TTS] Restoring profile: {self.set_profile(saved_profile)}", flush=True)
            saved_rate = _ss.get("audio.voice_rate")
            if saved_rate and float(saved_rate) != 1.0:
                self.set_speed(float(saved_rate))
            saved_exagg = _ss.get("audio.chatterbox_exaggeration")
            if saved_exagg is not None and self._chatterbox and self._chatterbox.is_ready():
                self._chatterbox.set_exaggeration(float(saved_exagg))
        except Exception as exc:
            print(f"[TTS] Settings restore error: {exc}", flush=True)

    def _find_output(self) -> tuple[Optional[int], str, bool]:
        """
        Returns (device_index, device_name, used_fallback).
        Priority: AUDIO_OUTPUT_INDEX → AUDIO_OUTPUT_KW match → sounddevice default (None).
        """
        try:
            import sounddevice as sd
            devices = sd.query_devices()

            if AUDIO_OUTPUT_INDEX is not None:
                idx = int(AUDIO_OUTPUT_INDEX)
                if 0 <= idx < len(devices) and devices[idx]["max_output_channels"] > 0:
                    name = devices[idx]["name"]
                    if AUDIO_DEBUG:
                        print(f"[TTS] output pinned by index {idx}: {name!r}", flush=True)
                    return idx, name, False
                print(
                    f"[TTS] AUDIO_OUTPUT_INDEX={AUDIO_OUTPUT_INDEX} invalid — falling back.",
                    flush=True,
                )

            kw = AUDIO_OUTPUT_KW.lower()
            for i, d in enumerate(devices):
                if d["max_output_channels"] > 0 and kw in d["name"].lower():
                    if AUDIO_DEBUG:
                        print(f"[TTS] output matched {kw!r}: [{i}] {d['name']!r}", flush=True)
                    return i, d["name"], False

            print(f"[TTS] keyword {kw!r} not matched — using sounddevice default.", flush=True)
            return None, "system default", True

        except Exception as exc:
            print(f"[TTS] _find_output error: {exc} — using sounddevice default.", flush=True)
            return None, "unknown (error)", True

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_mode(self) -> str:
        return self._mode

    @property
    def is_speaking(self) -> bool:
        """True while Kokoro is playing audio or SAPI/Piper is active."""
        return self._kokoro_playing.is_set() or self._speaking.is_set()

    def status(self) -> dict:
        return {
            "ready":       self._ready,
            "backend":     self._mode,
            "output":      self._out_name,
            "out_idx":     self._out_idx,
            "fallback":    self._out_fallback,
            "profile":     self._active_profile_name or "auto",
            "chatterbox":  (
                "ready" if (self._chatterbox and self._chatterbox.is_ready())
                else "unavailable"
            ),
        }

    def speak(self, raw: str):
        if not self._ready:
            return

        profile = self._resolve_profile()
        text    = self._normalizer.normalize(raw, style=profile.normalize_style)
        text    = self._normalizer.chunk(text, max_chars=450)
        if not text:
            return

        t_ready = time.monotonic()
        print(f"[TTS] response_ready={t_ready:.3f}", flush=True)

        with self._pend_lock:
            self._pending = (text, t_ready, profile)

        self._interrupt_current()
        self._speak_evt.set()

    def set_voice_kokoro(self, voice_id: str) -> str:
        """Switch the Kokoro voice. Fuzzy-matches against known voice IDs."""
        return self._kokoro.set_voice(voice_id)

    def set_voice_piper(self, model_name: str) -> str:
        """Switch to a different Piper model by name (without .onnx)."""
        result = self._piper.set_voice(model_name)
        if self._piper.is_ready():
            self._mode  = "piper"
            self._ready = True
        return result

    def set_speed(self, speed: float) -> str:
        """Set speech rate live on all ready backends. speed in [0.5, 2.0]."""
        speed = max(0.5, min(2.0, float(speed)))
        applied = []
        if self._kokoro.is_ready():
            self._kokoro.set_speed(speed)
            applied.append(f"Kokoro={speed:.2f}")
        if self._piper.is_ready():
            self._piper.set_speed(speed)
            applied.append(f"Piper={speed:.2f}")
        if self._sapi.is_ready():
            sapi_rate = int(round((speed - 1.0) * 5))  # 0.5→-3, 1.0→0, 2.0→+5
            self._sapi.set_rate(sapi_rate)
            applied.append(f"SAPI={sapi_rate}")
        return "Speed: " + ", ".join(applied) if applied else "No ready backends."

    def set_chatterbox_exaggeration(self, val: float) -> str:
        """Set Chatterbox emotion exaggeration live. val in [0.0, 1.0].
        Returns info string if Chatterbox not available."""
        if not self._chatterbox or not self._chatterbox.is_ready():
            return "Chatterbox not available."
        val = max(0.0, min(1.0, float(val)))
        self._chatterbox.set_exaggeration(val)
        return f"Chatterbox exaggeration → {val:.2f}"

    def get_chatterbox_exaggeration(self) -> float:
        """Return current Chatterbox exaggeration, or -1.0 if unavailable."""
        if not self._chatterbox or not self._chatterbox.is_ready():
            return -1.0
        return self._chatterbox._exaggeration

    def get_voices(self) -> str:
        if self._mode == "chatterbox" and self._chatterbox:
            return self._chatterbox.get_voices_display()
        if self._mode == "kokoro":
            profile = self._resolve_profile()
            return (
                f"Mode: Kokoro neural TTS\n"
                f"Active profile: {self._active_profile_name or 'auto'}\n"
                f"Active voice: {self._kokoro.get_voice()}  "
                f"speed: {self._kokoro._speed}  "
                f"(persona: {getattr(_config, 'ACTIVE_PERSONA', 'jarvis')})\n"
                f"{self._kokoro.get_voices_display()}"
            )
        if self._mode == "piper":
            available = self._piper.list_voices()
            active    = self._piper._model.stem if self._piper._model else "none"
            return (
                f"Mode: Piper neural TTS\n"
                f"Active model: {active}\n"
                f"Available models: {available}"
            )
        # SAPI
        voices = self._sapi.list_voices()
        lines  = "\n".join(f"  {i+1}. {v}" for i, v in enumerate(voices))
        return f"Mode: Windows SAPI\nInstalled voices:\n{lines}"

    # ── Profile API ────────────────────────────────────────────────────────────

    def get_active_profile(self) -> str:
        return self._active_profile_name or "auto"

    def set_profile(self, profile_name: str) -> str:
        """Switch to a named voice profile. Returns confirmation or error string."""
        if profile_name in ("auto", ""):
            self._active_profile_name = None
            return "Voice profile set to auto (follows active persona)."

        profile = get_profile(profile_name)
        if not profile:
            available = ", ".join(PROFILES.keys())
            return f"Profile '{profile_name}' not found. Available: {available}"

        self._active_profile_name = profile_name
        self._apply_profile_to_backends(profile)
        return f"Voice profile set to '{profile.display_name}'."

    def list_profiles(self) -> list[str]:
        return _list_profiles()

    def _resolve_profile(self) -> VoiceProfile:
        """Return the current effective VoiceProfile.

        If an explicit profile is set, return it.
        Otherwise derive from config.ACTIVE_PERSONA.
        """
        if self._active_profile_name:
            p = get_profile(self._active_profile_name)
            if p:
                return p
        persona = getattr(_config, "ACTIVE_PERSONA", "jarvis")
        return get_profile_for_persona(persona)

    def _apply_profile_to_backends(self, profile: VoiceProfile) -> None:
        """Configure the active backend to match the profile's voice settings."""
        for backend_name in profile.backend_preference:
            if backend_name == "chatterbox" and self._chatterbox and self._chatterbox.is_ready():
                ref   = getattr(profile, "reference_audio_path", None)
                exagg = float(getattr(profile, "exaggeration", 0.5))
                if ref:
                    self._chatterbox.set_voice(ref)
                self._chatterbox.set_exaggeration(exagg)
                # Chatterbox is profile-selected only; do not change _mode
                return
            if backend_name == "kokoro" and self._kokoro.is_ready():
                if profile.voice_id:
                    self._kokoro.set_voice(profile.voice_id)
                self._kokoro.set_speed(profile.speed)
                self._mode = "kokoro"
                return
            if backend_name == "piper" and self._piper.is_ready():
                if profile.voice_id:
                    self._piper.set_voice(profile.voice_id)
                self._mode = "piper"
                return
            if backend_name == "sapi" and self._sapi.is_ready():
                if profile.voice_id:
                    self._sapi.set_voice(profile.voice_id)
                self._mode = "sapi"
                return

    # ── Output device API (Phase 2) ────────────────────────────────────────────

    def list_output_devices(self) -> list[tuple[int, str]]:
        """Return list of (index, name) for all sounddevice output devices."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            return [
                (i, d["name"])
                for i, d in enumerate(devices)
                if d["max_output_channels"] > 0
            ]
        except Exception as exc:
            print(f"[TTS] list_output_devices error: {exc}", flush=True)
            return []

    def get_output_device(self) -> tuple[Optional[int], str]:
        """Return (current_index, current_name). Index is None = system default."""
        return self._out_idx, self._out_name

    def set_output_device(self, device_index: Optional[int]) -> str:
        """Switch audio output device at runtime.

        Parameters
        ----------
        device_index : sounddevice device index, or None for system default.

        Returns
        -------
        Confirmation or error string.
        """
        if device_index is None:
            self._out_idx  = None
            self._out_name = "system default"
            # Persist to settings store if available
            try:
                import storage.settings_store as _ss
                _ss.set("audio.output_device_index", None)
            except Exception:
                pass
            return "Audio output set to system default."

        try:
            import sounddevice as sd
            devices = sd.query_devices()
            idx     = int(device_index)
            if not (0 <= idx < len(devices)):
                return f"Device index {idx} out of range (0–{len(devices)-1})."
            if devices[idx]["max_output_channels"] < 1:
                return f"Device [{idx}] '{devices[idx]['name']}' has no output channels."
            name           = devices[idx]["name"]
            self._out_idx  = idx
            self._out_name = name
            # Persist to settings store if available
            try:
                import storage.settings_store as _ss
                _ss.set("audio.output_device_index", idx)
            except Exception:
                pass
            return f"Audio output switched to [{idx}] '{name}'."
        except Exception as exc:
            return f"Failed to set output device: {exc}"

    # ── Interrupt (public) ─────────────────────────────────────────────────────

    def interrupt(self) -> None:
        """Stop current speech immediately. Non-blocking. Never raises. Idempotent.

        Called by:
          - _submit() when a new message arrives while JARVIS is speaking
          - Natural language interrupt commands ("shut up", "stop", etc.)
          - Kill switch
        """
        try:
            # Discard any pending utterance first
            with self._pend_lock:
                self._pending = None
            self._interrupt_current()
        except Exception:
            pass

    # ── Speaker loop ──────────────────────────────────────────────────────────

    def _interrupt_current(self) -> None:
        """Interrupt the currently playing utterance (if any)."""
        if self._mode in ("kokoro", "chatterbox") and self._kokoro_playing.is_set():
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass
        elif self._speaking.is_set():
            if self._mode == "piper":
                self._piper.interrupt()
            elif self._mode == "sapi":
                self._sapi.interrupt()
            self._speaking.clear()

    def _speaker_loop(self):
        """Dedicated thread: one utterance at a time, latest-wins queue."""
        while True:
            self._speak_evt.wait()
            self._speak_evt.clear()

            with self._pend_lock:
                item          = self._pending
                self._pending = None

            if not item:
                continue

            text, t_ready, profile = item
            t_dispatch = time.monotonic()
            print(
                f"[TTS] dispatch_start={t_dispatch:.3f} "
                f"(queued={t_dispatch - t_ready:.3f}s)",
                flush=True,
            )

            persona = getattr(_config, "ACTIVE_PERSONA", "jarvis")
            if not self._say_elevenlabs(text, persona):
                self._say_with_profile(text, profile)

            with self._pend_lock:
                if self._pending:
                    self._speak_evt.set()

    def _say_with_profile(self, text: str, profile: VoiceProfile) -> None:
        """Synthesize and play text using the given profile's settings."""
        t_engine = time.monotonic()
        print(f"[TTS] engine_start={t_engine:.3f}", flush=True)

        backend_name = self._resolve_backend_for_profile(profile)

        if backend_name == "chatterbox" and self._chatterbox:
            # Update per-utterance cloning parameters from profile
            ref   = getattr(profile, "reference_audio_path", None)
            exagg = float(getattr(profile, "exaggeration", 0.5))
            self._chatterbox._ref_path     = ref
            self._chatterbox._exaggeration = max(0.0, min(1.0, exagg))
            audio_result = self._chatterbox.synthesize(text)
            if audio_result is not None:
                samples, sr = audio_result
                postfx_enabled = getattr(_config, "VOICE_POSTFX_ENABLED", True)
                samples = _postfx.apply(
                    samples, sr,
                    profile.postfx_chain if postfx_enabled else "none",
                )
                self._play_audio(samples, sr, text)
                return
            # Chatterbox synthesis failed — fall through to SAPI
            print("[TTS] Chatterbox synthesis failed — falling back to SAPI.", flush=True)
            self._say_sapi_direct(text)

        elif backend_name == "kokoro":
            audio_result = self._kokoro.synthesize(
                text,
                voice_id=profile.voice_id or None,
                speed=profile.speed,
            )
            if audio_result is not None:
                samples, sr = audio_result
                postfx_enabled = getattr(_config, "VOICE_POSTFX_ENABLED", True)
                samples = _postfx.apply(
                    samples, sr,
                    profile.postfx_chain if postfx_enabled else "none",
                )
                self._play_audio(samples, sr, text)
                return
            # Kokoro synthesis failed — fall through to SAPI
            self._say_sapi_direct(text)

        elif backend_name == "piper":
            audio_result = self._piper.synthesize(text)
            if audio_result is not None:
                samples, sr = audio_result
                postfx_enabled = getattr(_config, "VOICE_POSTFX_ENABLED", True)
                samples = _postfx.apply(
                    samples, sr,
                    profile.postfx_chain if postfx_enabled else "none",
                )
                self._play_audio(samples, sr, text)
                return
            self._say_sapi_direct(text)

        elif backend_name == "sapi":
            self._say_sapi_direct(text)
        else:
            print("[TTS] No backend available — utterance dropped.", flush=True)

        t_done = time.monotonic()
        print(f"[TTS] speak_end={t_done:.3f}", flush=True)

    def _resolve_backend_for_profile(self, profile: VoiceProfile) -> str:
        """Return the name of the first available backend for this profile."""
        for name in profile.backend_preference:
            if name == "chatterbox" and self._chatterbox and self._chatterbox.is_ready():
                return "chatterbox"
            if name == "kokoro" and self._kokoro.is_ready():
                return "kokoro"
            if name == "piper" and self._piper.is_ready():
                return "piper"
            if name == "sapi" and self._sapi.is_ready():
                return "sapi"
        if self._sapi.is_ready():
            return "sapi"
        return "none"

    def _play_audio(self, samples, sample_rate: int, fallback_text: str) -> None:
        """Play float32 audio via sounddevice. Blocks until done."""
        try:
            import sounddevice as sd
            import numpy as np
            t_speak = time.monotonic()
            print(f"[TTS] speak_begin={t_speak:.3f}", flush=True)
            if not isinstance(samples, np.ndarray) or samples.dtype != np.float32:
                samples = np.asarray(samples, dtype=np.float32)
            self._kokoro_playing.set()
            sd.play(samples, sample_rate, device=self._out_idx)
            sd.wait()
            self._kokoro_playing.clear()
            print(f"[TTS] speak_end={time.monotonic():.3f}", flush=True)
        except Exception as exc:
            self._kokoro_playing.clear()
            print(f"[TTS] audio playback error: {exc} — falling back to SAPI", flush=True)
            if fallback_text:
                self._say_sapi_direct(fallback_text)

    def _say_sapi_direct(self, text: str) -> None:
        """Fall-through to SAPI for any utterance that the primary backend failed."""
        if self._sapi.is_ready():
            self._speaking.set()
            self._sapi.speak_direct(text)
            self._speaking.clear()

    # ── ElevenLabs cloud TTS (optional override) ──────────────────────────────

    def _say_elevenlabs(self, text: str, persona: str) -> bool:
        """Synthesise via ElevenLabs cloud API. Returns True on success.
        Falls through silently to local backends when key absent or on error.
        """
        import json
        import os
        import tempfile
        import urllib.request

        api_key = getattr(_config, "ELEVENLABS_API_KEY", "")
        if not api_key:
            return False
        voices   = getattr(_config, "ELEVENLABS_VOICES", {})
        voice_id = voices.get(persona)
        if not voice_id:
            return False

        url     = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = json.dumps({
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={
                "xi-api-key":   api_key,
                "Content-Type": "application/json",
                "Accept":       "audio/mpeg",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                audio = resp.read()
            tf = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tf.write(audio)
            tf.close()
            self._play_audio_file(tf.name)
            try:
                os.unlink(tf.name)
            except Exception:
                pass
            return True
        except Exception as exc:
            print(f"[TTS] ElevenLabs error: {exc} — falling through to Kokoro", flush=True)
            return False

    def _play_audio_file(self, path: str) -> None:
        """Play an MP3 audio file. Tries pygame → playsound → PowerShell."""
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            return
        except Exception:
            pass
        try:
            from playsound import playsound
            playsound(path)
            return
        except Exception:
            pass
        subprocess.run(
            ["powershell", "-c", f"(New-Object Media.SoundPlayer '{path}').PlaySync()"],
            capture_output=True,
        )
