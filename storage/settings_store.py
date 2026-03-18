"""
storage/settings_store.py — Runtime operator preferences, JSON-backed.

Layer 4 (State/Memory). No GUI imports. No autonomy imports.

Separate from config.py (static constants). This module handles mutable
operator preferences that persist across sessions.

Thread-safety: all reads and writes are protected by a single module-level
threading.Lock. _flush() acquires a snapshot under the lock before writing
so set() and reset() never hold the lock during I/O.

Usage:
    import storage.settings_store as _ss
    _ss.load()                  # called once at startup (main_window.__init__)
    _ss.get('audio.tts_enabled')
    _ss.set('display.fullscreen', True)
    _ss.reset()
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

# ── Persistence path ──────────────────────────────────────────────────────────
SETTINGS_PATH: Path = Path(__file__).parent.parent / "jarvis_settings.json"

# ── Default values ────────────────────────────────────────────────────────────
DEFAULTS: dict[str, object] = {
    # Audio — output
    "audio.tts_enabled":        True,    # LIVE: gates _on_reply TTS call
    "audio.voice_name":         None,    # LIVE: None = auto from persona profile
    "audio.voice_rate":         1.0,     # LIVE: Kokoro/SAPI apply immediately; Piper restarts process
    "audio.auto_speak":         True,    # LIVE: gates ALWAYS_SPEAK path in _on_reply
    # Audio — input
    "audio.stt_enabled":        True,    # display only — STT model init is fixed at startup
    "audio.input_device_index":  None,   # LIVE: sounddevice input device index; None = keyword match
    "audio.output_device_index": None,   # LIVE: sounddevice output device index; None = system default
    "audio.chatterbox_exaggeration": 0.5, # LIVE: Chatterbox emotion intensity [0.0, 1.0]
    # Display
    "display.hud_brightness":   1.0,     # LIVE: 0.5–1.5; >1.0 clamped to 1.0 by Qt
    "display.reduced_motion":   False,   # RESTART: no runtime animation toggle exists
    "display.dim_idle_effects": False,   # RESTART: no runtime idle-dim toggle exists
    "display.fullscreen":       False,   # LIVE: showFullScreen() / showNormal()
    # Behaviour
    "behavior.startup_voice":   True,    # RESTART: guards _try_greet() in _boot()
    "behavior.minimal_mode":    False,   # RESTART: no runtime minimal-mode switch
    # Window
    "window.geometry":          None,    # LIVE: base64 QByteArray from saveGeometry()
    # Persona
    "active_persona":           "jarvis",  # persists last used persona across restarts
}

# ── Internal state ─────────────────────────────────────────────────────────────
_lock: threading.Lock       = threading.Lock()
_current: dict[str, object] = dict(DEFAULTS)


# ── Public API ─────────────────────────────────────────────────────────────────

def load() -> None:
    """
    Load settings from JSON file. Silent on missing file; corrupt file falls
    back to defaults with a printed warning. Unknown keys are dropped so that
    removed settings never persist stale data.
    """
    global _current
    if not SETTINGS_PATH.exists():
        return
    try:
        raw  = SETTINGS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        merged = dict(DEFAULTS)
        # Only accept keys we know about; silently drop unknown keys
        merged.update({k: v for k, v in data.items() if k in DEFAULTS})
        with _lock:
            _current = merged
    except Exception as exc:
        print(f"[Settings] Load failed: {exc} — using defaults.", flush=True)


def get(key: str) -> object:
    """Return the current value for key, or the default if key is unknown."""
    with _lock:
        return _current.get(key, DEFAULTS.get(key))


def set(key: str, value: object) -> None:
    """Write value to memory, then flush to JSON (outside the lock)."""
    with _lock:
        _current[key] = value
    _flush()


def reset() -> None:
    """Restore all keys to DEFAULTS and flush to JSON (outside the lock)."""
    global _current
    with _lock:
        _current = dict(DEFAULTS)
    _flush()


def all_settings() -> dict[str, object]:
    """Return a shallow copy of all current settings (for diagnostics)."""
    with _lock:
        return dict(_current)


# ── Internal ──────────────────────────────────────────────────────────────────

def _flush() -> None:
    """
    Write _current to JSON. Takes a snapshot under the lock so callers
    do not hold the lock during file I/O.
    """
    with _lock:
        data = dict(_current)
    try:
        SETTINGS_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[Settings] Flush failed: {exc}", flush=True)
