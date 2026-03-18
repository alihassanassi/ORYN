"""
audio/sound_engine.py — Non-blocking UI sound playback for JARVIS.

All sounds play on a dedicated background thread.
Never blocks the main thread.
Never crashes if audio device is unavailable.
Volume controlled globally via config.UI_SOUND_VOLUME.

Usage:
    from audio.sound_engine import play, start, duck, unduck
    start()          # call once at boot
    play('ui_ready') # call anywhere, non-blocking
    duck()           # lower volume while TTS is speaking
    unduck()         # restore volume after TTS finishes

Sound files live in assets/sounds/ as WAV files.
Generate them once with: python generate_sounds.py
"""
from __future__ import annotations

import queue
import threading
import logging
import pathlib
from typing import Optional

logger = logging.getLogger(__name__)

_SOUND_DIR = pathlib.Path(__file__).parent.parent / "assets" / "sounds"
_q: queue.Queue = queue.Queue(maxsize=20)   # cap prevents spam
_thread: Optional[threading.Thread] = None
_started = False
_started_lock = threading.Lock()
_duck_lock = threading.Lock()
_duck_factor: float = 1.0  # 1.0 = full vol; 0.2 = ducked under TTS

# ── Category volumes ──────────────────────────────────────────────────────────
# Each event has a category; category vol * global vol = final vol.
# Values are multipliers (0.0–1.0). Override in config.py via SOUND_CATEGORY_VOLUMES.
_DEFAULT_CATEGORY_VOLUMES: dict[str, float] = {
    "ui":       1.00,   # clicks, transmit, receive
    "alerts":   1.10,   # findings, critical, kill_switch (slight boost)
    "voice":    0.80,   # mic on/off, persona switch
    "recon":    0.90,   # scan start/complete, tool operations
    "ambient":  0.50,   # background hum (reserved)
    "system":   1.00,   # startup, ready, error, approved
}

# ── SOUNDS_MAP — event alias → (category, wav_stem) ──────────────────────────
# Callers use short logical names; the map resolves to actual WAV files.
SOUNDS_MAP: dict[str, tuple[str, str]] = {
    # UI interactions
    "ui_click_primary":   ("ui",      "ui_click_primary"),
    "ui_click_nav":       ("ui",      "ui_click_nav"),
    "ui_transmit":        ("ui",      "ui_transmit"),
    "ui_receive":         ("ui",      "ui_receive"),
    # System lifecycle
    "ui_startup":         ("system",  "ui_startup"),
    "ui_ready":           ("system",  "ui_ready"),
    "ui_approved":        ("system",  "ui_approved"),
    "ui_error":           ("system",  "ui_error"),
    # Alerts / findings
    "ui_finding":         ("alerts",  "ui_finding"),
    "ui_critical":        ("alerts",  "ui_critical"),
    "ui_kill_switch":     ("alerts",  "ui_kill_switch"),
    # Recon / tool ops
    "ui_scan_start":      ("recon",   "ui_scan_start"),
    "ui_scan_complete":   ("recon",   "ui_scan_complete"),
    "ui_tool_start":      ("recon",   "ui_tool_start"),
    "ui_tool_done":       ("recon",   "ui_tool_done"),
    # Voice / persona
    "ui_wake_word":       ("voice",   "ui_wake_word"),
    "ui_persona_switch":  ("voice",   "ui_persona_switch"),
    "ui_mic_on":          ("voice",   "ui_mic_on"),
    "ui_mic_off":         ("voice",   "ui_mic_off"),
}


def _worker() -> None:
    while True:
        item = _q.get()
        if item is None:
            break
        path, cat_vol = item
        try:
            import config as _cfg
            global_vol = getattr(_cfg, "UI_SOUND_VOLUME", 0.7)
            if global_vol <= 0:
                continue
            with _duck_lock:
                df = _duck_factor
            _play_wav(path, global_vol * cat_vol * df)
        except Exception as e:
            logger.debug("[SoundEngine] play error: %s", e)
        finally:
            _q.task_done()


def _play_wav(path: str, volume: float) -> None:
    """Play a WAV file using sounddevice+soundfile (preferred) or winsound fallback."""
    # Primary: sounddevice + soundfile
    try:
        import sounddevice as sd
        import soundfile as sf
        data, sr = sf.read(path)
        sd.play(data * volume, sr, blocking=True)
        return
    except Exception:
        pass
    # Fallback: winsound (Windows only, no volume control)
    try:
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        pass


def start() -> None:
    """Start the sound worker thread. Call once at boot. Idempotent."""
    global _thread, _started
    with _started_lock:
        if _started:
            return
        _started = True
    _thread = threading.Thread(target=_worker, daemon=True, name="SoundEngine")
    _thread.start()
    logger.info("[SoundEngine] ready — sounds dir: %s", _SOUND_DIR)


def duck() -> None:
    """Lower playback volume while TTS is speaking. Call from tts.py on speak start."""
    global _duck_factor
    with _duck_lock:
        _duck_factor = 0.15


def unduck() -> None:
    """Restore playback volume after TTS finishes. Call from tts.py on speak end."""
    global _duck_factor
    with _duck_lock:
        _duck_factor = 1.0


def _resolve(sound_name: str) -> tuple[str, float]:
    """Return (wav_path, category_vol) for a sound name, or ('', 0) if not found."""
    try:
        import config as _cfg
        cat_vols = getattr(_cfg, "SOUND_CATEGORY_VOLUMES", _DEFAULT_CATEGORY_VOLUMES)
    except Exception:
        cat_vols = _DEFAULT_CATEGORY_VOLUMES

    if sound_name in SOUNDS_MAP:
        cat, stem = SOUNDS_MAP[sound_name]
        cat_vol = cat_vols.get(cat, 1.0)
        wav = str(_SOUND_DIR / f"{stem}.wav")
    else:
        # Bare stem passthrough — legacy calls like play("ui_startup")
        cat_vol = 1.0
        wav = str(_SOUND_DIR / f"{sound_name}.wav")

    if not pathlib.Path(wav).exists():
        logger.debug("[SoundEngine] sound not found: %s", sound_name)
        return ("", 0.0)
    return (wav, cat_vol)


def play(sound_name: str) -> None:
    """
    Play a named UI sound. Non-blocking. Drops if queue full.

    sound_name: logical event name, e.g. 'ui_transmit', 'ui_tool_start', 'ui_finding'
    Resolved via SOUNDS_MAP; falls back to bare wav stem for legacy callers.
    """
    try:
        import config as _cfg
        if not getattr(_cfg, "UI_SOUNDS_ENABLED", True):
            return
    except Exception:
        pass

    if not _started:
        start()

    wav, cat_vol = _resolve(sound_name)
    if not wav:
        return
    try:
        _q.put_nowait((wav, cat_vol))
    except queue.Full:
        pass  # drop silently — never block the caller


def stop() -> None:
    """Shut down the sound worker thread."""
    _q.put(None)
