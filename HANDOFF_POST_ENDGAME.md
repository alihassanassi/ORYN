# JARVIS Lab — Handoff: Post-ENDGAME State
**Date:** 2026-03-16
**Prepared by:** Agent 04 DOCS-SYNC

This document is the authoritative state summary for anyone (human or agent) picking up this
project after the ENDGAME agent wave. Read this before touching anything.

---

## Current System State

### What Works

| Component | Status | Notes |
|-----------|--------|-------|
| GUI launch | Working | `.\JARVIS_START.ps1` or direct python call |
| LLM (qwen3:14b) | Working | Ollama at localhost:11434; pre-warmed by start script |
| Local Judge (phi4-mini) | Working | ~180 t/s approve/deny decisions |
| TTS — Kokoro ONNX | Working | Primary working backend |
| TTS — Piper | Working | Fallback |
| TTS — SAPI | Working | Final fallback; always available |
| STT — faster-whisper | Working | DO NOT TOUCH `voice/stt.py` |
| Chat panel | Working | Bubble scroll, DETAIL_SEP summary/detail split |
| Tool dispatch | Working | registry.py + 5 tool modules |
| Recon loop | Disabled (safe) | `RECON_LOOP_ENABLED = False`; enable only when scoped |
| Kill switch | Working | Dual-mechanism: Python state + EMERGENCY_STOP.flag |
| Watchdog | Working | Monitors Ollama and services |
| Integrity check | Working | SHA256 baseline at fixed absolute path |
| Audit log | Working | Hash-chained ImmutableAuditLog at fixed absolute path |
| Morning briefing | Working | `scheduler/morning_briefing.py` on startup |
| UI sound engine | Code complete | Needs one-time `python generate_sounds.py` to create WAV files |
| Wake word detection | Partial | `voice/wake_listener.py` exists; STT queue integration is stub |
| Splash screen | Working | Animated HUD; sound augmentation wired (P2) |
| TTS interrupt | Working | Public `tts.interrupt()`; `_INTERRUPT_PATTERNS` in worker.py |
| Security hardening | Clean | 19 fixes applied; 3 operator-action items remain |
| Research engine | Code complete | Set RESEARCH_ENGINE_ENABLED=True to activate |
| Strategy engine | Working | `strategy_briefing` tool, feeds autonomous agent |
| TelemetryPanel | Extracted | Now in `gui/panels/telemetry_panel.py` |
| MiniHUD | Working | Ctrl+Shift+J overlay, shows last response + state |
| Center tabs | Working | CHAT / SCAN / RESEARCH view switcher |
| Network tools | Working | weather, dns, whois, geoip, subfinder, httpx, nuclei |
| Job executor | Working | Processes recon jobs (runs when RECON_LOOP_ENABLED=True) |
| Companion DB | Working | Operator skill tracking, adaptation hints in every LLM call |
| Response translator | Working | Persona-aware natural language for all recon tool output |

### What Is Pending / Incomplete

| Item | Details |
|------|---------|
| Chatterbox GPU | Backend exists but needs cuDNN 9.x — see below |
| Wake word STT integration | Stub — full queue wiring needs Agent 03 completion |
| `assets/sounds/` WAV files | Run `python generate_sounds.py` once |
| Agents 05–19 | COMPLETE — all delivered |
| `requirements.txt` | Not present; generate with `pip freeze > requirements.txt` |
| `ambient_log` DB table | Schema defined; may need migration run if DB already exists |
| Enable research engine | Set `RESEARCH_ENGINE_ENABLED = True` in config.py + optional `NVD_API_KEY` |
| Install recon tools | `go install` subfinder, httpx, nuclei for autonomous scanning |
| Enable recon loop | Set `RECON_LOOP_ENABLED = True` in config.py (then add programs to DB) |
| generate_sounds.py | Run once: `.\jarvis_env\Scripts\python.exe generate_sounds.py` |
| cuDNN for Chatterbox | `pip install nvidia-cudnn-cu12` for GPU TTS (CPU fallback works) |

---

## How to Launch

### Standard Launch (Recommended)

```powershell
cd "c:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab"
.\JARVIS_START.ps1
```

`JARVIS_START.ps1` does:
1. Checks Ollama is running (starts it if needed)
2. Verifies `qwen3:14b` and `phi4-mini` are pulled (auto-pulls if missing — takes several minutes first time)
3. Pre-warms models in background for low first-response latency
4. Launches `main.py` via the virtual environment

### Direct Launch

```powershell
cd "c:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab"
.\jarvis_env\Scripts\python.exe main.py
```

---

## One-Time Setup Steps

### 1. Pull LLM Models (if not yet done)

```powershell
ollama pull qwen3:14b
ollama pull phi4-mini
```

First pull: allow 5–15 minutes depending on connection speed.

### 2. Generate UI Sound Files

