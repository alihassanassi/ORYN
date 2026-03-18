"""
config.py — J.A.R.V.I.S. global constants and paths.

All color tokens, font choices, filesystem paths, safety lists, and
app-level knobs live here. Import this first; nothing else does.
"""
from __future__ import annotations
import os
from pathlib import Path

# ── Filesystem roots ──────────────────────────────────────────────────────────
ROOT_DIR    = Path(__file__).parent.resolve()
DB_PATH     = ROOT_DIR / "jarvis.db"
BACKUP_DIR  = ROOT_DIR / "jarvis_backups"
PATCH_DIR   = ROOT_DIR / "jarvis_patches"
EVO_STATE   = ROOT_DIR / "jarvis_evo_state.json"

# ── Kokoro neural TTS (primary) ───────────────────────────────────────────────
# pip install kokoro-onnx
# Download kokoro-v0_19.onnx + voices.bin from:
#   https://huggingface.co/hexgrad/Kokoro-82M/tree/main
# Place both files in KOKORO_MODEL_DIR.
KOKORO_MODEL_DIR = Path(r"C:\kokoro")   # must contain kokoro-v0_19.onnx + voices.bin
KOKORO_VOICE     = "bm_george"          # British Male George — default JARVIS voice
KOKORO_SPEED     = 1.0                  # 0.5 slow → 2.0 fast; 1.0 = natural pace

# Per-persona voice IDs — used ONLY for Kokoro warmup preloading (kokoro_backend.py).
# Voice selection for synthesis is controlled exclusively by voice/profiles.py.
# Keep in sync with profile voice_id values or warmup will load wrong voices.
PERSONA_VOICES: dict[str, dict] = {
    "jarvis": {"voice": "bm_george", "speed": 1.0},   # British Male George — classic JARVIS
    "india":  {"voice": "bf_emma",   "speed": 0.95},  # British Female Emma — warm, formal
    "ct7567": {"voice": "bm_lewis",  "speed": 1.1},   # British Male Lewis, faster — clipped
    "morgan": {"voice": "am_michael","speed": 0.85},  # American Male Michael — slow, weighty
}

# ── ElevenLabs cloud TTS (optional primary voice, used when API key is set) ──
# When set, ElevenLabs is used first; Kokoro/SAPI are silent fallbacks.
# Get free key at elevenlabs.io (10k chars/month free)
ELEVENLABS_API_KEY: str = ""

ELEVENLABS_VOICES: dict = {
    "jarvis": "21m00Tcm4TlvDq8ikWAM",
    "india":  "AZnzlk1XvdvUeBnXmlld",
    "ct7567": "VR6AewLTigWG4xSOukaG",
}

# ── Piper neural TTS (secondary fallback) ─────────────────────────────────────
# Optional. Only used if Kokoro model files are absent.
# Download binary from: https://github.com/rhasspy/piper/releases
PIPER_EXE    = Path(r"C:\piper\piper.exe")
PIPER_VOICES = Path(r"C:\piper\voices")
PIPER_VOICE_PREFS = [
    "en_GB-alan-medium",       # British male
    "en_GB-cori-high",
    "en_US-ryan-high",
    "en_US-lessac-high",
    "en_US-arctic-medium",
]

# ── Audio I/O routing ─────────────────────────────────────────────────────────
# Priority: explicit index (if set and valid) → keyword match → system default.
# Keywords are case-insensitive substrings of the sounddevice device name.
AUDIO_INPUT_KW     = "logitech"  # substring to match microphone device name
AUDIO_OUTPUT_KW    = "logitech"  # substring to match speaker/output device name
AUDIO_INPUT_INDEX  = None       # int: pin to exact sounddevice index; None = auto
AUDIO_OUTPUT_INDEX = None       # int: pin to exact sounddevice index; None = auto
AUDIO_DEBUG        = True       # print device selection logs on startup

# ── STT Voice Activity Detection (VAD) ────────────────────────────────────────
# All thresholds are RMS energy on float32 audio in [-1, 1].
STT_SILENCE_THRESHOLD     = 0.015   # RMS below this = silence
STT_START_THRESHOLD       = 0.038   # RMS above this = speech has started
STT_MAX_RECORD_SECS       = 30      # hard cap on utterance length (seconds)
STT_END_SILENCE_MS        = 800     # trailing silence (ms) after speech to stop
STT_PRE_SPEECH_TIMEOUT_MS = 8000    # give up if no speech within this many ms
STT_MIN_SPEECH_MS         = 400     # discard utterances shorter than this

