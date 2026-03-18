"""voice/backends/sapi_backend.py — Windows SAPI TTS backend.

Uses a persistent PowerShell process to avoid 2-4 s spawn overhead per utterance.
Always available on Windows as the last-resort fallback.
"""
from __future__ import annotations

import subprocess
import threading
from typing import Optional

import numpy as np

from voice.backends.base import TTSBackend


class SAPIBackend(TTSBackend):
    """Windows SAPI TTS via persistent PowerShell subprocess.

    Per-call cost after warmup: ~5 ms.
    Spawn cost: ~2-3 s (done once at init).
    """

    def __init__(self):
        self._voice     : Optional[str]               = None
        self._rate      : int                         = -1
        self._proc_a    : Optional[subprocess.Popen]  = None   # active
        self._proc_s    : Optional[subprocess.Popen]  = None   # standby
        self._lock      = threading.Lock()
        self._speaking  = threading.Event()
        self._ready     = False

    def get_backend_name(self) -> str:
        return "sapi"

    def is_ready(self) -> bool:
        return self._ready

    def initialize(self) -> bool:
        """Spawn initial SAPI process. Returns True on success."""
        try:
            proc = self._spawn()
            if proc:
                with self._lock:
                    self._proc_a = proc
                self._ready = True
                # Pre-warm standby in background
                threading.Thread(target=self._warm_standby, daemon=True).start()
                # Apply voice preference in background
                threading.Thread(target=self._apply_voice_pref, daemon=True).start()
                print("[SAPI] Ready.", flush=True)
                return True
        except Exception as exc:
            print(f"[SAPI] Init failed: {exc}", flush=True)
        return False

    def _spawn(self) -> Optional[subprocess.Popen]:
        """Spawn a persistent PowerShell SAPI process."""
        vc = f'$s.SelectVoice("{self._voice}");' if self._voice else ""
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$s.Rate={self._rate};$s.Volume=100;{vc}"
            "[Console]::Out.WriteLine('READY');[Console]::Out.Flush();"
            "$r=[System.Console]::In;"
            "while($true){"
            "$l=$r.ReadLine();"
            "if($null -eq $l -or $l -eq '__EXIT__'){break}"
            "if($l -ne ''){"
            "$s.Speak($l);"
            "[Console]::Out.WriteLine('DONE');[Console]::Out.Flush()"
            "}}"
        )
        try:
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding="utf-8", bufsize=0,
            )
            line = proc.stdout.readline()
            if "READY" in line:
                return proc
            proc.kill()
        except Exception:
            pass
        return None

    def _warm_standby(self):
        proc = self._spawn()
        if proc:
            with self._lock:
                if self._proc_s and self._proc_s.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                else:
                    self._proc_s = proc

    def _apply_voice_pref(self):
        try:
            voices = self.list_voices()
            prefs  = ["Microsoft Mark", "Microsoft David", "Microsoft Guy",
                      "Microsoft James", "Microsoft George"]
            chosen = None
            for p in prefs:
                for v in voices:
                    if p.lower() in v.lower():
                        chosen = v
                        break
                if chosen:
                    break
            if not chosen and voices:
                chosen = voices[0]
            if not chosen:
                return
            self._voice = chosen
            new_proc = self._spawn()
            if not new_proc:
                return
            with self._lock:
                old = self._proc_a
                self._proc_a = new_proc
            if old and old.poll() is None:
                try:
                    old.stdin.write("__EXIT__\n")
                    old.stdin.flush()
                except Exception:
                    pass
        except Exception:
            pass

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
    ) -> Optional[tuple[np.ndarray, int]]:
        """SAPI does not return audio samples — use speak_direct() instead."""
        return None

    def speak_direct(self, text: str) -> None:
        """Speak text directly via the persistent SAPI process. Blocks until done."""
        safe = (text
                .replace('"', " ").replace("'", " ")
                .replace("`", " ").replace("\\", " ")
                .replace("\n", " "))

        proc = None
        with self._lock:
            if self._proc_a and self._proc_a.poll() is None:
                proc = self._proc_a
            elif self._proc_s and self._proc_s.poll() is None:
                self._proc_a = self._proc_s
                self._proc_s = None
                proc = self._proc_a
                threading.Thread(target=self._warm_standby, daemon=True).start()

        if proc is None:
            proc = self._spawn()
            if proc is None:
                return
            with self._lock:
                self._proc_a = proc
            threading.Thread(target=self._warm_standby, daemon=True).start()

        try:
            proc.stdin.write(safe + "\n")
            proc.stdin.flush()
            self._speaking.set()
            proc.stdout.readline()
            self._speaking.clear()
        except Exception:
            self._speaking.clear()
            with self._lock:
                if self._proc_a is proc:
                    self._proc_a = None
            threading.Thread(target=self._warm_standby, daemon=True).start()

    def interrupt(self) -> None:
        """Kill the active SAPI proc to interrupt mid-sentence speech."""
        if self._speaking.is_set():
            with self._lock:
                proc = self._proc_a
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
                with self._lock:
                    if self._proc_a is proc:
                        self._proc_a = None
        self._speaking.clear()

    def list_voices(self) -> list[str]:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Add-Type -AssemblyName System.Speech;"
                 "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                 "$s.GetInstalledVoices()|%{$_.VoiceInfo.Name}"],
                capture_output=True, text=True, timeout=10,
            )
            return [v.strip() for v in r.stdout.strip().splitlines() if v.strip()]
        except Exception:
            return []

    def set_voice(self, voice_id: str) -> str:
        voices = self.list_voices()
        matched = next(
            (v for v in voices if voice_id.lower() in v.lower() or v.lower() in voice_id.lower()),
            None,
        )
        if not matched:
            return f"Voice '{voice_id}' not found. Available: {', '.join(voices[:6])}"
        self._voice = matched
        # Spawn a new proc with the selected voice
        new_proc = self._spawn()
        if new_proc:
            with self._lock:
                old = self._proc_a
                self._proc_a = new_proc
            if old and old.poll() is None:
                try:
                    old.stdin.write("__EXIT__\n")
                    old.stdin.flush()
                except Exception:
                    pass
        return f"Voice set to {matched}."

    def set_rate(self, rate: int) -> None:
        self._rate = max(-10, min(10, int(rate)))

    def get_voices_display(self) -> str:
        voices = self.list_voices()
        lines  = "\n".join(f"  {i+1}. {v}" for i, v in enumerate(voices))
        active = f"\nActive: {self._voice}" if self._voice else ""
        return f"Mode: Windows SAPI\nInstalled voices:\n{lines}{active}"