```powershell
cd "c:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab"
.\jarvis_env\Scripts\python.exe generate_sounds.py
```

This creates `assets/sounds/*.wav`. Run once. Safe to re-run if files are deleted.

### 3. Fix Chatterbox GPU (optional — CPU fallback works)

Install cuDNN 9.x for CUDA 12.x:

```powershell
.\jarvis_env\Scripts\pip.exe install nvidia-cudnn-cu12
```

Or download manually from https://developer.nvidia.com/cudnn (install system-wide).
After install, restart JARVIS — Chatterbox will auto-detect GPU.
Without cuDNN: Chatterbox runs on CPU (slow but functional); Kokoro ONNX picks up automatically.

### 4. Generate requirements.txt (for dependency auditing)

```powershell
cd "c:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab"
.\jarvis_env\Scripts\python.exe -m pip freeze > requirements.txt
.\jarvis_env\Scripts\pip.exe install pip-audit --quiet
.\jarvis_env\Scripts\python.exe -m pip_audit --requirement requirements.txt
```

---

## Known Issues

### Chatterbox on CPU — cuDNN Missing

**Symptom:** TTS falls through to Kokoro ONNX instead of Chatterbox. Voice quality is different.
**Cause:** cuDNN 9.x not installed. GPU has 16 GB VRAM — more than enough. Only the CUDA
dependency is missing.
**Fix:** `pip install nvidia-cudnn-cu12` or manual cuDNN install from NVIDIA developer site.
**Impact:** Non-blocking. Kokoro ONNX is the working fallback. Audio works.

### Shell Fork Failures

**Symptom:** Bash commands fail with `fork: Resource temporarily unavailable`.
**Cause:** JARVIS process holding resources when dev environment is running simultaneously.
**Fix:** Stop JARVIS before running shell validation commands. Or use PowerShell directly (not bash).
**Impact:** Dev/agent tooling only. Does not affect JARVIS runtime.

### ALWAYS_SPEAK vs _voice_on Disconnect

**Symptom:** `config.ALWAYS_SPEAK = True` but `main_window.py` gates TTS on `self._voice_on`.
**Current behavior:** Voice toggle controls both STT and TTS simultaneously (intentional per design).
**Impact:** Low. Voice toggle = STT-only semantics when ALWAYS_SPEAK is True is documented
in memory but not yet enforced in code. Existing behavior is stable.

### `gui/panels/` — Now Populated

`gui/panels/` now contains `telemetry_panel.py` (Agent 09) and `scan_graph.py` (Agent 08).
TelemetryPanel has been extracted from `gui/main_window.py` into its own module.
Additional panels may still have logic remaining in `main_window.py` — read the full file
before making further extractions.

### voice/tts.py Path Interpolation

ElevenLabs fallback branch interpolates a temp file path into a PowerShell f-string.
Voice pipeline is off-limits — operator must fix manually if using ElevenLabs.
ElevenLabs is not the active backend. Current active: Chatterbox → Kokoro → Piper → SAPI.
See `SECURITY_REPORT.md` for exact details.

---

## Critical Do-Not-Touch List

| File | Why |
|------|-----|
| `voice/stt.py` | Working STT pipeline. Any change risks breaking microphone input. No one touches this. |
| `voice/tts.py` | Working TTS pipeline. Known path-injection issue in ElevenLabs branch — operator aware. Agent 01/02 scope only for backend files. |
| `gui/main_window.py` | Monolithic. Read the entire file before editing. Agent 09 is the designated refactor agent. |

---

## Next Phase — Operator Actions

Agents 05–19 are complete. Remaining work is operator configuration and optional hardware upgrades.

| Priority | Action | Details |
|----------|--------|---------|
| High | Enable research engine | Set `RESEARCH_ENGINE_ENABLED = True` in config.py; optionally set `NVD_API_KEY` |
| High | Agent 01 — Chatterbox GPU | Install cuDNN — `pip install nvidia-cudnn-cu12` |
| Medium | Agent 02 — Persona Voice | Requires stable Chatterbox (Agent 01 first) |
| Medium | Agent 03 — Wake Word | Complete STT queue wiring in `voice/wake_listener.py` |
| Medium | Enable recon loop | Set `RECON_LOOP_ENABLED = True` after adding programs to DB |
| Low | Install recon tools | `go install` subfinder, httpx, nuclei for full autonomous scanning |

Before running any new agent: re-read `AUDIT_REPORT.md` for the current GO/NO-GO status and any
config keys that agent is expected to add.

---

## Continuation Session Additions (2026-03-16)

Work performed after the original ENDGAME wave (operator instruction: "keep going"):