# ── Ollama LLM ────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL   = "http://127.0.0.1:11434/v1"
OLLAMA_MODEL      = "qwen3:14b"        # RTX 4070 Ti Super 16GB: ~9GB VRAM, ~60 t/s, best tool-call
OLLAMA_KEEP_ALIVE = "2m"               # unload from VRAM 2min after last use → frees space for Chatterbox
OLLAMA_OPTIONS    = {
    "num_ctx":        4096,
    "num_gpu":        99,
    "num_thread":     8,
    "num_predict":    180,             # hard cap; max_tokens in client.py is the binding limit
    "temperature":    0.3,
    "repeat_penalty": 1.1,
    "think":          False,           # Qwen3: disable chain-of-thought for agent loop speed
}

# ── Command safety ────────────────────────────────────────────────────────────
BLOCKED_COMMANDS = [
    # ── Original entries ──────────────────────────────────────────────────────
    "format c:",
    "format d:",
    "mkfs /dev/sda",
    "> /dev/sda",
    "dd if=/dev/zero of=/dev/sd",
    ":(){:|:&};:",
    # ── Windows-destructive additions ─────────────────────────────────────────
    "Remove-Item -Recurse -Force",
    "Remove-Item -Force -Recurse",
    "rd /s /q",
    "rmdir /s /q",
    "net user",                        # user account manipulation
    "reg delete",                      # registry deletion
    "sc delete",                       # service deletion
    "Stop-Service -Force",
    "Disable-NetAdapter",
    "Set-ExecutionPolicy Unrestricted",
    "Set-ExecutionPolicy Bypass",
    "cipher /w",                       # DoD wipe
    "sdelete",                         # secure delete
    "del /f /s /q",                    # force-delete all recursive
    "takeown /f",                      # take ownership
    "icacls.*\\/grant.*Everyone",      # grant everyone permissions
    "bcdedit",                         # boot config edit
    "diskpart",                        # disk partitioning
    "format ",                         # generic format (space prevents false match on "format c:" above)
]

