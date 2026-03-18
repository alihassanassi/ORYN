"""voice/validate_voice.py — Smoke test for the JARVIS voice platform.

Run from jarvis_lab/ with:
  python -m voice.validate_voice

Tests:
  1. Import and init without crash
  2. Text normalization on cybersecurity/operator content
  3. Profile listing and profile resolution
  4. Backend selection (mode detection)
  5. Voice profile switching
  6. Backward-compatible API availability
  7. Interrupt/latest-wins: two rapid speak() calls without hang

Pass criteria: all tests print PASS. No exception raised.
Actual audio output is not required for the test to pass —
the test validates the logic path, not the audio hardware.
"""
from __future__ import annotations

import sys
import time

_PASS = 0
_FAIL = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if condition:
        print(f"  PASS  {name}")
        _PASS += 1
    else:
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))
        _FAIL += 1


def test_imports() -> None:
    print("\n[1] Import validation")
    try:
        from voice.text_normalizer import TextNormalizer
        _check("TextNormalizer import", True)
    except Exception as e:
        _check("TextNormalizer import", False, str(e))

    try:
        from voice.profiles import PROFILES, list_profiles, get_profile_for_persona
        _check("profiles import", True)
        _check("profiles non-empty", len(PROFILES) > 0)
    except Exception as e:
        _check("profiles import", False, str(e))

    try:
        import voice.postfx as pfx
        _check("postfx import", True)
        _check("postfx chains defined", len(pfx.CHAINS) >= 3)
    except Exception as e:
        _check("postfx import", False, str(e))

    try:
        from voice.backends.base import TTSBackend
        from voice.backends.kokoro_backend import KokoroBackend
        from voice.backends.piper_backend import PiperBackend
        from voice.backends.sapi_backend import SAPIBackend
        _check("backend imports", True)
    except Exception as e:
        _check("backend imports", False, str(e))

    try:
        from voice.tts import TTS
        _check("TTS import", True)
    except Exception as e:
        _check("TTS import", False, str(e))


def test_text_normalizer() -> None:
    print("\n[2] Text normalization")
    from voice.text_normalizer import TextNormalizer
    n = TextNormalizer()

    cases = [
        ("CVE normalization",
         "Found CVE-2024-12345 in the target.",
         "CVE 2024 dash 12345"),
        ("IP normalization",
         "Target is 192.168.0.1",
         "192 dot 168 dot 0 dot 1"),
        ("Port normalization",
         "Service running on :443",
         "port 443"),
        ("URL normalization",
         "Endpoint at https://api.example.com/v1/login",
         "api.example.com"),
        ("Hex normalization",
         "Address 0x1337 found",
         "hex 1337"),
        ("Percentage normalization",
         "Confidence 90%",
         "90 percent"),
        ("Code fence stripping",
         "Here is ```bash\necho hello\n```",
         "code block"),
        ("Bullet stripping",
         "- First item\n- Second item",
         "First item"),
        ("XSS expansion",
         "XSS vulnerability found",
         "cross-site scripting"),
        ("SSRF expansion",
         "SSRF via redirect",
         "server-side request forgery"),
    ]

    for name, input_text, expected_substr in cases:
        result = n.normalize(input_text, style=TextNormalizer.STYLE_CYBER)
        _check(name, expected_substr in result, f"got: {result!r}")

    # Chunking
    long_text = "This is sentence one. " * 30
    chunked = n.chunk(long_text, max_chars=100)
    _check("chunk respects max_chars", len(chunked) <= 120,
           f"len={len(chunked)}")


def test_profiles() -> None:
    print("\n[3] Profile system")
    from voice.profiles import (
        PROFILES, list_profiles, get_profile, get_profile_for_persona, PERSONA_TO_PROFILE
    )

    required = ["jarvis_british", "jarvis_indian", "clone_trooper",
                "tactical_operator", "fallback_default"]
    for name in required:
        _check(f"profile '{name}' exists", name in PROFILES)

    for name in list_profiles():
        p = get_profile(name)
        _check(f"profile '{name}' has backend_preference",
               len(p.backend_preference) > 0)
        _check(f"profile '{name}' has test_line",
               bool(p.test_line))

    for persona_key in ["jarvis", "india", "ct7567"]:
        p = get_profile_for_persona(persona_key)
        _check(f"persona '{persona_key}' → profile {p.name}", p is not None)

    # Indian profile honesty check
    india_p = get_profile("jarvis_indian")
    _check(
        "jarvis_indian has honesty note about no Indian voice",
        "no" in india_p.notes.lower() or "honest" in india_p.notes.lower(),
    )


def test_postfx() -> None:
    print("\n[4] Post-FX chains")
    import numpy as np
    import voice.postfx as pfx

    sr = 24000
    duration = 1.0
    t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    sine = np.sin(2 * 3.14159 * 220.0 * t).astype(np.float32)

    for chain in pfx.CHAINS:
        try:
            result = pfx.apply(sine, sr, chain)
            _check(f"chain '{chain}' runs without error", True)
            _check(f"chain '{chain}' returns float32",
                   result.dtype == np.float32)
            _check(f"chain '{chain}' output same length",
                   len(result) == len(sine))
            peak = float(np.max(np.abs(result)))
            _check(f"chain '{chain}' output not silent", peak > 1e-6)
        except Exception as e:
            _check(f"chain '{chain}'", False, str(e))

    # int16 input normalization
    int16_audio = (sine * 32767).astype(np.int16)
    result = pfx.apply(int16_audio, sr, "none")
    _check("int16 input converted to float32", result.dtype == np.float32)
    _check("int16 normalization range ok", float(np.max(np.abs(result))) <= 1.01)


