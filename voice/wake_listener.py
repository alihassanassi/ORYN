"""
voice/wake_listener.py — Ambient intelligence layer for JARVIS.

Always listening on a background thread. Decides: respond vs log.
Wake words trigger the full JARVIS response pipeline via callback.
Ambient speech is logged to ambient_log table for context injection.

Does NOT modify voice/stt.py — wraps around it via its public API.
"""
from __future__ import annotations

import threading
import time
import logging
import re
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Module-level singleton — set when WakeListener starts, used by agent worker
# for ambient context injection without requiring an import-time reference.
_instance: "WakeListener | None" = None


def get_ambient_context_global(n: int = 5) -> str:
    """Return ambient context from the running WakeListener, or empty string."""
    if _instance is not None:
        return _instance.get_ambient_context(n)
    return ""


class WakeListener:

    def __init__(self, response_callback: Callable[[str], None]):
        """
        response_callback: called with (transcript: str) when wake word detected
        or when operator speaks within the active window after a wake word.
        """
        self._callback      = response_callback
        self._running       = False
        self._thread: Optional[threading.Thread] = None
        self._ambient_buffer: list[str] = []   # last 10 ambient entries
        self._last_wake     = 0.0              # timestamp of last wake word
        self._active_window = 30.0             # seconds to stay active after wake

        # Ambient audio monitor state
        import config as _cfg
        self._ambient_enabled: bool = getattr(_cfg, "AMBIENT_LISTENING_ENABLED", False)
        self._memory_manager = None            # set lazily on first use

    def start(self) -> None:
        if self._running:
            return
        global _instance
        _instance = self
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="WakeListener"
        )
        self._thread.start()
        logger.info("[WakeListener] Ambient listening active")

        if self._ambient_enabled:
            self._start_ambient_audio_monitor()

    def stop(self) -> None:
        self._running = False

    def push_transcript(self, text: str) -> None:
        """Feed a PTT-sourced transcript into ambient logging and the context buffer.

        Does NOT trigger response_callback — the PTT path already calls _submit()
        directly. This purely populates ambient_log (for DB persistence) and the
        in-memory buffer (for get_ambient_context LLM injection).
        """
        if not text or not text.strip():
            return
        priority = self._assess_priority(text)
        self._log_ambient(text, "ptt", responded=True, priority=priority)
        self._ambient_buffer.append(text)
        if len(self._ambient_buffer) > 10:
            self._ambient_buffer.pop(0)

    def get_ambient_context(self, n: int = 5) -> str:
        """Returns last N ambient entries as a string for LLM context injection."""
        if not self._ambient_buffer:
            return ""
        recent = self._ambient_buffer[-n:]
        return "Recent ambient context: " + ". ".join(recent)

    def _listen_loop(self) -> None:
        import config as _cfg
        wake_words = getattr(_cfg, "WAKE_WORDS", [
            "jarvis", "hey jarvis", "hey j",
            "daddy's home", "jarvis wake up", "jarvis im home",
        ])

        while self._running:
            try:
                transcript = self._capture_utterance()
                if not transcript or len(transcript.split()) < 2:
                    time.sleep(0.1)
                    continue

                wake_detected, clean = self._check_wake(transcript, wake_words)
                now = time.time()

                if wake_detected:
                    self._last_wake = now
                    logger.info("[WakeListener] Wake word: %r → command: %r", transcript, clean)
                    self._log_ambient(transcript, "wake", responded=True)
                    if clean:
                        self._callback(clean)
                elif now - self._last_wake < self._active_window:
                    # Still in active window — respond without wake word
                    self._log_ambient(transcript, "active_window", responded=True)
                    self._callback(transcript)
                else:
                    # Ambient mode — log, don't respond
                    priority = self._assess_priority(transcript)
                    self._log_ambient(transcript, "ambient", priority=priority)
                    self._ambient_buffer.append(transcript)
                    if len(self._ambient_buffer) > 10:
                        self._ambient_buffer.pop(0)

            except Exception as e:
                logger.debug("[WakeListener] listen error: %s", e)
                time.sleep(1)

    def _check_wake(self, transcript: str, wake_words: list) -> tuple[bool, str]:
        """
        Returns (wake_detected, remaining_command).
        Uses simple substring matching — robust enough for home use.
        """
        lower = transcript.lower().strip()
        for word in sorted(wake_words, key=len, reverse=True):  # longest first
            if word in lower:
                remaining = re.sub(re.escape(word), "", lower, count=1,
                                   flags=re.IGNORECASE).strip()
                return True, remaining
        return False, transcript

    def _assess_priority(self, transcript: str) -> str:
        security_terms = [
            "vuln", "exploit", "payload", "injection", "bypass",
            "cve", "rce", "sqli", "xss", "idor", "ssrf", "subdomain",
        ]
        lower = transcript.lower()
        return "high" if any(t in lower for t in security_terms) else "low"

    def _capture_utterance(self) -> Optional[str]:
        """
        Tries to get a transcribed utterance from the STT subsystem.
        Non-blocking: returns None immediately if nothing available.
        Falls back to a short poll.
        """
        try:
            # Attempt to use the STT result queue if exposed
            from voice.stt import STT as _STT
            # STT doesn't expose a static queue — use a very short-lived instance
            # with a tight timeout so the wake listener stays responsive.
            # We reuse the global STT instance if the main window has one,
            # otherwise skip (wake listener is additive — won't crash if absent).
            import importlib
            _m = importlib.import_module("voice.stt")
            if hasattr(_m, "_wake_result_queue"):
                q = getattr(_m, "_wake_result_queue")
                import queue as _q
                try:
                    return q.get_nowait()
                except _q.Empty:
                    return None
        except Exception:
            pass
        time.sleep(0.5)
        return None

    # ── Ambient audio monitor ─────────────────────────────────────────────────

    def _start_ambient_audio_monitor(self) -> None:
        """
        Spawns a background thread that continuously monitors the microphone
        for speech activity. Detected speech is recorded and passed to
        _process_ambient_audio() for transcription and memory extraction.
        """
        t = threading.Thread(
            target=self._ambient_audio_loop, daemon=True, name="AmbientAudioMonitor"
        )
        t.start()
        logger.info("[WakeListener] Ambient audio monitor started")

    def _ambient_audio_loop(self) -> None:
        """Background loop: detect speech by energy, record until silence, dispatch."""
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as e:
            logger.warning("[WakeListener] Ambient audio monitor unavailable: %s", e)
            return

        SAMPLE_RATE    = 16000
        CHUNK_FRAMES   = 1024           # ~64 ms per chunk
        ENERGY_THRESH  = 0.02           # RMS threshold for speech detection
        SILENCE_SECS   = 1.5            # trailing silence before end of utterance
        silence_chunks = int(SILENCE_SECS * SAMPLE_RATE / CHUNK_FRAMES)

        recording      = False
        silent_count   = 0
        audio_chunks: list = []

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_FRAMES,
            )
            stream.start()
        except Exception as e:
            logger.warning("[WakeListener] Could not open audio stream: %s", e)
            return

        try:
            while self._running:
                try:
                    chunk, _ = stream.read(CHUNK_FRAMES)
                except Exception as e:
                    logger.debug("[WakeListener] Audio read error: %s", e)
                    time.sleep(0.1)
                    continue

                rms = float(np.sqrt(np.mean(chunk ** 2)))

                if rms > ENERGY_THRESH:
                    recording = True
                    silent_count = 0
                    audio_chunks.append(chunk.copy())
                elif recording:
                    audio_chunks.append(chunk.copy())
                    silent_count += 1
                    if silent_count >= silence_chunks:
                        # Silence threshold reached — process accumulated audio
                        audio_data = np.concatenate(audio_chunks, axis=0)
                        threading.Thread(
                            target=self._process_ambient_audio,
                            args=(audio_data, SAMPLE_RATE),
                            daemon=True,
                        ).start()
                        audio_chunks = []
                        recording    = False
                        silent_count = 0
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _process_ambient_audio(self, audio_data, sample_rate: int) -> None:
        """
        Transcribe audio_data using faster_whisper.
        Falls back to CPU if CUDA is unavailable.
        Calls _on_ambient_transcript() with the resulting text.
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.debug("[WakeListener] faster_whisper not installed — ambient transcription skipped")
            return

        import config as _cfg
        model_size = getattr(_cfg, "AMBIENT_WHISPER_MODEL", "base")

        # Try CUDA first, fall back to CPU
        model = None
        for device, compute_type in [("cuda", "float16"), ("cpu", "int8")]:
            try:
                model = WhisperModel(model_size, device=device, compute_type=compute_type)
                break
            except Exception:
                continue

        if model is None:
            logger.debug("[WakeListener] Could not load WhisperModel")
            return

        try:
            import numpy as np
            # faster_whisper expects float32 mono at 16 kHz, shape (n,)
            if audio_data.ndim > 1:
                audio_data = audio_data[:, 0]
            segments, _ = model.transcribe(audio_data, language="en", beam_size=1)
            text = " ".join(seg.text for seg in segments).strip()
            if text:
                self._on_ambient_transcript(text)
        except Exception as e:
            logger.debug("[WakeListener] Transcription error: %s", e)

    def _on_ambient_transcript(self, text: str) -> None:
        """
        Handle a completed ambient transcript.

        - Skips utterances shorter than AMBIENT_MIN_WORDS.
        - If the text contains a wake phrase, routes it through the normal
          wake-word path and does NOT also log it as ambient.
        - Otherwise logs the transcript and, if memory extraction is enabled,
          calls extract_from_ambient() on the MemoryManager.
        """
        import config as _cfg
        min_words = getattr(_cfg, "AMBIENT_MIN_WORDS", 5)
        if len(text.split()) < min_words:
            return

        import importlib
        wake_words = getattr(_cfg, "WAKE_WORDS", ["jarvis"])
        wake_detected, _clean = self._check_wake(text, wake_words)
        if wake_detected:
            # Let the normal listen loop handle it — don't double-process
            return

        logger.info("[WakeListener] Ambient: %s", text[:80])
        self._log_ambient(text, "ambient_audio")
        self._ambient_buffer.append(text)
        if len(self._ambient_buffer) > 10:
            self._ambient_buffer.pop(0)

        if not getattr(_cfg, "AMBIENT_MEMORY_ENABLED", False):
            return

        # Lazily initialise memory manager
        if self._memory_manager is None:
            try:
                from memory.manager import MemoryManager
                self._memory_manager = MemoryManager()
            except Exception as e:
                logger.debug("[WakeListener] MemoryManager unavailable: %s", e)
                return

        try:
            keys = self._memory_manager.extract_from_ambient(text)
            if keys:
                logger.debug("[WakeListener] Stored %d ambient memories: %s", len(keys), keys)
        except Exception as e:
            logger.debug("[WakeListener] Memory extraction error: %s", e)

    def _log_ambient(self, transcript: str, mode: str,
                     responded: bool = False, priority: str = "low") -> None:
        """Persist ambient transcript to DB for context injection."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO ambient_log "
                    "(transcript, mode, responded, priority, created_at) "
                    "VALUES (?,?,?,?,datetime('now'))",
                    (transcript[:500], mode, int(responded), priority),
                )
        except Exception as e:
            logger.debug("[WakeListener] log error: %s", e)
