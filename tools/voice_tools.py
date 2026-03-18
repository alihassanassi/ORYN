"""
tools/voice_tools.py — TTS voice management tools + persona switching.

_TTS_REF is a one-element list holding the live TTS instance.
_PERSONA_CB is a one-element list holding the GUI persona-switch callback.
main_window.py populates both after construction so tools can
mutate runtime state without a circular import.
"""
from __future__ import annotations
import subprocess
from typing import Optional

# Populated by main_window.py after TTS is constructed:
#   from tools.voice_tools import _TTS_REF
#   _TTS_REF.clear(); _TTS_REF.append(tts_instance)
_TTS_REF: list = []

# Populated by main_window.py after UI is built:
#   from tools.voice_tools import _PERSONA_CB
#   _PERSONA_CB.clear(); _PERSONA_CB.append(callback_fn)
# callback_fn(persona_key: str) — updates face color + title label.
_PERSONA_CB: list = []

# ── Persona metadata ──────────────────────────────────────────────────────────
PERSONA_META: dict[str, dict] = {
    "jarvis": {
        "display": "J.A.R.V.I.S",
        "color":   "#18e0c1",
        "greeting": "Always, sir.",
    },
    "india": {
        "display": "J.A.R.V.I.S",
        "color":   "#ffa020",
        "greeting": "Namaste, sir. All systems operational.",
    },
    "ct7567": {
        "display": "CT-7567",
        "color":   "#39d353",
        "greeting": "CT-7567 online. What are your orders?",
    },
    "morgan": {
        "display": "J.A.R.V.I.S",
        "color":   "#b060ff",
        "greeting": "I'm here. What do you need?",
    },
    "jarjar": {
        "display": "J.A.R.V.I.S",
        "color":   "#FFD700",
        "greeting": "Meesa JARVIS! Ohh mooie mooie — all systems okeeday!",
    },
}

# Input aliases → canonical key
_PERSONA_ALIASES: dict[str, str] = {
    "jarvis":       "jarvis",
    "default":      "jarvis",
    "india":        "india",
    "jarvisindia":  "india",
    "ct7567":       "ct7567",
    "ct":           "ct7567",
    "clone":        "ct7567",
    "clonetrooper": "ct7567",
    "trooper":      "ct7567",
    "rex":          "ct7567",
    "captainrex":   "ct7567",
    "military":     "ct7567",
    "morgan":       "morgan",
    "morganfreeman":"morgan",
    "jarjar":       "jarjar",
    "jar":          "jarjar",
    "jarjarbinks":  "jarjar",
    "mesa":         "jarjar",
    "meesa":        "jarjar",
}


def tool_switch_persona(persona_name: str) -> dict:
    """Switch the active JARVIS persona and update GUI color + title."""
    import config as _cfg

    key = _PERSONA_ALIASES.get(
        persona_name.strip().lower().replace(" ", "").replace("-", "").replace("_", ""),
        None,
    )
    if key is None:
        return {
            "ok": False,
            "output": (
                f"Unknown persona '{persona_name}'. "
                "Available: jarvis, india, ct7567, morgan."
            ),
            "error": "unknown_persona",
            "artifacts": [],
            "meta": {},
        }

    _cfg.ACTIVE_PERSONA = key
    meta = PERSONA_META[key]

    if _PERSONA_CB:
        try:
            _PERSONA_CB[0](key)
        except Exception:
            pass

    return {
        "ok": True,
        "output": meta["greeting"],
        "error": None,
        "artifacts": [],
        "meta": {"persona": key, "color": meta["color"], "display": meta["display"]},
    }


def tool_list_voices() -> dict:
    if _TTS_REF:
        output = _TTS_REF[0].get_voices()
        return {"ok": True, "output": output, "error": None, "artifacts": [], "meta": {}}
    return {"ok": False, "output": "TTS engine not initialised yet, sir.", "error": "TTS not ready", "artifacts": [], "meta": {}}