# ── .env loader ───────────────────────────────────────────────────────────────
# Reads jarvis_lab/.env (KEY=VALUE pairs, # comments supported) into os.environ
# before any module reads environment variables.  Shell-exported vars always win
# (existing env is never overwritten).  .env is NEVER version-controlled —
# see .env.example for the expected format.
_ENV_FILE = ROOT_DIR / ".env"
if _ENV_FILE.exists():
    _k = _v = None
    with _ENV_FILE.open(encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _k = _k.strip()
                if _k and _k not in os.environ:
                    os.environ[_k] = _v.strip()
    del _ef, _line, _k, _v   # don't leak loop vars into module namespace

# ── Bridge token ──────────────────────────────────────────────────────────────
# Token is loaded from (in priority order):
#   1. JARVIS_TOKEN in jarvis_lab/.env
#   2. JARVIS_TOKEN env var (shell export)
#   3. Development fallback "jarvis_local_token" (local dev only)
# Do NOT put a real token in this file; use .env instead.
JARVIS_TOKEN: str | None = None


def _get_jarvis_token() -> str:
    """Return JARVIS_TOKEN from .env or env var. Returns None if not configured.

    NOTE: The previous hardcoded fallback 'jarvis_local_token' has been removed.
    Set JARVIS_TOKEN in .env or as an environment variable for bridge auth.
    """
    # Check .env file first
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("JARVIS_TOKEN="):
                return line.split("=", 1)[1].strip()
    # Check environment variable
    token = os.environ.get("JARVIS_TOKEN")
    if token:
        return token
    # No token configured — return None so callers can detect unconfigured state
    return None


APP_MAP: dict[str, str] = {
    "terminal":   "wt.exe",
    "cmd":        "cmd.exe",
    "powershell": "powershell.exe",
    "chrome":     r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "browser":    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "vscode":     "code",
    "code":       "code",
    "wireshark":  r"C:\Program Files\Wireshark\Wireshark.exe",
    "burpsuite":  r"C:\Program Files\BurpSuiteCommunity\BurpSuiteCommunity.exe",
    "burp":       r"C:\Program Files\BurpSuiteCommunity\BurpSuiteCommunity.exe",
    "notepad":    "notepad.exe",
    "explorer":   "explorer.exe",
    "files":      "explorer.exe",
}

# ── Agent runtime ─────────────────────────────────────────────────────────────
# Internal local-first agent loop (runtime/agent_runtime.py).
# Disable to prevent automated tool execution from the planner loop.
AGENT_RUNTIME_ENABLED:   bool = True   # set False to disable local agent loop
AGENT_RUNTIME_MAX_STEPS: int  = 5      # max planning+execution steps per run

# ── Autonomous proposal agent ─────────────────────────────────────────────────
AUTO_AGENT_PROPOSAL_INTERVAL_SECS: int = 300  # 5 minutes between proposals
AUTO_AGENT_MAX_PENDING:            int = 5    # max proposals waiting at once

# ── Active persona ────────────────────────────────────────────────────────────
# One of: "jarvis" | "india" | "ct7567"
# Changed at runtime by tools.persona_tools.tool_switch_persona()
# and by GUI persona buttons in gui/main_window.py.
ACTIVE_PERSONA: str = "jarvis"

# ── Speech behavior ───────────────────────────────────────────────────────────
# When True, JARVIS speaks all responses automatically.
# The voice toggle controls STT (microphone) only.
# Set False to require the voice toggle to be on before JARVIS speaks.
ALWAYS_SPEAK = True

# ── Voice platform (Phase VOICE-PLATFORM) ─────────────────────────────────────
# Default voice profile (voice/profiles.py).
# None = auto-derive from ACTIVE_PERSONA on every utterance.
# Explicit name = use that profile regardless of persona.
# "chatterbox_jarvis" is safe with qwen3:14b: LLM generates text, then unloads
# (OLLAMA_KEEP_ALIVE="2m"), then Chatterbox loads ~6.8GB — fully sequential,
# peak simultaneous VRAM is never ~15GB. Both fit comfortably on 16GB.
VOICE_DEFAULT_PROFILE: str | None = "chatterbox_jarvis"

# Post-processing FX chains (voice/postfx.py).
# Set False to disable all FX for minimum latency / diagnostic mode.
VOICE_POSTFX_ENABLED: bool = True

# ── Chatterbox neural TTS backend (Phase CHATTERBOX) ──────────────────────────
# Resemble AI Chatterbox — MIT license, runs 100% locally on CUDA GPU.
# Supports zero-shot voice cloning from a 5–30 s reference WAV clip.
# VRAM requirement: ~6.8 GB (fits on RTX 4070 Ti Super 16 GB alongside Ollama).
CHATTERBOX_DEVICE        : str       = "cuda"          # "cuda" or "cpu"
CHATTERBOX_DEFAULT_EXAGG : float     = 0.5             # default emotion exaggeration
CHATTERBOX_REFERENCE_DIR : str       = "voice/reference_clips"  # reference WAV directory
CHATTERBOX_REQUIRE_GPU   : bool      = False           # warn but don't crash if GPU unavailable

# ── Theme system ──────────────────────────────────────────────────────────────
GUI_DEFAULT_THEME      = "CIRCUIT"
GUI_DEFAULT_BRIGHTNESS = 1.0

# ── Design system — HUD color palette ────────────────────────────────────────
P: dict[str, str] = {
    # Backgrounds (4 layers of depth)
    "void":    "#080e1a",
    "base":    "#0e1621",
    "surface": "#162840",
    "card":    "#1a3048",
    "input":   "#0a1829",

    # Borders
    "b0":      "#1a2d42",
    "b1":      "#1f3855",
    "b2":      "#264566",

    # Arc reactor signature — #18E0C1 teal
    "arc":     "#18e0c1",
    "arc_d":   "#0fa896",
    "arc_g":   "#18e0c114",
    "arc_m":   "#14c8b0",

    # Alerts
    "amber":   "#ffa020",
    "amber_d": "#6a3f08",

    # Status
    "green":   "#00e87a",
    "red":     "#ff3355",
    "blue":    "#3aa0ff",
    "purple":  "#aa66ff",

    # Text weights
    "t0":      "#e6f2ff",
    "t1":      "#b8d4e8",
    "t2":      "#6b9ab8",
    "t3":      "#3d5f76",
}

# ── Presentation ─────────────────────────────────────────────────────────────
# Sentinel that separates the one-sentence summary from the full detail block
# in operator replies. Worker produces it; Bubble consumes it for two-tier
# rendering. Must not appear in natural language or tool output.
DETAIL_SEP = "\n\x1edetail\x1e\n"

# ── Typography ────────────────────────────────────────────────────────────────
MONO    = "JetBrains Mono"
DISPLAY = "Rajdhani"

# CSS font stacks (updated at runtime by main.py after font probe)
MONO_CSS    = f"'{MONO}', Consolas, 'Courier New', monospace"
DISPLAY_CSS = f"'{DISPLAY}', 'Segoe UI', Arial, sans-serif"

# ── Center identity element ────────────────────────────────────────────────────
# "ai_core" → AICoreWidget  |  "face" → FaceSurface (original)
# Change this value to swap the center panel identity widget.
CENTER_ELEMENT: str = "ai_core"

# ── Autonomous Recon Loop ─────────────────────────────────────────────────────
# RECON_LOOP_ENABLED must be set True explicitly by the operator.
# All other flags are hard ceilings enforced in DB — not just memory.
RECON_LOOP_ENABLED   : bool       = False     # operator must explicitly enable
RECON_LOOP_INTERVAL  : int        = 300       # seconds between cycles
RECON_AUTO_APPROVE   : bool       = False     # RESERVED — always False — never auto-approve
RECON_MAX_CONCURRENT : int        = 2         # max simultaneous pipeline jobs
RECON_QUIET_HOURS    : list       = [(22, 8)] # 10pm–8am: no autonomous scanning
RECON_STALENESS_HOURS: int        = 24        # rescan threshold (hours)
RECON_MAX_DAILY_JOBS : int        = 10        # persisted daily circuit breaker

# ── Research Intelligence Engine ─────────────────────────────────────────────
RESEARCH_ENGINE_ENABLED : bool = False   # set True to enable background CVE polling
RESEARCH_POLL_INTERVAL  : int  = 3600    # seconds between research cycles
NVD_API_KEY             : str  = ""      # optional: unlocks 50 req/30s (vs 5 req/30s)
RESEARCH_MAX_KEYWORDS   : int  = 5       # max target keywords sent per NVD query

# ── Local Intelligence Layer ──────────────────────────────────────────────────
# LocalJudge uses a smaller/faster model for structured decisions.
# Cloud LLM (OLLAMA_MODEL) is used for complex reasoning and generation.
LOCAL_JUDGE_MODEL    : str        = "phi4-mini:latest"  # 3.8B, ~2.5GB VRAM, ~180 t/s, best JSON
OLLAMA_HOST          : str        = "http://127.0.0.1:11434"  # without /v1 path

# ── UI Sound Engine ────────────────────────────────────────────────────────────
# Iron Man HUD audio feedback layer (audio/sound_engine.py).
# Sounds are synthesized by generate_sounds.py → assets/sounds/*.wav
# Run once: python generate_sounds.py
UI_SOUNDS_ENABLED    : bool  = True
UI_SOUND_VOLUME      : float = 0.7   # 0.0 (silent) → 1.0 (full)

# ── Wake Word Engine ───────────────────────────────────────────────────────────
WAKE_WORDS: list = [
    "jarvis", "hey jarvis", "hey j",
    "daddy's home", "jarvis wake up", "jarvis im home",
]
WAKE_ACTIVE_WINDOW_SECS: int  = 30    # seconds to stay active after wake word
AMBIENT_LISTENING_ENABLED : bool = True    # always listening
AMBIENT_MEMORY_ENABLED    : bool = True    # extract memories from ambient audio
AMBIENT_MIN_WORDS         : int  = 5       # ignore very short fragments
AMBIENT_WHISPER_MODEL     : str  = "base"  # fast, small footprint

# ── Intelligence Layer Daemons ────────────────────────────────────────────────
INTEL_CORRELATOR_ENABLED   : bool = False   # cross-reference CVEs against targets
INTEL_HACKTIVITY_ENABLED   : bool = False   # watch HackerOne public disclosures
HUNT_DIRECTOR_ENABLED      : bool = False   # propose next recon targets
COACHING_ENABLED           : bool = True    # operator skill hints during pause windows
CONTEXT_PREDICTOR_ENABLED  : bool = False   # preload session context before operator sits down

# ── Response cache ────────────────────────────────────────────────────────────
RESPONSE_CACHE_ENABLED : bool = True   # cache deterministic read-only tool results in RAM
RESPONSE_CACHE_MAX_MB  : int  = 512    # ceiling — 512MB of 48GB free DDR5 (trivial overhead)

# ── Parallel tool execution ────────────────────────────────────────────────────
PARALLEL_TOOL_EXECUTION   : bool = True    # run I/O-bound tools concurrently (tools/registry.py)
PARALLEL_TOOL_MAX_WORKERS : int  = 6       # thread pool size for _TOOL_EXECUTOR

# ── Self-improvement engine ───────────────────────────────────────────────────
# JARVIS reviews his own responses every N conversations and proposes improvements.
# Proposals go through the standard operator approval pipeline — never auto-apply.
SELF_IMPROVEMENT_ENABLED : bool = True
SELF_IMPROVEMENT_TRIGGER : int  = 10  # conversations between self-review cycles

# Auto-agent: when True, shell/tool confirmations are auto-approved without
# waiting for operator click. Toggled live by the AUTONOMOUS AGENT panel button.
AUTO_AGENT_ENABLED       : bool = False

# ── Camera vision system ───────────────────────────────────────────────────────
# OFF by default — operator enables explicitly. All processing is local.
# Requires: pip install face-recognition opencv-python
VISION_ENABLED            : bool  = False  # OFF by default – operator enables
VISION_CAMERA_INDEX       : int   = 0      # webcam index (0 = default camera)
VISION_SCAN_INTERVAL_SECS : int   = 5      # seconds between scan cycles
VISION_FACE_TOLERANCE     : float = 0.5    # 0.0 = strictest, 1.0 = most lenient
SPEECH_FORMALITY          : str   = "casual"  # casual | neutral | formal
