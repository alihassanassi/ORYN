# JARVIS Lab — Architecture Reference
**Last updated:** 2026-03-16
**Status:** Current (post-ENDGAME Audit, post-Security Audit, post-Model Upgrade)

---

## 1. Overview

JARVIS is a local AI operations console designed for cybersecurity work. It runs entirely on-device:
no cloud API calls, no external telemetry. All inference is handled by a local Ollama instance.

---

## 2. Five-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Layer 5 — AUTONOMY                                     │
│  autonomy/  · scheduler/  · runtime/  · policy/         │
├─────────────────────────────────────────────────────────┤
│  Layer 4 — GUI                                          │
│  gui/main_window.py (monolithic)  · gui/splash.py       │
│  gui/widgets/  · gui/settings_panel.py                  │
├─────────────────────────────────────────────────────────┤
│  Layer 3 — AGENTS / TOOLS                               │
│  agents/worker.py  · tools/  · audio/  · voice/         │
├─────────────────────────────────────────────────────────┤
│  Layer 2 — STORAGE                                      │
│  storage/db.py  · storage/audit_log.py                  │
│  storage/settings_store.py  · jarvis.db  · audit_log.db │
├─────────────────────────────────────────────────────────┤
│  Layer 1 — CONFIG                                       │
│  config.py  · security/  · llm/  · bridge/              │
└─────────────────────────────────────────────────────────┘
```

Data flows bottom-up: config is consumed by all layers; storage is written by agents and read by GUI;
tools are dispatched by agents; the GUI orchestrates everything.

---

## 3. LLM Stack

| Role | Model | Backend | VRAM |
|------|-------|---------|------|
| Primary LLM | `qwen3:14b` Q4_K_M | Ollama at `http://localhost:11434/v1` | ~9 GB |
| Local Judge | `phi4-mini:latest` Q4_K_M | Ollama (same instance) | ~2.5 GB |

**Key config values (config.py):**
- `OLLAMA_MODEL = "qwen3:14b"`
- `LOCAL_JUDGE_MODEL = "phi4-mini:latest"`
- `OLLAMA_KEEP_ALIVE = "2m"` — unloads after 2 minutes of inactivity (enables Chatterbox cohabitation)
- `OLLAMA_OPTIONS = {"think": False}` — Qwen3 chain-of-thought disabled by default

**Thinking mode:** Send `/think` as first word to enable per-query reasoning (+2-5 seconds latency).
`llm/client.py` strips all `<think>...</think>` blocks via `_strip_think()` regardless.

**Personas (llm/prompts.py):** jarvis (default), india, ct7567, morgan

**Routing:** `llm/router.py` — `LLMRouter` class with `route()`, `get_token_stats()`, `_log_routing()`.

---

## 4. Voice Stack

### TTS (Text-to-Speech)

Fallback chain — each backend tried in order until one succeeds:

```
Chatterbox (GPU/CPU)  →  Kokoro ONNX  →  Piper  →  Windows SAPI
```

| Backend | File | Notes |
|---------|------|-------|
| Chatterbox | `voice/backends/chatterbox_backend.py` | GPU preferred; ~6.8 GB VRAM; requires cuDNN 9.x |
| Kokoro ONNX | `voice/backends/kokoro_backend.py` | CPU-capable; primary fallback |
| Piper | `voice/backends/piper_backend.py` | Offline neural TTS |
| SAPI | `voice/backends/sapi_backend.py` | Windows built-in; always available |

**Orchestrator:** `voice/tts.py` — public API: `speak()`, `interrupt()`, `is_speaking()`, `set_profile()`
**Profiles:** `voice/profiles.py` — `VoiceProfile`, `PROFILES`, `PERSONA_TO_PROFILE`
**Default profile:** `chatterbox_jarvis` (set in config.py)
**ALWAYS_SPEAK:** `True` in config.py — TTS fires regardless of the voice toggle
**Voice toggle** controls STT (microphone) only when ALWAYS_SPEAK is enabled
**TTS truncation:** `speak()` cleans markdown, truncates to 3 sentences / 280 chars

**VRAM sequencing:** LLM unloads after `KEEP_ALIVE=2m`; Chatterbox then loads. Never simultaneous.
Peak VRAM during conversation: ~11.5 GB (qwen3 + phi4). Peak during TTS only: ~6.8 GB.

### STT (Speech-to-Text)

**Engine:** faster-whisper
**File:** `voice/stt.py` — DO NOT TOUCH
**Microphone:** Logitech PRO X Wire