def tool_set_voice(voice_name: str, rate: int = -1) -> dict:
    """Switch the live TTS voice."""
    if not _TTS_REF:
        return {"ok": False, "output": "TTS engine not initialised yet, sir.", "error": "TTS not ready", "artifacts": [], "meta": {}}
    tts = _TTS_REF[0]
    mode = tts.get_mode()

    if mode == "kokoro":
        output = tts.set_voice_kokoro(voice_name)
        return {"ok": True, "output": output, "error": None, "artifacts": [], "meta": {"mode": mode, "voice": voice_name}}

    if mode == "piper":
        output = tts.set_voice_piper(voice_name)
        return {"ok": True, "output": output, "error": None, "artifacts": [], "meta": {"mode": mode, "voice": voice_name}}

    try:
        sapi = getattr(tts, "_sapi", None)
        if sapi is not None:
            sapi.set_rate(max(-10, min(10, rate)))
            msg = sapi.set_voice(voice_name)
            ok = "not found" not in msg.lower()
            return {
                "ok": ok,
                "output": msg + (", sir." if ok else ""),
                "error": None if ok else "voice not found",
                "artifacts": [],
                "meta": {"mode": "sapi", "voice": voice_name, "rate": rate},
            }
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Speech;"
             "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
             "$s.GetInstalledVoices()|%{$_.VoiceInfo.Name}"],
            capture_output=True, text=True, timeout=10,
        )
        available = [v.strip() for v in r.stdout.strip().splitlines() if v.strip()]
        matched: Optional[str] = next(
            (v for v in available if voice_name.lower() in v.lower() or v.lower() in voice_name.lower()),
            None,
        )
        if not matched:
            return {
                "ok": False,
                "output": (f"Voice '{voice_name}' not found, sir.\n"
                           f"Available: {', '.join(available[:8])}"),
                "error": "voice not found",
                "artifacts": [],
                "meta": {"available": available[:8]},
            }
        return {
            "ok": False,
            "output": f"SAPI backend unavailable — cannot switch to '{matched}', sir.",
            "error": "sapi_handle_unavailable",
            "artifacts": [],
            "meta": {"voice": matched},
        }
    except Exception as e:
        return {"ok": False, "output": f"Could not set voice: {e}", "error": str(e), "artifacts": [], "meta": {}}


def tool_list_voice_profiles() -> dict:
    """List all available JARVIS voice profiles with their descriptions."""
    from voice.profiles import PROFILES
    lines = []
    for name, p in PROFILES.items():
        lines.append(f"  {name:<22} — {p.display_name}  [{p.backend_preference[0]}]")
        if p.notes:
            lines.append(f"    Note: {p.notes}")
    output = "Available voice profiles:\n" + "\n".join(lines)
    if _TTS_REF:
        active = _TTS_REF[0].get_active_profile()
        output += f"\n\nActive profile: {active}"
    return {"ok": True, "output": output, "error": None, "artifacts": [],
            "meta": {"profiles": list(PROFILES.keys())}}


def tool_set_voice_profile(profile_name: str) -> dict:
    """Switch the active JARVIS voice profile."""
    from voice.profiles import PROFILES
    if profile_name not in PROFILES and profile_name != "auto":
        available = ", ".join(PROFILES.keys())
        return {
            "ok": False,
            "output": (
                f"Profile '{profile_name}' not found, sir. "
                f"Available: {available}, auto"
            ),
            "error": "unknown_profile",
            "artifacts": [],
            "meta": {},
        }
    if _TTS_REF:
        msg = _TTS_REF[0].set_profile(profile_name)
        return {"ok": True, "output": msg, "error": None, "artifacts": [],
                "meta": {"profile": profile_name}}
    return {"ok": True,
            "output": f"Profile '{profile_name}' queued — TTS engine is still initialising.",
            "error": None, "artifacts": [], "meta": {"profile": profile_name}}
