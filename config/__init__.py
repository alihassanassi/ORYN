"""
config/__init__.py — J.A.R.V.I.S. global constants and paths.

All color tokens, font choices, filesystem paths, safety lists, and
app-level knobs live here. Import this first; nothing else does.

NOTE: config is now a package so that config.network can coexist.
      All constants from the original config.py live here in __init__.py.
      Import pattern unchanged: from config import P, OLLAMA_MODEL, etc.
"""
from __future__ import annotations
import os
from pathlib import Path

# ── Filesystem roots ──────────────────────────────────────────────────────────
ROOT_DIR    = Path(__file__).parent.parent.resolve()   # jarvis_lab root (one level up from config/)
DB_PATH     = ROOT_DIR / "jarvis.db"
BACKUP_DIR  = ROOT_DIR / "jarvis_backups"
PATCH_DIR   = ROOT_DIR / "jarvis_patches"
EVO_STATE   = ROOT_DIR / "jarvis_evo_state.json"
REPORTS_DIR = ROOT_DIR / "reports"

# ── Kokoro neural TTS (primary) ───────────────────────────────────────────────
KOKORO_MODEL_DIR = Path(r"C:\kokoro")
KOKORO_VOICE     = "bm_george"
KOKORO_SPEED     = 1.0

PERSONA_VOICES: dict[str, dict] = {
    "jarvis": {"voice": "bm_george", "speed": 1.0},
    "india":  {"voice": "bf_emma",   "speed": 0.95},
    "ct7567": {"voice": "bm_lewis",  "speed": 1.1},
    "morgan": {"voice": "am_michael","speed": 0.85},
}

# ── ElevenLabs cloud TTS (optional primary voice, used when API key is set) ──
ELEVENLABS_API_KEY: str = ""

ELEVENLABS_VOICES: dict = {
    "jarvis": "21m00Tcm4TlvDq8ikWAM",
    "india":  "AZnzlk1XvdvUeBnXmlld",
    "ct7567": "VR6AewLTigWG4xSOukaG",
}

# ── Piper neural TTS (secondary fallback) ─────────────────────────────────────
PIPER_EXE    = Path(r"C:\piper\piper.exe")
PIPER_VOICES = Path(r"C:\piper\voices")
PIPER_VOICE_PREFS = [
    "en_GB-alan-medium",
    "en_GB-cori-high",
    "en_US-ryan-high",
    "en_US-lessac-high",
    "en_US-arctic-medium",
]

# ── Audio I/O routing ─────────────────────────────────────────────────────────
AUDIO_INPUT_KW     = "logitech"
AUDIO_OUTPUT_KW    = "logitech"
AUDIO_INPUT_INDEX  = None
AUDIO_OUTPUT_INDEX = None
AUDIO_DEBUG        = True

# ── STT Voice Activity Detection (VAD) ────────────────────────────────────────
STT_SILENCE_THRESHOLD     = 0.015
STT_START_THRESHOLD       = 0.038
STT_MAX_RECORD_SECS       = 30
STT_END_SILENCE_MS        = 800
STT_PRE_SPEECH_TIMEOUT_MS = 8000
STT_MIN_SPEECH_MS         = 400

# ── Ollama LLM ────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL   = "http://127.0.0.1:11434/v1"
OLLAMA_MODEL      = "qwen3:14b"
OLLAMA_KEEP_ALIVE = -1
OLLAMA_OPTIONS    = {
    "think":        False,
    "temperature":  0.7,
    "top_p":        0.9,
    "num_ctx":      4096,
    "num_predict":  350,
    "num_batch":    512,
    "num_gpu":      99,
    "main_gpu":     0,
    "low_vram":     False,
    "f16_kv":       True,
    "use_mmap":     True,
    "use_mlock":    True,
}

OLLAMA_JUDGE_OPTIONS = {
    "think":        False,
    "temperature":  0.1,
    "num_ctx":      1024,
    "num_predict":  80,
    "num_batch":    256,
    "num_gpu":      99,
}

LLM_PREWARM_ON_BOOT = True

# ── Command safety ────────────────────────────────────────────────────────────
BLOCKED_COMMANDS = [
    "format c:",
    "format d:",
    "mkfs /dev/sda",
    "> /dev/sda",
    "dd if=/dev/zero of=/dev/sd",
    ":(){:|:&};:",
    "Remove-Item -Recurse -Force",
    "Remove-Item -Force -Recurse",
    "rd /s /q",
    "rmdir /s /q",
    "net user",
    "reg delete",
    "sc delete",
    "Stop-Service -Force",
    "Disable-NetAdapter",
    "Set-ExecutionPolicy Unrestricted",
    "Set-ExecutionPolicy Bypass",
    "cipher /w",
    "sdelete",
    "del /f /s /q",
    "takeown /f",
    "icacls.*\\/grant.*Everyone",
    "bcdedit",
    "diskpart",
    "format ",
]

# ── .env loader ───────────────────────────────────────────────────────────────
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
    del _ef, _line, _k, _v

# ── Bridge token ──────────────────────────────────────────────────────────────
JARVIS_TOKEN: str | None = None


