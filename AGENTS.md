# JARVIS Lab — Agents Reference
**Last updated:** 2026-03-16
**Status:** Current (post-ENDGAME wave, Agents 00–19 complete)

---

## Agent Naming Convention

| Prefix | Meaning |
|--------|---------|
| `P#` | PATCH agent — targeted fix, no new features |
| `Agent ##` | ENDGAME agent — feature or major change |

---

## Completed Agents

### PATCH P1 — Sound Engine
**Status:** COMPLETE
**Files created:** `audio/__init__.py`, `audio/sound_engine.py`, `generate_sounds.py`
**Config added:** `UI_SOUNDS_ENABLED = True`, `UI_SOUND_VOLUME = 0.7`
**What it does:** UI sound engine for feedback events (boot, ready, thinking, error, etc.).
**One-time setup required:** `python generate_sounds.py` synthesizes WAV files into `assets/sounds/`.
**Note:** `assets/sounds/` does not exist until that script runs. Shell was broken at time of writing — operator must run manually.

---

### PATCH P2 — Startup Sequence
**Status:** COMPLETE
**Files modified:** `gui/splash.py`
**What it does:** Augments the existing `JarvisSplash` boot screen with `sound_engine` calls so
audio cues play during the animated splash sequence. No new files.

---

### PATCH P3 — Speech Interrupt
**Status:** COMPLETE
**Files modified:** `voice/tts.py`, `agents/worker.py`
**What it does:**
- Added public `tts.interrupt()` wrapper (was previously `_interrupt_current()`, private-only)
- Added `_INTERRUPT_PATTERNS` in `agents/worker.py` — phrases that trigger immediate TTS cutoff
- Wired into `main_window._submit()` path

---

### PATCH P4 — Morning Briefing
**Status:** COMPLETE
**Files created:** `scheduler/morning_briefing.py`
**What it does:** Generates a weather + intelligence briefing on JARVIS startup.
Registered as a tool so it can also be invoked on demand.
`generate_briefing_text()` is the public entry point.

---

### Agent 00 — Audit (ENDGAME)
**Status:** COMPLETE
**Output:** `AUDIT_REPORT.md`
**What it did:**
- Full syntax inspection of all Python files
- Config value verification (confirmed qwen3:14b, chatterbox_jarvis, etc.)
- Import status check — identified missing files that later agents would create
- GUI panel discrepancy documented: memory said panels were separate files; reality is all-monolithic in `main_window.py`
- DB table audit
- Identified TTS public interrupt gap (fixed by P3)
- GO/NO-GO issued for all ENDGAME agents

---

### Agent 01 — Chatterbox GPU (ENDGAME)
**Status:** IN PROGRESS (held — shell broken, cuDNN missing)
**Files:** `voice/backends/chatterbox_backend.py` (exists, needs GPU wiring)
**Blocker:** cuDNN 9.x not installed. Chatterbox falls back to CPU (slow).
**Operator action to unblock:**
```powershell
# Install cuDNN 9.x for CUDA 12.x
# Download from: https://developer.nvidia.com/cudnn
# Or via pip:
pip install nvidia-cudnn-cu12
```
After install, Chatterbox will auto-detect GPU and use it.
**DO NOT TOUCH:** `voice/tts.py` and `voice/stt.py` — voice pipeline is off-limits.

---

### Agent 02 — Persona Voice Overhaul (ENDGAME)
**Status:** IN PROGRESS
**Files:** `voice/profiles.py`, `voice/backends/chatterbox_backend.py`
**What it does:** Maps each LLM persona (jarvis, india, ct7567, morgan) to a distinct voice profile.
`PERSONA_TO_PROFILE` dict in `voice/profiles.py` — already partially implemented.

---

### Agent 03 — Wake Word Engine (ENDGAME)
**Status:** IN PROGRESS / PARTIAL
**Files created:** `voice/wake_listener.py`
**Config keys added:** `WAKE_WORDS`, `AMBIENT_LISTENING_ENABLED`
**DB table added:** `ambient_log`
**What it does:** Ambient background listener detects wake words and routes to the STT queue,
enabling hands-free activation without PTT.
**Note:** STT queue API was not fully known at time of writing — implemented with stub integration.
`voice/stt.py` was NOT modified (off-limits).

---

