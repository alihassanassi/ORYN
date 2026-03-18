"""
runtime/night_watchman.py – Minimal always-on wake phrase listener.

Runs even when JARVIS is not running.
Listens for wake phrase. Starts JARVIS when heard.
Uses <50MB RAM. No GPU. No LLM. Just audio + keyword detection.

Register with Windows Task Scheduler on user login:
  schtasks /create /tn "JARVIS Night Watchman" /tr
  "powershell -WindowStyle Hidden -File C:\\...\\START_WATCHMAN.ps1"
  /sc onlogon /ru %USERNAME%

Wake phrases:
  "JARVIS wake up"
  "Daddy's home"
  "Hey JARVIS start"
  "Wake up JARVIS"
"""
from __future__ import annotations
import subprocess
import sys
import time
import pathlib
import logging
import threading

logger = logging.getLogger(__name__)

JARVIS_ROOT     = pathlib.Path(__file__).parent.parent
JARVIS_LAUNCHER = JARVIS_ROOT / "JARVIS_GUARDIAN.ps1"
LOCK_FILE       = JARVIS_ROOT / "JARVIS_RUNNING.flag"

WAKE_PHRASES = [
    "jarvis wake up",
    "daddy's home",
    "daddys home",
    "hey jarvis start",
    "wake up jarvis",
    "jarvis start",
    "start jarvis",
]


def is_jarvis_running() -> bool:
    """Check if JARVIS is already running."""
    try:
        import psutil
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                if ('python' in proc.name().lower() and
                        any('main.py' in arg for arg in (proc.cmdline() or []))):
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return LOCK_FILE.exists()


def start_jarvis():
    """Launch JARVIS via the guardian script."""
    if is_jarvis_running():
        logger.info("[Watchman] JARVIS already running – not launching")
        return
    logger.info("[Watchman] Wake phrase detected – launching JARVIS")
    try:
        if JARVIS_LAUNCHER.exists():
            subprocess.Popen(
                ["powershell.exe", "-ExecutionPolicy", "Bypass",
                 "-File", str(JARVIS_LAUNCHER)],
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            # Fallback: launch main.py directly
            python_exe = JARVIS_ROOT / "jarvis_env" / "Scripts" / "python.exe"
            subprocess.Popen(
                [str(python_exe), str(JARVIS_ROOT / "main.py")],
                cwd=str(JARVIS_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                env={"JARVIS_WAKE_PHRASE": "1"}
            )
    except Exception as e:
        logger.error(f"[Watchman] Failed to start JARVIS: {e}")


def listen_for_wake():
    """Continuous minimal audio listen loop."""
    try:
        import sounddevice as sd
        import numpy as np
        import faster_whisper

        model = faster_whisper.WhisperModel(
            "tiny", device="cpu", compute_type="int8"
        )  # tiny model – <40MB RAM, CPU only

        SAMPLE_RATE = 16000
        CHUNK_SECS  = 2.0   # 2 second chunks
        THRESHOLD   = 0.015

        logger.info("[Watchman] Listening for wake phrase...")

        while True:
            try:
                audio = sd.rec(
                    int(CHUNK_SECS * SAMPLE_RATE),
                    samplerate=SAMPLE_RATE, channels=1,
                    dtype='float32'
                )
                sd.wait()

                # Quick energy check – skip silent chunks
                energy = float(np.abs(audio).mean())
                if energy < THRESHOLD:
                    continue

                # Transcribe
                segments, _ = model.transcribe(
                    audio.flatten(),
                    language="en",
                    vad_filter=True
                )
                text = " ".join(s.text for s in segments).lower().strip()

                if any(phrase in text for phrase in WAKE_PHRASES):
                    logger.info(f"[Watchman] Wake phrase heard: '{text}'")
                    start_jarvis()
                    time.sleep(15)  # wait before listening again

            except Exception as e:
                logger.debug(f"[Watchman] Listen error: {e}")
                time.sleep(1)

    except Exception as e:
        logger.error(f"[Watchman] Fatal error: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    listen_for_wake()
