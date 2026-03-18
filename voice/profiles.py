"""voice/profiles.py — Voice profile definitions for JARVIS personas.

Each profile is a complete voice configuration binding a persona to:
  - Preferred backend order (first available wins)
  - Voice/model identifier (backend-specific)
  - Speaking speed
  - Text normalization style
  - Post-FX chain
  - A short test line for validation
  - An honest fallback description

Profile selection:
  - Default: auto-derived from config.ACTIVE_PERSONA
  - Override: TTS.set_profile(name) or tool_set_voice_profile(name)

Honesty note:
  - The "jarvis_indian" profile uses bf_emma (British Female) because
    no Indian-accented voice exists in kokoro-onnx v0.19.
  - This is documented clearly and degrades honestly — no fake DSP accent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VoiceProfile:
    """A complete voice configuration profile."""

    name               : str
    display_name       : str
    # Backends tried in order; first available wins
    backend_preference : list[str]
    # Voice identifier (kokoro voice_id, piper model stem, or "" for SAPI auto-select)
    voice_id           : str
    speed              : float = 1.0
    # Text normalization style: "cyber" | "military" | "standard"
    normalize_style    : str   = "cyber"
    # Post-FX chain: "none" | "jarvis_polish" | "clone_comms"
    postfx_chain       : str   = "none"
    # Short line spoken when the profile is activated (smoke test)
    test_line          : str   = "Voice configuration verified. Standing by."
    # Profile to activate if all preferred backends unavailable
    fallback_profile   : Optional[str] = None
    # Operator-visible notes
    notes              : str   = ""
    # Chatterbox-specific (ignored by all other backends)
    # Path to reference WAV for zero-shot voice cloning (None = model default voice)
    reference_audio_path: Optional[str] = None
    # Emotion exaggeration: 0.0 = flat/neutral, 1.0 = very dramatic
    exaggeration         : float = 0.5
    # When True and no reference_audio_path file is present on disk,
    # Chatterbox backend will log a clear message and fall through to Kokoro.
    chatterbox_fallback_to_kokoro: bool = False


# ── Canonical profile registry ────────────────────────────────────────────────

PROFILES: dict[str, VoiceProfile] = {
    "jarvis_british": VoiceProfile(
        name               = "jarvis_british",
        display_name       = "JARVIS — British",
        backend_preference = ["kokoro", "piper", "sapi"],
        voice_id           = "bm_george",
        speed              = 1.0,
        normalize_style    = "cyber",
        postfx_chain       = "jarvis_polish",
        test_line          = "All systems operational, sir. Standing by.",
        fallback_profile   = "fallback_default",
        notes              = "Classic JARVIS. Kokoro bm_george. jarvis_polish FX applied.",
    ),

    "jarvis_indian": VoiceProfile(
        name               = "jarvis_indian",
        display_name       = "JARVIS — India",
        backend_preference = ["kokoro", "piper", "sapi"],
        voice_id           = "bf_emma",
        speed              = 0.95,
        normalize_style    = "cyber",
        postfx_chain       = "jarvis_polish",
        test_line          = "Namaste, sir. All systems operational.",
        fallback_profile   = "fallback_default",
        notes              = (
            "No Indian-accent voice in kokoro-onnx v0.19. "
            "Uses bf_emma (British Female) as the closest warm/formal available voice. "
            "Not a fake DSP accent effect. Degrades honestly."
        ),
    ),

    "clone_trooper": VoiceProfile(
        name               = "clone_trooper",
        display_name       = "CT-7567 Rex",
        backend_preference = ["kokoro", "piper", "sapi"],
        voice_id           = "bm_lewis",
        speed              = 1.1,
        normalize_style    = "military",
        postfx_chain       = "clone_comms",
        test_line          = "CT-7567 online. Awaiting orders.",
        fallback_profile   = "fallback_default",
        notes              = "Clipped pace. clone_comms FX chain. bm_lewis voice.",
    ),

    "tactical_operator": VoiceProfile(
        name               = "tactical_operator",
        display_name       = "Tactical Operator",
        backend_preference = ["kokoro", "piper", "sapi"],
        voice_id           = "am_michael",
        speed              = 1.05,
        normalize_style    = "cyber",
        postfx_chain       = "none",
        test_line          = "Operator console ready. Awaiting tasking.",
        fallback_profile   = "fallback_default",
        notes              = "Neutral American Male. Clean unprocessed output.",
    ),

    "fallback_default": VoiceProfile(
        name               = "fallback_default",
        display_name       = "Fallback — SAPI",
        backend_preference = ["sapi"],
        voice_id           = "",
        speed              = 1.0,
        normalize_style    = "standard",
        postfx_chain       = "none",
        test_line          = "Voice fallback active.",
        fallback_profile   = None,
        notes              = "Windows SAPI. Always available. Last resort.",
    ),

    # ── Chatterbox profiles — neural TTS with zero-shot voice cloning ─────────
    "chatterbox_jarvis": VoiceProfile(
        name                          = "chatterbox_jarvis",
        display_name                  = "Chatterbox — JARVIS",
        backend_preference            = ["chatterbox", "kokoro", "piper", "sapi"],
        voice_id                      = "",
        speed                         = 0.95,
        normalize_style               = "cyber",
        postfx_chain                  = "jarvis_polish",
        test_line                     = "Indeed. Chatterbox neural voice online. All systems nominal.",
        fallback_profile              = "jarvis_british",
        notes                         = "JARVIS persona. Measured pace, dry wit. exaggeration=0.35 for controlled delivery.",
        reference_audio_path          = "voice/reference_clips/jarvis_reference.wav",
        exaggeration                  = 0.35,
        chatterbox_fallback_to_kokoro = True,
    ),

    "chatterbox_india": VoiceProfile(
        name                          = "chatterbox_india",
        display_name                  = "Chatterbox — India",
        backend_preference            = ["chatterbox", "kokoro", "piper", "sapi"],
        voice_id                      = "",
        speed                         = 1.0,
        normalize_style               = "cyber",
        postfx_chain                  = "none",
        test_line                     = "Namaste. Chatterbox neural voice active.",
        fallback_profile              = "jarvis_indian",
        notes                         = "Warm, confident Indian-accented clone. Falls back to Kokoro bf_emma.",
        reference_audio_path          = "voice/reference_clips/india_reference.wav",
        exaggeration                  = 0.55,
        chatterbox_fallback_to_kokoro = True,
    ),

    "chatterbox_ct7567": VoiceProfile(
        name                          = "chatterbox_ct7567",
        display_name                  = "Chatterbox — CT-7567",
        backend_preference            = ["chatterbox", "kokoro", "piper", "sapi"],
        voice_id                      = "",
        speed                         = 1.1,
        normalize_style               = "military",
        postfx_chain                  = "clone_comms",
        test_line                     = "CT-7567 online. Awaiting orders.",
        fallback_profile              = "clone_trooper",
        notes                         = "Rex persona. Clipped, fast delivery. exaggeration=0.25 keeps it flat and tactical.",
        reference_audio_path          = "voice/reference_clips/ct7567_reference.wav",
        exaggeration                  = 0.25,
        chatterbox_fallback_to_kokoro = True,
    ),

    "chatterbox_tactical": VoiceProfile(
        name                          = "chatterbox_tactical",
        display_name                  = "Chatterbox — Tactical Alert",
        backend_preference            = ["chatterbox", "kokoro", "piper", "sapi"],
        voice_id                      = "",
        speed                         = 1.0,
        normalize_style               = "military",
        postfx_chain                  = "clone_comms",
        test_line                     = "Tactical alert. High-intensity vocal mode active.",
        fallback_profile              = "tactical_operator",
        notes                         = "High exaggeration for threat/alert announcements. Same ref as ct7567.",
        reference_audio_path          = "voice/reference_clips/ct7567_reference.wav",
        exaggeration                  = 0.9,
        chatterbox_fallback_to_kokoro = True,
    ),

    "chatterbox_morgan": VoiceProfile(
        name                          = "chatterbox_morgan",
        display_name                  = "Chatterbox — Morgan",
        backend_preference            = ["chatterbox", "kokoro", "piper", "sapi"],
        voice_id                      = "",
        speed                         = 0.85,
        normalize_style               = "standard",
        postfx_chain                  = "none",
        test_line                     = "You know... some things take time to see clearly. I am here.",
        fallback_profile              = "tactical_operator",
        notes                         = "Morgan persona. Slow, weighty delivery. exaggeration=0.40 for resonant warmth without theatrics.",
        reference_audio_path          = "voice/reference_clips/morgan_reference.wav",
        exaggeration                  = 0.40,
        chatterbox_fallback_to_kokoro = True,
    ),

    "jar_jar": VoiceProfile(
        name               = "jar_jar",
        display_name       = "JAR JAR",
        backend_preference = ["kokoro", "piper", "sapi"],
        voice_id           = "bm_lewis",
        speed              = 0.85,
        normalize_style    = "standard",
        postfx_chain       = "none",
        test_line          = "Meesa JARVIS! Ohh mooie mooie — all systems okeeday!",
        fallback_profile   = "fallback_default",
        notes              = "Jar Jar Binks easter egg persona. Slower pace for comedic effect.",
    ),

    "chatterbox_default": VoiceProfile(
        name                 = "chatterbox_default",
        display_name         = "Chatterbox — Default",
        backend_preference   = ["chatterbox", "kokoro", "piper", "sapi"],
        voice_id             = "",
        speed                = 1.0,
        normalize_style      = "standard",
        postfx_chain         = "none",
        test_line            = "Chatterbox default voice active.",
        fallback_profile     = "fallback_default",
        notes                = "No cloning — uses Chatterbox model default voice. Clean unprocessed output.",
        reference_audio_path = None,
        exaggeration         = 0.5,
    ),
}

# Mapping: config.ACTIVE_PERSONA key → default profile name
# Each persona maps to its chatterbox variant as primary;
# the chatterbox profiles carry their own kokoro/piper/sapi fallbacks.
PERSONA_TO_PROFILE: dict[str, str] = {
    "jarvis":  "chatterbox_jarvis",
    "india":   "chatterbox_india",
    "ct7567":  "chatterbox_ct7567",
    "morgan":  "chatterbox_morgan",
    "jarjar":  "jar_jar",
}

# Chatterbox persona mapping — used by get_profile_for_persona() when
# Chatterbox backend is available.  Populated automatically at runtime;
# not used directly by this module.
PERSONA_TO_PROFILE_CHATTERBOX: dict[str, str] = {
    "jarvis":  "chatterbox_jarvis",
    "india":   "chatterbox_india",
    "ct7567":  "chatterbox_ct7567",
    "morgan":  "chatterbox_morgan",
}


def get_profile(name: str) -> Optional[VoiceProfile]:
    """Return a profile by name, or None if not found."""
    return PROFILES.get(name)


def list_profiles() -> list[str]:
    """Return list of all registered profile names."""
    return list(PROFILES.keys())


def get_profile_for_persona(persona: str) -> VoiceProfile:
    """Return the default profile for the given ACTIVE_PERSONA key."""
    profile_name = PERSONA_TO_PROFILE.get(persona, "jarvis_british")
    return PROFILES.get(profile_name, PROFILES["fallback_default"])
