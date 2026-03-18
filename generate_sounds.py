"""
generate_sounds.py — Synthesize all JARVIS UI sounds.

Run once from the project root:
  python generate_sounds.py

Requires: numpy  (pip install numpy)
Generates 16 WAV files in assets/sounds/
No external API needed — pure numpy synthesis.
"""
import numpy as np
import wave
import pathlib

SOUNDS_DIR = pathlib.Path("assets/sounds")
SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
SR = 44100  # sample rate


def save_wav(filename: str, samples: np.ndarray, sr: int = SR) -> None:
    samples = np.clip(samples, -1.0, 1.0)
    data = (samples * 32767).astype(np.int16)
    with wave.open(str(SOUNDS_DIR / filename), 'w') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(data.tobytes())


def tone(freq, duration, amp=0.3, attack=0.005, decay=0.01, sr=SR):
    t = np.linspace(0, duration, int(sr * duration))
    env = np.ones_like(t)
    atk = int(sr * attack)
    dcy = int(sr * decay)
    if atk:
        env[:atk] = np.linspace(0, 1, atk)
    if dcy:
        env[-dcy:] = np.linspace(1, 0, dcy)
    return amp * env * np.sin(2 * np.pi * freq * t)


def chirp(f0, f1, duration, amp=0.25, sr=SR):
    t = np.linspace(0, duration, int(sr * duration))
    freq = np.linspace(f0, f1, len(t))
    env = np.sin(np.pi * t / duration)
    return amp * env * np.sin(2 * np.pi * np.cumsum(freq) / sr)


# ── Generate all sounds ────────────────────────────────────────────────────────

save_wav("ui_click_primary.wav",
    tone(1200, 0.04, amp=0.2, attack=0.002, decay=0.035))

save_wav("ui_click_nav.wav",
    tone(900, 0.025, amp=0.15, attack=0.001, decay=0.022))

save_wav("ui_transmit.wav",
    chirp(800, 1400, 0.08, amp=0.22))

save_wav("ui_receive.wav",
    chirp(1200, 700, 0.06, amp=0.20))

save_wav("ui_finding.wav",
    np.concatenate([
        tone(880, 0.07, amp=0.25), np.zeros(int(SR * 0.03)),
        tone(1100, 0.07, amp=0.28), np.zeros(int(SR * 0.03)),
        tone(1320, 0.12, amp=0.30),
    ]))

save_wav("ui_critical.wav",
    np.concatenate([
        chirp(400, 800, 0.15, amp=0.35),
        np.zeros(int(SR * 0.05)),
        chirp(400, 800, 0.15, amp=0.40),
    ]))

save_wav("ui_scan_start.wav",
    np.concatenate([
        chirp(600, 1800, 0.12, amp=0.22),
        tone(1800, 0.04, amp=0.18),
    ]))

save_wav("ui_scan_complete.wav",
    np.concatenate([
        tone(1047, 0.08, amp=0.25), np.zeros(int(SR * 0.02)),
        tone(1319, 0.08, amp=0.28), np.zeros(int(SR * 0.02)),
        tone(1568, 0.15, amp=0.30),
    ]))

save_wav("ui_wake_word.wav",
    chirp(1000, 1600, 0.08, amp=0.18))

save_wav("ui_persona_switch.wav",
    np.concatenate([
        chirp(1800, 800, 0.06, amp=0.15),
        np.zeros(int(SR * 0.02)),
        chirp(800, 1400, 0.08, amp=0.20),
    ]))

save_wav("ui_kill_switch.wav",
    np.concatenate([
        chirp(800, 200, 0.3, amp=0.35),
        np.zeros(int(SR * 0.05)),
        chirp(400, 100, 0.2, amp=0.25),
    ]))

save_wav("ui_error.wav",
    np.concatenate([
        tone(180, 0.08, amp=0.3),
        np.zeros(int(SR * 0.02)),
        tone(160, 0.12, amp=0.28),
    ]))

save_wav("ui_approved.wav",
    np.concatenate([
        tone(880, 0.06, amp=0.22),
        np.zeros(int(SR * 0.01)),
        tone(1320, 0.12, amp=0.25),
    ]))

save_wav("ui_ready.wav",
    np.concatenate([
        tone(523, 0.06, amp=0.20), np.zeros(int(SR * 0.02)),
        tone(659, 0.06, amp=0.22), np.zeros(int(SR * 0.02)),
        tone(784, 0.06, amp=0.24), np.zeros(int(SR * 0.02)),
        tone(1047, 0.18, amp=0.28),
    ]))

# Startup: 3-second power-on rising sequence
parts = []
freqs = [220, 277, 330, 415, 523, 659, 784, 987, 1175, 1397]
for i, f in enumerate(freqs):
    parts.append(tone(f, 0.1, amp=0.1 + i * 0.025, attack=0.01, decay=0.05))
    parts.append(np.zeros(int(SR * 0.02)))
parts.append(chirp(400, 1600, 0.4, amp=0.30))
save_wav("ui_startup.wav", np.concatenate(parts))

# ── New events for enhanced sound engine ──────────────────────────────────────

# Tool start — quick mid ascending beep, brief (signals operation beginning)
save_wav("ui_tool_start.wav",
    chirp(600, 1000, 0.04, amp=0.14))

# Tool done — soft descending ding (operation completed)
save_wav("ui_tool_done.wav",
    chirp(1000, 700, 0.05, amp=0.13))

# Mic on — rising two-note (microphone activated, ready to record)
save_wav("ui_mic_on.wav",
    np.concatenate([
        tone(880, 0.03, amp=0.15, attack=0.002, decay=0.02),
        np.zeros(int(SR * 0.01)),
        tone(1320, 0.05, amp=0.18, attack=0.002, decay=0.04),
    ]))

# Mic off — falling two-note (microphone deactivated)
save_wav("ui_mic_off.wav",
    np.concatenate([
        tone(1100, 0.03, amp=0.14, attack=0.002, decay=0.02),
        np.zeros(int(SR * 0.01)),
        tone(660, 0.05, amp=0.12, attack=0.002, decay=0.04),
    ]))

# Count generated files
generated = list(SOUNDS_DIR.glob('*.wav'))
print(f"Generated {len(generated)} sound files in {SOUNDS_DIR}")
for f in sorted(generated):
    print(f"  {f.name}")