### Agent 04 — Docs Sync (ENDGAME)
**Status:** COMPLETE (this agent)
**Files created:** `ARCHITECTURE.md`, `AGENTS.md`, `HANDOFF_POST_ENDGAME.md`
**What it did:** Audited all existing .md files, cross-referenced with actual disk state (via Glob),
and produced authoritative documentation reflecting current system state as of 2026-03-16.

---

## Completed Agents (05–19)

All agents in this wave are complete.

| Agent | Codename | Status | Key Files |
|-------|----------|--------|-----------|
| 05 | RESEARCH-AGENT | COMPLETE | `research/` package, NVD CVE polling, `research_digest` + `search_research` tools |
| 06 | COMPANION-DATABASE | COMPLETE | `storage/companion_db.py`, operator skill tracking, adaptation hints |
| 07 | CONVERSATION-ENGINE | COMPLETE | `voice/response_translator.py`, persona-aware tool output translation |
| 08 | SCAN-GRAPH | COMPLETE | `gui/panels/scan_graph.py`, QTreeWidget target/findings tree |
| 09 | LEFT-PANEL | COMPLETE | `gui/panels/telemetry_panel.py`, TelemetryPanel extracted |
| 10 | GUI-INTEGRATION | COMPLETE | MiniHUD wired, VoiceButton + PanelHeader integrated |
| 11 | CENTER-TABS | COMPLETE | CHAT/SCAN/RESEARCH tabs in center panel |
| 12 | WINDOW-PERSIST | COMPLETE | Window geometry save/restore via settings_store |
| 13 | MINI-WINDOW | COMPLETE | `gui/mini_window.py`, Ctrl+Shift+J overlay HUD |
| 14 | HUD-POLISH | COMPLETE | `gui/widgets/panel_header.py` + `voice_button.py` |
| 15 | DB-MAINTENANCE | COMPLETE | `db_stats`, `db_vacuum`, `db_prune_old_messages`, `db_maintenance` tool |
| 16 | POLICY-AUDIT | COMPLETE | `_audit_decision()` in AutonomyPolicyEngine, full context per decision |
| 17 | SELF-HEALER | COMPLETE | `record_llm_success`, `llm_is_stale`, `_check_ollama_model`, `_recover_ollama` |
| 18 | STRATEGY-ENGINE | COMPLETE | `autonomy/strategy.py`, ReconStage + MissionState, `strategy_briefing` tool |
| 19 | GO-NO-GO | COMPLETE | Final integration audit — 21/21 files GO, zero blockers |

---

## Operator-Created Agents (External)

The following agents were run outside the ENDGAME sequence:

| Agent | What it did | Report |
|-------|-------------|--------|
| Security Auditor | 2-cycle security audit; 19 fixes applied; 3 operator-action items remain | `SECURITY_REPORT.md` |
| Model Upgrader | llama3.1 → qwen3:14b; llama3.1:8b → phi4-mini; created `JARVIS_START.ps1` | `MODEL_UPGRADE_REPORT.md` |

---

## AgentWorker (`agents/worker.py`) — Runtime Agent

This is not a one-shot deployment agent but the persistent runtime agent that processes every
user message. Key internals:

| Component | Description |
|-----------|-------------|
| `_KEYWORD_RULES` | 15+ deterministic regex patterns matched before LLM round-trip |
| `_DIRECT_TOOLS` | Tools invoked directly without LLM involvement |
| `_INTERRUPT_PATTERNS` | Phrases that trigger `tts.interrupt()` immediately |
| `_tool_summary()` | Deterministic one-line summaries for 30+ tools |
| `_format_tool_reply()` | Builds `DETAIL_SEP`-formatted Bubble content |

---

## Autonomous Agent (`agents/autonomous.py`)

Background autonomous loop with ProposalCard approval queue. Generates `CMD_1`–`CMD_5` style
proposals for operator review. All proposals must be approved via GUI before execution.

**Known security gap (operator action):** The approval path calls `tool_run_command(confirmed=True)`
without re-verifying against the CMD_1–CMD_5 allowlist at execution time. Prompt-layer control only.
See `SECURITY_REPORT.md` for details.

---

## Do-Not-Touch List

| File | Reason |
|------|--------|
| `voice/stt.py` | Working STT pipeline — any change risks breaking microphone input |
| `voice/tts.py` | Working TTS pipeline (known path-injection issue in ElevenLabs branch — operator aware) |
| `voice/backends/*.py` | TTS backend chain — only touch if Agent 01/02 scope explicitly covers it |

---

*Agents reference — Agent 19 GO-NO-GO / DOCS-SYNC-2 — 2026-03-16*