### Wake Word Detection

**File:** `voice/wake_listener.py` — NEW (Agent 03)
**Trigger:** Ambient listening detects wake words and routes to STT queue.
Config keys `WAKE_WORDS` and `AMBIENT_LISTENING_ENABLED` added by Agent 03.

---

## 5. GUI Architecture

**Framework:** PySide6
**Entry:** `main.py` → `gui/main_window.py` → `JARVIS(QMainWindow)`

### Layout (3-column)

```
┌──────────────┬────────────────────────┬──────────────┐
│ Left 280px   │   Center (flex)        │ Right 460px  │
│              │                        │              │
│ Telemetry    │   OrbCanvas            │  ChatPanel   │
│ (stats,      │   + CameraFeed         │  (top)       │
│  weather,    │                        ├──────────────┤
│  projects,   │   3 control buttons    │  Terminal    │
│  actions)    │                        │  Panel       │
│              │                        │  (bottom)    │
└──────────────┴────────────────────────┴──────────────┘
```

**CRITICAL:** All panel logic is **monolithic in `gui/main_window.py`**.
`gui/panels/__init__.py` exists but is empty. There are no separate panel files.

### GUI Files

| File | Contents |
|------|----------|
| `gui/main_window.py` | JARVIS QMainWindow — all panels inline, backend wiring, topbar, waveform, input bar, statusbar |
| `gui/splash.py` | JarvisSplash — animated Iron Man HUD boot screen (60fps, rings, arcs, progress bar, 8-message ticker) |
| `gui/widgets/__init__.py` | ArcReactor, PTT, ThinkDots, WaveformVisualizer, Bubble, ProposalCard |
| `gui/widgets.py` | Legacy widgets file (superseded by package) |
| `gui/settings_panel.py` | Settings UI panel |

### AI State Machine

`_set_ai_state(mode)` at `gui/main_window.py` updates arc + waveform + topbar label atomically.
States: `IDLE` · `THINKING` · `LISTENING` · `EXECUTING`

### Chat Rendering

`DETAIL_SEP = "\n\x1edetail\x1e\n"` — separator between summary sentence and detail block in Bubble.
TTS speaks the summary only (splits on DETAIL_SEP before calling `speak()`).

---

## 6. Agent / Tool Layer

### AgentWorker (`agents/worker.py`)

- Keyword routing: `_KEYWORD_RULES` (15+ deterministic patterns) — matched before LLM
- Direct tools: `_DIRECT_TOOLS` — tools called without LLM round-trip
- Tool summarization: `_tool_summary()` — deterministic one-sentence summaries for 30+ tools
- Reply formatting: `_format_tool_reply()`
- Interrupt patterns: `_INTERRUPT_PATTERNS` — phrases that trigger `tts.interrupt()`

### Tool Registry (`tools/registry.py`)

`TOOL_SCHEMAS` — OpenAI-format JSON schema list consumed by LLM for tool-calling.
`dispatch()` — routes tool name → implementation function.

### Tools

| File | Tools |
|------|-------|
| `tools/system_tools.py` | CPU, RAM, disk, network, process inspection; file ops with path-boundary guard |
| `tools/shell_tools.py` | `run_command` (PowerShell, confirm-gated), `open_app` (APP_MAP allowlist) |
| `tools/voice_tools.py` | `list_voices`, `set_voice` |
| `tools/project_tools.py` | projects, notes, proposals, save_target, list_targets, save_finding, list_findings |
| `tools/report_tools.py` | Report generation tools |

**Note:** `tools/network_tools.py` and `tools/document_tools.py` are NOT present on disk.
DNS/WHOIS/geolocate stubs and PDF/YouTube tools from earlier memory entries no longer exist.

### UI Sound Engine (`audio/`)

**Files:** `audio/__init__.py`, `audio/sound_engine.py`
**Added by:** PATCH P1
**One-time setup:** Run `python generate_sounds.py` to synthesize WAV files into `assets/sounds/`
**Note:** `assets/sounds/` directory does not exist yet — created when `generate_sounds.py` runs.
Config keys: `UI_SOUNDS_ENABLED = True`, `UI_SOUND_VOLUME = 0.7` (added by P1).

---

## 7. Storage Layer

**Primary DB:** `jarvis.db` (SQLite, via `storage/db.py`)

| Table | Purpose |
|-------|---------|
| projects | Named projects |
| messages | Conversation history |
| commands | Command history |
| scan_targets | Recon scope targets |
| ambient_log | Wake-word / ambient event log (Agent 03) |