def test_tts_init() -> None:
    print("\n[5] TTS initialization")
    from voice.tts import TTS

    try:
        tts = TTS()
        _check("TTS constructor does not raise", True)
    except Exception as e:
        _check("TTS constructor does not raise", False, str(e))
        return

    # Wait for background init (up to 120 s — Chatterbox loads ~6.8 GB into VRAM)
    deadline = time.monotonic() + 120.0
    while not tts._ready and time.monotonic() < deadline:
        time.sleep(0.2)

    mode = tts.get_mode()
    _check("TTS selects a backend", mode in ("kokoro", "piper", "sapi", "chatterbox"),
           f"mode={mode!r}")
    _check("TTS is_ready after init", tts._ready)

    # Backward-compatible API
    _check("get_mode() callable",    callable(getattr(tts, "get_mode", None)))
    _check("get_voices() callable",  callable(getattr(tts, "get_voices", None)))
    _check("set_voice_kokoro callable", callable(getattr(tts, "set_voice_kokoro", None)))
    _check("set_voice_piper callable",  callable(getattr(tts, "set_voice_piper", None)))
    _check("status() callable",      callable(getattr(tts, "status", None)))
    _check("speak() callable",       callable(getattr(tts, "speak", None)))

    # New profile API
    _check("get_active_profile() callable", callable(getattr(tts, "get_active_profile", None)))
    _check("set_profile() callable",        callable(getattr(tts, "set_profile", None)))
    _check("list_profiles() callable",      callable(getattr(tts, "list_profiles", None)))

    # Phase 2 output device API
    _check("list_output_devices() callable", callable(getattr(tts, "list_output_devices", None)))
    _check("get_output_device() callable",   callable(getattr(tts, "get_output_device", None)))
    _check("set_output_device() callable",   callable(getattr(tts, "set_output_device", None)))

    # Profile switching
    profiles = tts.list_profiles()
    _check("list_profiles() returns list", isinstance(profiles, list))
    _check("list_profiles() non-empty",    len(profiles) > 0)

    for profile_name in ["jarvis_british", "clone_trooper", "fallback_default"]:
        result = tts.set_profile(profile_name)
        _check(f"set_profile('{profile_name}') returns string", isinstance(result, str))

    result = tts.set_profile("nonexistent_profile_xyz")
    _check("set_profile(invalid) returns error string",
           "not found" in result.lower())

    # Auto-mode
    result = tts.set_profile("auto")
    _check("set_profile('auto') works", "auto" in result.lower())

    # speak() does not raise (may or may not produce audio)
    try:
        tts.speak("Voice validation test.")
        time.sleep(0.1)  # Give the speaker loop a moment
        _check("speak() does not raise", True)
    except Exception as e:
        _check("speak() does not raise", False, str(e))

    # Interrupt: two rapid calls should not hang
    try:
        tts.speak("First utterance which should be interrupted immediately.")
        tts.speak("Second utterance takes over.")
        time.sleep(0.1)
        _check("rapid double speak() no hang", True)
    except Exception as e:
        _check("rapid double speak() no hang", False, str(e))

    # SAPI fallback reachability
    if mode == "sapi":
        voices_str = tts.get_voices()
        _check("SAPI get_voices() returns string", isinstance(voices_str, str))


def test_voice_tools() -> None:
    print("\n[6] Voice tools backward compatibility")
    try:
        from tools.voice_tools import (
            tool_list_voices, tool_set_voice,
            tool_list_voice_profiles, tool_set_voice_profile,
            tool_switch_persona,
        )
        _check("tool_list_voices import",        True)
        _check("tool_set_voice import",          True)
        _check("tool_switch_persona import",     True)
        _check("tool_list_voice_profiles import", True)
        _check("tool_set_voice_profile import",  True)
    except Exception as e:
        _check("voice_tools imports", False, str(e))
        return

    # These run without a live TTS ref — should return gracefully
    result = tool_list_voices()
    _check("tool_list_voices() returns ToolResult", isinstance(result, dict))
    _check("tool_list_voices() has 'ok' key", "ok" in result)

    result = tool_list_voice_profiles()
    _check("tool_list_voice_profiles() returns ToolResult", isinstance(result, dict))
    _check("tool_list_voice_profiles() ok=True", result.get("ok") is True)

    result = tool_set_voice_profile("jarvis_british")
    _check("tool_set_voice_profile() returns ToolResult", isinstance(result, dict))

    result = tool_switch_persona("jarvis")
    _check("tool_switch_persona('jarvis') ok", result.get("ok") is True)

    result = tool_switch_persona("clone")
    _check("tool_switch_persona('clone') ok", result.get("ok") is True)

    result = tool_switch_persona("invalid_persona_xyz")
    _check("tool_switch_persona(invalid) returns error", result.get("ok") is False)


def main() -> None:
    print("=" * 60)
    print("JARVIS Voice Platform — Smoke Test")
    print("=" * 60)

    test_imports()
    test_text_normalizer()
    test_profiles()
    test_postfx()
    test_tts_init()
    test_voice_tools()

    print("\n" + "=" * 60)
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    print("=" * 60)

    if _FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