| Item | File | Details |
|------|------|---------|
| Program management tools | `tools/program_tools.py` | 6 tools: list_programs, create_program, add_scope, program_status, set_program_status, scope_check |
| `scope_check` tool | `tools/program_tools.py` | Verify domain is in scope for a program; calls `bridge/scope.py::is_in_scope` |
| `_TOOL_RE` expansion | `agents/worker.py` | Added 40+ keyword patterns covering all new tools (program, scope, finding, briefing, research, weather, dns, strategy, etc.) |
| Research polling loop | `runtime/boot_manager.py` | Step 10: periodic `ResearchEngine.run()` every `RESEARCH_POLL_INTERVAL` secs (gated on `RESEARCH_ENGINE_ENABLED`) |
| Updated capabilities | `tools/network_tools.py` | `tool_list_capabilities()` now lists all 40+ tools across 8 categories |

**Operator workflow enabled by program management tools:**
1. `"create program Shopify hackerone shopify.com,*.shopify.com"` → creates program
2. `"scope check 1 api.shopify.com"` → instantly verifies in-scope
3. `"save target shopify.com"` → adds to active project for strategy tracking
4. `"start recon loop"` → if `RECON_LOOP_ENABLED=True`, autonomous scanning begins

---

## File Tree Snapshot (2026-03-16)

```
jarvis_lab/
├── main.py
├── config.py
├── requirements.txt              ← MISSING — generate with pip freeze
├── generate_sounds.py            ← run once to create assets/sounds/
├── JARVIS_START.ps1              ← use this to launch
├── DEPLOY_PATCHES.ps1
├── ARCHITECTURE.md
├── AGENTS.md
├── HANDOFF_POST_ENDGAME.md       ← this file
├── AUDIT_REPORT.md
├── SECURITY_REPORT.md
├── MODEL_UPGRADE_REPORT.md
├── audio/
│   ├── __init__.py
│   └── sound_engine.py
├── assets/
│   └── sounds/                   ← MISSING until generate_sounds.py runs
├── agents/
│   ├── worker.py
│   ├── autonomous.py
│   └── monitor.py
├── autonomy/
│   ├── recon_loop.py
│   ├── finding_engine.py
│   ├── preference_engine.py
│   └── strategy.py               ← NEW: ReconStage mission tracker
├── bridge/
│   └── scope.py
├── evolution/
│   └── engine.py
├── gui/
│   ├── main_window.py
│   ├── splash.py
│   ├── mini_window.py             ← NEW: Ctrl+Shift+J overlay HUD
│   ├── settings_panel.py
│   ├── widgets.py                ← legacy
│   ├── panels/
│   │   ├── __init__.py
│   │   ├── telemetry_panel.py     ← NEW: extracted from main_window
│   │   └── scan_graph.py          ← NEW: target/findings tree
│   └── widgets/
│       ├── __init__.py            ← ArcReactor, PTT, ThinkDots, WaveformVisualizer, Bubble, ProposalCard
│       ├── panel_header.py        ← NEW: reusable HUD section header
│       └── voice_button.py        ← NEW: state-aware voice button
├── llm/
│   ├── client.py
│   ├── prompts.py
│   ├── router.py
│   └── local_judge.py
├── policy/
│   ├── autonomy_policy.py
│   └── engine.py
├── research/
│   ├── __init__.py                ← NEW
│   ├── engine.py                  ← NEW: NVD CVE polling
│   ├── evaluator.py               ← NEW: severity classifier
│   └── sources/
│       ├── __init__.py            ← NEW
│       └── nvd.py                 ← NEW: NIST NVD API v2 client
├── runtime/
│   ├── kill_switch.py
│   ├── watchdog.py
│   ├── integrity.py
│   └── boot_manager.py
├── scheduler/
│   ├── morning_briefing.py
│   ├── recon_scheduler.py
│   └── job_executor.py            ← NEW: recon pipeline executor
├── security/
│   ├── sanitizer.py
│   └── secrets.py
├── storage/
│   ├── db.py
│   ├── audit_log.py
│   ├── companion_db.py            ← NEW: operator skill tracking
│   └── settings_store.py
├── tools/
│   ├── registry.py
│   ├── system_tools.py
│   ├── shell_tools.py
│   ├── network_tools.py           ← NEW: weather/dns/whois/geoip/subfinder/httpx/nuclei
│   ├── voice_tools.py
│   ├── project_tools.py
│   └── report_tools.py
└── voice/
    ├── tts.py                    ← DO NOT TOUCH
    ├── stt.py                    ← DO NOT TOUCH
    ├── wake_listener.py          ← Agent 03 (partial)
    ├── profiles.py
    ├── text_normalizer.py
    ├── postfx.py
    ├── validate_voice.py
    ├── response_translator.py     ← NEW: persona-aware tool output
    └── backends/
        ├── chatterbox_backend.py
        ├── kokoro_backend.py
        ├── piper_backend.py
        └── sapi_backend.py
```

---

*Handoff document — Agent 04 DOCS-SYNC / DOCS-SYNC-2 — updated 2026-03-16*
