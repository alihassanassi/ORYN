"""voice/postfx.py — Post-processing FX chains for TTS audio output.

Applied after synthesis, before sounddevice playback.
All chains receive and return a float32 numpy array.

Chains:
    none          — no processing (pass-through)
    jarvis_polish — light high-shelf boost + gentle compression
    clone_comms   — bandpass + light distortion for radio comms feel
"""
from __future__ import annotations

import numpy as np

# Registered chain names — checked by validate_voice.py
CHAINS: list[str] = ["none", "jarvis_polish", "clone_comms"]


def apply(samples: np.ndarray, sample_rate: int, chain: str) -> np.ndarray:
    """Apply the named FX chain to the audio samples.

    Parameters
    ----------
    samples     : Audio data. int16 arrays are converted to float32 first.
    sample_rate : Sample rate in Hz.
    chain       : One of CHAINS. Unknown values fall through to 'none'.

    Returns
    -------
    float32 numpy array, same length as input, range approximately [-1.0, 1.0].
    """
    # Normalise input to float32
    if not isinstance(samples, np.ndarray):
        samples = np.asarray(samples, dtype=np.float32)
    if samples.dtype != np.float32:
        if samples.dtype == np.int16:
            samples = samples.astype(np.float32) / 32768.0
        elif samples.dtype == np.int32:
            samples = samples.astype(np.float32) / 2147483648.0
        else:
            samples = samples.astype(np.float32)

    if chain == "jarvis_polish":
        return _jarvis_polish(samples, sample_rate)
    elif chain == "clone_comms":
        return _clone_comms(samples, sample_rate)
    else:
        # "none" or any unknown chain
        return samples


# ── Chain implementations ──────────────────────────────────────────────────────

def _jarvis_polish(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Light high-shelf boost (presence/clarity) + soft-knee compression.

    Implemented purely with numpy — no scipy dependency required.
    """
    try:
        # High-shelf boost: emphasise 3 kHz+ for clarity/presence
        # Simple FIR high-pass approximation via first-order IIR
        # Cutoff ~3 kHz, boost factor ~1.25
        alpha = _shelf_coeff(3000.0, sample_rate)
        boosted = np.empty_like(samples)
        hp_prev = samples[0] if len(samples) > 0 else 0.0
        for i in range(len(samples)):
            hp      = alpha * (hp_prev + samples[i] - (samples[i - 1] if i > 0 else samples[i]))
            hp_prev = hp
            boosted[i] = samples[i] + 0.25 * hp  # blend: original + 25% high-freq boost

        # Soft-knee compression: reduce peaks above threshold
        threshold = 0.60
        ratio     = 3.0
        result    = np.where(
            np.abs(boosted) > threshold,
            np.sign(boosted) * (threshold + (np.abs(boosted) - threshold) / ratio),
            boosted,
        )
        # Normalise to -1..1 headroom
        peak = float(np.max(np.abs(result)))
        if peak > 0.01:
            result = result / peak * 0.95
        return result.astype(np.float32)
    except Exception:
        return samples


def _clone_comms(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Bandpass (300 Hz – 3.4 kHz) + soft clip for radio/comms character.

    Mimics the frequency response of a military radio channel.
    """
    try:
        # Bandpass via two cascaded first-order IIR filters
        # High-pass at 300 Hz (remove low rumble)
        alpha_hp = _hp_coeff(300.0, sample_rate)
        hp_out   = np.empty_like(samples)
        prev_hp  = samples[0] if len(samples) > 0 else 0.0
        prev_x   = samples[0] if len(samples) > 0 else 0.0
        for i in range(len(samples)):
            x       = samples[i]
            hp      = alpha_hp * (prev_hp + x - prev_x)
            prev_hp = hp
            prev_x  = x
            hp_out[i] = hp

        # Low-pass at 3.4 kHz (remove highs)
        alpha_lp = _lp_coeff(3400.0, sample_rate)
        lp_out   = np.empty_like(hp_out)
        prev_lp  = hp_out[0] if len(hp_out) > 0 else 0.0
        for i in range(len(hp_out)):
            lp      = prev_lp + alpha_lp * (hp_out[i] - prev_lp)
            prev_lp = lp
            lp_out[i] = lp

        # Soft clip (tanh) for mild harmonic distortion / bite
        clipped = np.tanh(lp_out * 1.4) / np.tanh(np.array(1.4))

        # Mild level boost to compensate for bandpass attenuation
        result = clipped * 1.15
        peak   = float(np.max(np.abs(result)))
        if peak > 0.01:
            result = result / peak * 0.90
        return result.astype(np.float32)
    except Exception:
        return samples


# ── Filter coefficient helpers ────────────────────────────────────────────────

def _hp_coeff(cutoff_hz: float, sample_rate: int) -> float:
    """First-order IIR high-pass alpha coefficient."""
    import math
    rc    = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt    = 1.0 / sample_rate
    return rc / (rc + dt)


def _lp_coeff(cutoff_hz: float, sample_rate: int) -> float:
    """First-order IIR low-pass alpha coefficient."""
    import math
    rc    = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt    = 1.0 / sample_rate
    return dt / (rc + dt)


def _shelf_coeff(cutoff_hz: float, sample_rate: int) -> float:
    """High-shelf IIR alpha (same formula as HP — used for shelf blending)."""
    return _hp_coeff(cutoff_hz, sample_rate)