def _get_jarvis_token() -> str:
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("JARVIS_TOKEN="):
                return line.split("=", 1)[1].strip()
    token = os.environ.get("JARVIS_TOKEN")
    if token:
        return token
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
AGENT_RUNTIME_ENABLED:   bool = True
AGENT_RUNTIME_MAX_STEPS: int  = 5

# ── Active persona ────────────────────────────────────────────────────────────
ACTIVE_PERSONA: str = "jarvis"

# ── Speech behavior ───────────────────────────────────────────────────────────
ALWAYS_SPEAK = True

# ── Voice platform ─────────────────────────────────────────────────────────────
VOICE_DEFAULT_PROFILE: str | None = "chatterbox_jarvis"
VOICE_POSTFX_ENABLED: bool = True

# ── Chatterbox neural TTS backend ──────────────────────────────────────────────
CHATTERBOX_DEVICE        : str   = "cuda"
CHATTERBOX_DEFAULT_EXAGG : float = 0.5
CHATTERBOX_REFERENCE_DIR : str   = "voice/reference_clips"
CHATTERBOX_REQUIRE_GPU   : bool  = False

# ── Theme system ──────────────────────────────────────────────────────────────
GUI_DEFAULT_THEME      = "CIRCUIT"
GUI_DEFAULT_BRIGHTNESS = 1.0

# ── Design system — HUD color palette ────────────────────────────────────────
P: dict[str, str] = {
    "void":    "#080e1a",
    "base":    "#0e1621",
    "surface": "#162840",
    "card":    "#1a3048",
    "input":   "#0a1829",
    "b0":      "#1a2d42",
    "b1":      "#1f3855",
    "b2":      "#264566",
    "arc":     "#18e0c1",
    "arc_d":   "#0fa896",
    "arc_g":   "#18e0c114",
    "arc_m":   "#14c8b0",
    "amber":   "#ffa020",
    "amber_d": "#6a3f08",
    "green":   "#00e87a",
    "red":     "#ff3355",
    "blue":    "#3aa0ff",
    "purple":  "#aa66ff",
    "t0":      "#e6f2ff",
    "t1":      "#b8d4e8",
    "t2":      "#6b9ab8",
    "t3":      "#3d5f76",
}

# ── Presentation ─────────────────────────────────────────────────────────────
DETAIL_SEP = "\n\x1edetail\x1e\n"

# ── Typography ────────────────────────────────────────────────────────────────
MONO    = "JetBrains Mono"
DISPLAY = "Rajdhani"
MONO_CSS    = f"'{MONO}', Consolas, 'Courier New', monospace"
DISPLAY_CSS = f"'{DISPLAY}', 'Segoe UI', Arial, sans-serif"

# ── Center identity element ────────────────────────────────────────────────────
CENTER_ELEMENT: str = "ai_core"

# ── Autonomous Recon Loop ─────────────────────────────────────────────────────
RECON_LOOP_ENABLED   : bool  = False
RECON_LOOP_INTERVAL  : int   = 300
RECON_AUTO_APPROVE   : bool  = False
RECON_MAX_CONCURRENT : int   = 2
RECON_QUIET_HOURS    : list  = [(22, 8)]
RECON_STALENESS_HOURS: int   = 24
RECON_MAX_DAILY_JOBS : int   = 10

# ── Research Intelligence Engine ─────────────────────────────────────────────
RESEARCH_ENGINE_ENABLED : bool = False
RESEARCH_POLL_INTERVAL  : int  = 3600
NVD_API_KEY             : str  = ""
RESEARCH_MAX_KEYWORDS   : int  = 5

# ── Threat Intelligence Correlator ───────────────────────────────────────────
INTEL_CORRELATOR_ENABLED       : bool  = False
INTEL_CORRELATOR_INTERVAL_SECS : int   = 3600
INTEL_CORRELATOR_MIN_SCORE     : float = 0.70
INTEL_HACKTIVITY_ENABLED       : bool  = False

# ── Local Intelligence Layer ──────────────────────────────────────────────────
LOCAL_JUDGE_MODEL    : str = "phi4-mini:latest"
OLLAMA_HOST          : str = "http://127.0.0.1:11434"

# ── UI Sound Engine ────────────────────────────────────────────────────────────
UI_SOUNDS_ENABLED    : bool  = True
UI_SOUND_VOLUME      : float = 0.7

# ── Wake Word Engine ───────────────────────────────────────────────────────────
WAKE_WORDS: list = [
    "jarvis", "hey jarvis", "hey j",
    "daddy's home", "jarvis wake up", "jarvis im home",
]
WAKE_ACTIVE_WINDOW_SECS: int  = 30
AMBIENT_LISTENING_ENABLED: bool = True

# ── Coaching Engine ────────────────────────────────────────────────────────────
COACHING_ENABLED                    : bool = True
COACHING_PAUSE_THRESHOLD_SECS       : int  = 30
COACHING_MAX_SUGGESTIONS_PER_SESSION: int  = 5

# ── Hunt Director ──────────────────────────────────────────────────────────────
HUNT_DIRECTOR_ENABLED          : bool  = False
HUNT_AUTO_APPROVE_THRESHOLD    : float = 0.0   # 0.0 = disabled; NEVER raise without operator review
HUNT_PROPOSAL_INTERVAL_SECS    : int   = 300
HUNT_MAX_PROPOSALS_PER_DAY     : int   = 20