**Audit DB:** `audit_log.db` — hash-chained `ImmutableAuditLog` (`storage/audit_log.py`)
**Settings:** `storage/settings_store.py`
**Path anchoring:** All DB/flag paths anchored to `config.ROOT_DIR` — immune to CWD variation.

---

## 8. Autonomy Layer

### Recon Loop (`autonomy/recon_loop.py`)

`RECON_LOOP_ENABLED = False` in config — must be explicitly enabled by operator.

7-gate safety chain (all fail-closed):
1. Kill switch check
2. Quiet hours check
3. Daily budget check
4. Scope validation (`validate_domain()` + `is_in_scope()`)
5. Wildcard confirmation
6. Domain validation
7. Policy engine approval

### Scheduler

| File | Purpose |
|------|---------|
| `scheduler/recon_scheduler.py` | Timed recon job scheduler |
| `scheduler/morning_briefing.py` | Weather + intel briefing on startup (PATCH P4) |

### Runtime Safety

| File | Purpose |
|------|---------|
| `runtime/kill_switch.py` | Dual-mechanism stop: Python state + `EMERGENCY_STOP.flag` filesystem flag |
| `runtime/watchdog.py` | Health checks for Ollama and other services |
| `runtime/integrity.py` | SHA256 baseline tamper detection for entry points |
| `runtime/boot_manager.py` | Startup sequencing |

### Policy Engine

| File | Purpose |
|------|---------|
| `policy/autonomy_policy.py` | `AutonomyPolicyEngine` — governs what autonomous actions are permitted |
| `policy/engine.py` | Core policy evaluation |

### Other Autonomy

| File | Purpose |
|------|---------|
| `autonomy/finding_engine.py` | Stores findings to `reports_encrypted/` |
| `autonomy/preference_engine.py` | Learns operator preferences over time |
| `agents/autonomous.py` | Autonomous agent loop with ProposalCard approval queue |
| `agents/monitor.py` | System monitoring agent |

---

## 9. Security Architecture

All security controls documented in `SECURITY_REPORT.md`. Summary:

- **Shell confirmation gate:** `_SAFE_COMMANDS` tight allowlist; all mutations require `confirmed=True`
- **Prompt injection:** `security/sanitizer.py` — `wrap_untrusted()` envelopes all external data; `JARVIS_PERSONA` instructs model to treat `<untrusted_data>` tags as data boundaries
- **SQL injection:** All `storage/db.py` queries use `?` parameterization
- **Subprocess safety:** No `shell=True` anywhere; `tool_open_app` enforces APP_MAP allowlist
- **Path anchoring:** Kill flag, audit DB, integrity baseline, reports dir all anchored to `ROOT_DIR`
- **Secrets:** Windows DPAPI via `security/secrets.py` + `keyring`; no hardcoded fallbacks

**Remaining operator-action items (from SECURITY_REPORT.md):**
- `voice/tts.py:632` — PATH_INTERPOLATION_INTO_POWERSHELL (voice pipeline off-limits)
- `agents/autonomous.py:144` — AUTONOMOUS_APPROVAL_BYPASSES_ALLOWLIST
- `requirements.txt` — run `pip freeze > requirements.txt` then `pip-audit`

---

## 10. Key Config Values (config.py)

```python
OLLAMA_MODEL           = "qwen3:14b"
LOCAL_JUDGE_MODEL      = "phi4-mini:latest"
OLLAMA_KEEP_ALIVE      = "2m"
VOICE_DEFAULT_PROFILE  = "chatterbox_jarvis"
ACTIVE_PERSONA         = "jarvis"
ALWAYS_SPEAK           = True
RECON_LOOP_ENABLED     = False
UI_SOUNDS_ENABLED      = True    # added P1
UI_SOUND_VOLUME        = 0.7     # added P1
```

---

## 11. Hardware Context

| Component | Spec |
|-----------|------|
| CPU | Intel i7-14700F |
| RAM | 64 GB |
| GPU | NVIDIA RTX 4070 Ti Super, 16 GB VRAM |
| OS | Windows 11 Home |
| Microphone | Logitech PRO X Wire |

---

## 12. Launch

```powershell
# Standard launch (recommended)
cd "c:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab"
.\JARVIS_START.ps1

# Direct launch
.\jarvis_env\Scripts\python.exe main.py
```

`JARVIS_START.ps1` performs: Ollama health check → auto-pull if model missing → background pre-warm → JARVIS launch.

---

*Architecture reference — Agent 04 DOCS-SYNC — 2026-03-16*
