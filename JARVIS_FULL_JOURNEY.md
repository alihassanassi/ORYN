# THE JARVIS BUILD — COMPLETE JOURNEY

> One person. Seven days. A local AI cybersecurity operations console, built from scratch.
> This document is the archaeological record of that build.

---

## THE NUMBERS

| Metric | Count |
|--------|-------|
| Python files | 143 |
| Directories | 19 |
| Named build phases | 5 major waves |
| Individual agents deployed | 24+ (P1–P4, Agent 00–19, Security Auditor, Model Upgrader, post-ENDGAME wave) |
| Tools registered | 50+ |
| Boot sequence steps | 16 |
| Memory layers | 6 |
| LLM chains | 4 |
| TTS backends in fallback chain | 4 (Chatterbox → Kokoro → Piper → SAPI) |
| Security fixes applied | 23 (19 ENDGAME cycle + 4 hardening) |
| DB tables | 15+ |
| Feature flags | 8 |
| Build duration | ~7 days (approx. March 9–18, 2026) |

> **Note:** Total line count and database record counts could not be retrieved at document
> creation time — the bash environment is unavailable (JARVIS is running and holding fork
> resources). The file counts above are exact, from a complete directory enumeration.

---

## PHASE TIMELINE — EVERY PHASE IN ORDER

---

### PHASE 0 — THE FOUNDATION
**Date:** ~March 9–11, 2026 (estimated)
**What it built:**
The skeleton. Everything that had to exist before anything else could. The four sacred pieces
of infrastructure: the config, the database, the GUI shell, and the voice pipeline.

**Files created/modified:**
- `main.py` — application entry point, QApplication lifecycle
- `config.py` — all constants, color tokens P{}, LLM options, feature flags
- `storage/db.py` — SQLite helpers, `db_init()`, 4 initial tables (projects, messages, commands, scan_targets)
- `storage/audit_log.py` — `ImmutableAuditLog` with hash-chained records
- `storage/settings_store.py` — JSON-backed operator preferences
- `gui/main_window.py` — monolithic QMainWindow, Iron Man HUD aesthetic, 3-column layout
- `gui/splash.py` — `JarvisSplash`: animated boot screen, 60fps concentric rings, sweeping arcs, progress bar, 8-message boot ticker
- `gui/widgets.py` — legacy widget file (ArcReactor, PTT, ThinkDots, WaveformVisualizer, Bubble, ProposalCard)
- `voice/tts.py` — **DO NOT TOUCH**: Kokoro ONNX TTS pipeline, single-slot latest-wins queue, `speak()` + `interrupt()`
- `voice/stt.py` — **DO NOT TOUCH**: faster-whisper STT, wake word + PTT microphone input
- `voice/profiles.py` — VoiceProfile, PROFILES, PERSONA_TO_PROFILE dict
- `voice/text_normalizer.py` — cleans markdown/tables before TTS
- `voice/postfx.py` — audio post-processing chain
- `voice/validate_voice.py` — voice backend validation utilities
- `voice/backends/base.py` — abstract backend interface
- `voice/backends/kokoro_backend.py` — Kokoro ONNX backend (CPU-capable)
- `voice/backends/piper_backend.py` — Piper offline neural TTS
- `voice/backends/sapi_backend.py` — Windows SAPI fallback (always available)
- `voice/backends/chatterbox_backend.py` — zero-shot voice clone backend (GPU preferred)
- `llm/client.py` — Ollama OpenAI-compat client, `complete()`, `complete_stream()`, tool call parsing
- `llm/prompts.py` — `JARVIS_PERSONA` + 4 persona system prompts + `AUTO_SYSTEM` bug bounty recon prompt
- `llm/router.py` — `LLMRouter`: `route()`, `get_token_stats()`, `_log_routing()`
- `llm/local_judge.py` — fast structured decisions via phi4-mini
- `agents/worker.py` — `AgentWorker`: keyword routing, direct tools, `_needs_tools()`, tool loop
- `agents/autonomous.py` — `AutonomousAgent`: background thinking, ProposalCard approval queue
- `agents/monitor.py` — system monitoring agent
- `tools/registry.py` — `TOOL_SCHEMAS` (OpenAI JSON schema list) + `dispatch()` + `REGISTRY` dict
- `tools/system_tools.py` — system_status, CPU/RAM/disk/network, file ops with path-boundary guard
- `tools/shell_tools.py` — `run_command` (PowerShell + BLOCKED_COMMANDS), `open_app` (APP_MAP allowlist)
- `tools/project_tools.py` — projects, notes, proposals, targets, findings
- `tools/report_tools.py` — draft_report, verify_finding, score_finding, list_unverified_findings
- `tools/voice_tools.py` — list_voices, set_voice, list_voice_profiles, set_voice_profile, switch_persona
- `runtime/kill_switch.py` — dual-mechanism stop: Python state + `EMERGENCY_STOP.flag` filesystem flag; Ctrl+Alt+Shift+K
- `runtime/watchdog.py` — Ollama health checks, service monitoring
- `runtime/integrity.py` — SHA256 baseline tamper detection for entry points
- `runtime/boot_manager.py` — startup sequencing daemon (initial version, Steps 1–9)
- `autonomy/recon_loop.py` — `ReconLoop`: 7-gate safety chain, `RECON_LOOP_ENABLED=False` default
- `autonomy/finding_engine.py` — process_raw_finding → deduplicate → score → verify → store
- `autonomy/preference_engine.py` — operator approval preference learning
- `policy/autonomy_policy.py` — `AutonomyPolicyEngine`: `_AUTONOMOUS_ALLOWLIST`, `_NEVER_AUTONOMOUS`
- `policy/engine.py` — core policy evaluation
- `bridge/scope.py` — `is_in_scope(target, program_id)`: fails closed on any error
- `security/sanitizer.py` — `wrap_untrusted()`, `_strip_injections()`
- `security/secrets.py` — Windows DPAPI via keyring, no hardcoded fallbacks
- `scheduler/recon_scheduler.py` — timed recon job scheduler
- `scheduler/job_executor.py` — subfinder → httpx (cap 50) → nuclei (cap 20) → FindingEngine pipeline
- `evolution/engine.py` — evolution scaffolding (stub)
- `bridge/__init__.py`, `bridge/server.py` — FastAPI bridge for Parrot Linux VM

**Why it mattered:**
Before this phase nothing worked. After this phase, JARVIS could think, speak, hear, store,
and execute tools. The two voice files (tts.py and stt.py) were hardened enough that they were
declared untouchable for all future work. The 7-gate recon safety model was designed before
a single scan ever ran.

---

### PHASE 1 — EXTERNAL AGENTS: MODEL UPGRADE + SECURITY AUDIT
**Date:** 2026-03-16
**What it built:**
Two dedicated one-shot agents ran outside the ENDGAME sequence to harden the foundation
before the major feature wave began.

#### Model Upgrade Agent
**Files created/modified:**
- `config.py` — `OLLAMA_MODEL="qwen3:14b"`, `LOCAL_JUDGE_MODEL="phi4-mini:latest"`, `OLLAMA_KEEP_ALIVE="2m"`, `think:False`
- `llm/client.py` — `_strip_think()` guard, `keep_alive` on both request paths
- `llm/local_judge.py` — updated default model from `llama3.1:8b` → `phi4-mini:latest`
- `JARVIS_START.ps1` — **created**: Ollama health check, auto-pull if missing, background pre-warm, JARVIS launch
- `MODEL_UPGRADE_REPORT.md` — full upgrade report

**Before/After:**
| | Before | After |
|-|--------|-------|
| Primary LLM | llama3.1:latest (8B) | qwen3:14b (~60 t/s) |
| Judge | llama3.1:8b (~80 t/s) | phi4-mini (~180 t/s) |
| Tool-call reliability | Good | Excellent (native function-call head) |

**Why it mattered:**
Qwen3:14b has a native function-call head — it knows what a tool call is without prompting.
phi4-mini makes approve/deny decisions at ~180 tokens/second. The `KEEP_ALIVE=2m` design
means LLM unloads before Chatterbox loads — never fighting for VRAM.

#### Security Audit (2 Cycles)
**Files modified:** tools/shell_tools.py, config.py, autonomy/preference_engine.py, runtime/watchdog.py, agents/worker.py, security/sanitizer.py, storage/db.py
**Report:** `SECURITY_REPORT.md`

| Issue | Severity | Fix |
|-------|----------|-----|
| `shell=True` in open_app + arbitrary code path | HIGH | APP_MAP allowlist, `shell=False` |
| Confirmation gate bypass (`_SAFE_RE = re.compile(r".*")`) | HIGH | `_SAFE_COMMANDS` tight allowlist |
| Hardcoded dev token fallback | MED | Fallback removed entirely |
| SQL f-string column injection in preference_engine | MED | Replaced with explicit branches |
| Hardcoded 127.0.0.1 health-check URLs | MED | `_build_services()` reads config |
| Stored notes/commands injected into LLM raw | MED | `wrap_untrusted()` applied to both |
| + 16 more | various | 19 total fixes |

**Why it mattered:**
A `re.compile(r".*")` confirmation gate literally meant every shell command ran immediately.
This was caught and fixed before any autonomous scanning was enabled.

---

### PHASE 2 — ENDGAME PATCH WAVE (P1–P4)
**Date:** 2026-03-16
**What it built:**
Four targeted patches to fill gaps identified by the pre-ENDGAME audit before the full agent wave.

#### PATCH P1 — Sound Engine
**Files created:** `audio/__init__.py`, `audio/sound_engine.py`, `generate_sounds.py`
**Config added:** `UI_SOUNDS_ENABLED=True`, `UI_SOUND_VOLUME=0.7`
Audio feedback for boot, ready, thinking, error, and other UI events. One-time setup:
`python generate_sounds.py` synthesizes WAV files into `assets/sounds/`.

#### PATCH P2 — Startup Sequence
**Files modified:** `gui/splash.py`
Wired sound_engine calls into the existing `JarvisSplash` boot animation. Audio cues during
the animated HUD boot screen — rings, arcs, progress bar.

#### PATCH P3 — Speech Interrupt
**Files modified:** `voice/tts.py`, `agents/worker.py`
Added public `tts.interrupt()` wrapper (was private-only). Added `_INTERRUPT_PATTERNS` —
phrases that trigger immediate TTS cutoff. Wired into `main_window._submit()`.

#### PATCH P4 — Morning Briefing
**Files created:** `scheduler/morning_briefing.py`
`generate_briefing_text(persona)` delivers weather + intelligence on JARVIS startup.
Also registered as an on-demand tool.

---

### PHASE 3 — ENDGAME AGENT WAVE (Agents 00–19)
**Date:** 2026-03-16
**What it built:**
20 sequential agents, each with a specific mission, deploying in order from audit to
final GO-NO-GO verification. This was the planned expansion wave.

#### Agent 00 — AUDIT
**Output:** `AUDIT_REPORT.md`
Full pre-flight syntax inspection. Discovered:
- `gui/panels/` was empty — all panel logic was monolithic in main_window.py
- Missing: `audio/sound_engine.py`, `scheduler/morning_briefing.py`, `voice/wake_listener.py`, `research/engine.py`
- TTS public interrupt gap
- GO/NO-GO issued for all 8 upcoming agents

#### Agent 01 — Chatterbox GPU
**Status:** IN PROGRESS (cuDNN 9.x not installed)
`voice/backends/chatterbox_backend.py` exists, needs GPU wiring. CPU fallback operational.
**Unblock:** `pip install nvidia-cudnn-cu12`

#### Agent 02 — Persona Voice Overhaul
**Files:** `voice/profiles.py`, `voice/backends/chatterbox_backend.py`
`PERSONA_TO_PROFILE` dict mapping each of the 4 personas to a distinct voice profile.
JARVIS→bm_george, India→bf_emma, CT-7567→bm_lewis, Morgan→am_michael

#### Agent 03 — Wake Word Engine
**Files created:** `voice/wake_listener.py`
**Config added:** `WAKE_WORDS`, `AMBIENT_LISTENING_ENABLED`
**DB table added:** `ambient_log`
Ambient background listener for hands-free wake word detection. STT queue integration
is stub (voice/stt.py is off-limits).

#### Agent 04 — Docs Sync
**Files created:** `ARCHITECTURE.md`, `AGENTS.md`, `HANDOFF_POST_ENDGAME.md`
Authoritative documentation reflecting current system state. Corrected memory vs. reality
discrepancies (panels were monolithic, not separate files).

#### Agent 05 — Research Engine
**Files created:** `research/__init__.py`, `research/engine.py`, `research/evaluator.py`, `research/sources/__init__.py`, `research/sources/nvd.py`
`ResearchEngine`: NVD CVE polling (NIST API v2), 3-page pagination, 1s sleep (free tier).
`classify_severity()`, `should_surface()`, `get_digest_text()`. Gated on `RESEARCH_ENGINE_ENABLED`.
Tools: `research_digest`, `search_research`

#### Agent 06 — Companion Database
**Files created:** `storage/companion_db.py`
Operator skill tracking. `get_adaptation_hint(persona)` injected into every LLM call.
JARVIS learns how you work over time.

#### Agent 07 — Conversation Engine
**Files created:** `voice/response_translator.py`
`translate_tool_result(tool_name, result_dict, persona)`: persona-aware natural language
output for all tool results. JARVIS doesn't read JSON at you — it tells you what it found.

#### Agent 08 — Scan Graph
**Files created:** `gui/panels/scan_graph.py`
`QTreeWidget` for the SCAN tab — targets and findings as a browsable tree.

#### Agent 09 — Left Panel
**Files created:** `gui/panels/telemetry_panel.py`
`TelemetryPanel` extracted from the monolith. Signals: `submit_requested`, `new_project_clicked`, `voice_toggled`.

#### Agent 10 — GUI Integration
MiniHUD wired into main_window. `gui/widgets/voice_button.py` and `gui/widgets/panel_header.py` integrated.

#### Agent 11 — Center Tabs
CHAT / SCAN / RESEARCH tab switcher in the center QStackedWidget.

#### Agent 12 — Window Persist
Window geometry save/restore via `storage/settings_store.py`. JARVIS remembers where you
put its window.

#### Agent 13 — Mini Window
**Files created:** `gui/mini_window.py`
Ctrl+Shift+J overlay HUD — frameless, always-on-top. Shows AI state + last response.
The HUD you can glance at while doing something else.

#### Agent 14 — HUD Polish
**Files created:** `gui/widgets/panel_header.py` (28px HUD section header with optional action button), `gui/widgets/voice_button.py` (state-aware: offline/online/listening)

#### Agent 15 — DB Maintenance
`db_stats()`, `db_vacuum()`, `db_prune_old_messages()` added to `storage/db.py`.
`db_maintenance` tool registered. JARVIS can clean up after itself.

#### Agent 16 — Policy Audit
`_audit_decision()` added to `AutonomyPolicyEngine`. Full context logged per decision.
Every autonomous action leaves a signed audit trail.

#### Agent 17 — Self-Healer
`record_llm_success()`, `llm_is_stale()`, `_check_ollama_model()`, `_recover_ollama()` added to watchdog.
JARVIS monitors its own brain and restarts it if it goes stale.

#### Agent 18 — Strategy Engine
**Files created:** `autonomy/strategy.py`
`ReconStage` enum, `MissionState`, `StrategyEngine`. `tool_strategy_briefing()` tool.
Feeds the autonomous agent with mission context.

#### Agent 19 — GO-NO-GO
Final integration audit: 21/21 files verified GO, zero blockers. The wave is complete.

---

### CONTINUATION SESSION (same day — March 16, 2026)
**What it built:**
The operator typed "keep going." Four more additions on top of the completed ENDGAME wave.

**Files created/modified:**
- `tools/program_tools.py` — 6 tools: list_programs, create_program, add_scope, program_status, set_program_status, scope_check
- `tools/network_tools.py` — expanded: weather, dns_lookup, whois_lookup, geolocate_ip, url_analyze, run_subfinder, run_httpx, run_nuclei, list_capabilities
- `agents/worker.py` — `_TOOL_RE` expanded to 40+ keyword patterns
- `runtime/boot_manager.py` — Step 10: periodic ResearchEngine.run() every `RESEARCH_POLL_INTERVAL` secs

**Why it mattered:**
Without program_tools, JARVIS had no concept of bug bounty programs. With them: create a
program, add scope, scope-check any domain, and launch autonomous recon — all from chat.

---

### PHASE 4 — INTELLIGENCE + MEMORY WAVE
**Date:** 2026-03-17
**What it built:**
The largest expansion. Every subsystem that elevates JARVIS from a tool-calling chatbot to
an actual intelligence platform. Memory that persists across sessions. Reasoning chains that
think before acting. An INTEL tab that correlates CVEs to your actual targets.

**Files created:**

*Memory system (6-layer):*
- `memory/manager.py` — `MemoryManager`: `recall(query, project_id, persona, max_tokens=800)`
- `memory/store.py` — vector-backed working memory
- `memory/retrieval.py` — semantic retrieval across layers
- `memory/models.py` — data models: MemoryRecord, MemoryLayer
- `memory/promoter.py` — working → episodic → semantic promotion engine
- `memory/operator_model.py` — skill scores, blindspot hints, program match scoring
- `memory/tools.py` — `operator_model_summary`, `operator_blindspots` tools
- `memory/tests/test_memory.py` — unit tests for memory pipeline

*LLM reasoning chains:*
- `llm/chains/recon_analyst.py` — `analyze_scan_results`: structured recon interpretation
- `llm/chains/vuln_reasoner.py` — `reason_vulnerability`: multi-step vuln analysis
- `llm/chains/triage_engine.py` — `triage_findings`: severity/priority ranking
- `llm/chains/strategy_advisor.py` — `suggest_next_action`: contextual recon strategy
- `llm/response_cache.py` — response caching for repeated queries

*Reporting:*
- `reporting/cvss_calculator.py` — pure CVSS 3.1 base score math (no LLM, no network)
- `reporting/h1_formatter.py` — HackerOne markdown report template (DRAFT watermark)
- `reporting/report_engine.py` — `generate_report_for_finding()`, never auto-submits

*Intelligence layer:*
- `intelligence/correlator.py` — CVE↔target cross-reference (INTEL_CORRELATOR_ENABLED)
- `intelligence/hacktivity_monitor.py` — HackerOne public disclosure monitor
- `intelligence/coaching_engine.py` — 7-rule hint system, fires after pause threshold
- `intelligence/context_predictor.py` — preloads session context 5min before predicted start

*Autonomy additions:*
- `autonomy/hunt_director.py` — proposes next recon targets (HUNT_DIRECTOR_ENABLED, never auto-executes)
- `autonomy/strategy_learner.py` — rolling tool effectiveness tracker
- `autonomy/self_improver.py` — self-improvement scaffolding

*Security additions:*
- `security/rate_limiter.py` — sliding window per (tool, target): subfinder 10/hr, nuclei 5/hr

*Additional research sources:*
- `research/sources/hackerone.py` — HackerOne public disclosures
- `research/sources/github.py` — GitHub advisory feed
- `research/sources/shodan.py` — Shodan CVE feed
- `research/sources/ollama_registry.py` — Ollama model registry monitoring
- `research/sources/twitter.py` — security Twitter/X feed

*More tools:*
- `tools/browser_tools.py` — browser automation tools
- `tools/vision_tools.py` — vision/screenshot analysis tools

*GUI expansion (8-tab center panel):*
- `gui/theme.py` — `ThemeManager` singleton: `set_persona()`, `master_stylesheet()`
- `gui/settings_panel.py` — redesigned settings dialog (cards, badges, sliders, 420px)
- `gui/panels/agent_monitor.py` — AGENTS tab: daemon status, worker states
- `gui/panels/pipeline_monitor.py` — PIPELINES tab: recon pipeline status
- `gui/panels/memory_panel.py` — MEMORY tab: memory record browser
- `gui/panels/intelligence_panel.py` — INTEL tab: operator profile, coaching hint, threat intel, hunt proposals
- `gui/widgets/ai_core_widget.py` — AI CORE tab center widget
- `gui/widgets/orb_widget.py` — standalone orb widget
- `gui/widgets/hud_header.py` — HUD header variant
- `gui/widgets/voice_orb.py` — voice-reactive orb
- `gui/widgets/theme_bar.py` — persona theme selector bar
- `gui/widgets/audio_meter.py` — real-time audio level meter
- `gui/windows/resource_monitor.py` — floating resource monitor window
- `gui/windows/presentation_window.py` — presentation/demo mode window
- `voice/clip_manager.py` — Chatterbox reference WAV management (add/validate/select)
- `runtime/self_healer.py` — health checks every 60s, one-shot escalation guards
- `runtime/night_watchman.py` — overnight monitoring daemon
- `bridge/server.py` — FastAPI bridge, CORS restricted to localhost

*Config flags added:*
`INTEL_CORRELATOR_ENABLED`, `INTEL_HACKTIVITY_ENABLED`, `HUNT_DIRECTOR_ENABLED`,
`COACHING_ENABLED=True`, `CONTEXT_PREDICTOR_ENABLED`, `HUNT_AUTO_APPROVE_THRESHOLD=0.0`

*Boot sequence expanded:* Steps 11–16 added
(self_healer → correlator → hacktivity → hunt_director → coaching → context_predictor)

**Why it mattered:**
This is the difference between "AI assistant that calls tools" and "AI operator that remembers,
reasons, correlates, and teaches." The 6-layer memory means JARVIS gets better the longer you
use it. The CVSS calculator means bug reports never go out with guessed severity scores.
The coaching engine means JARVIS notices when you haven't tried a technique and tells you.

---

### PHASE 5 — HARDENING + BUG FIXES
**Date:** 2026-03-17
**What it built:**
Four security fixes and one critical performance fix.

**Security fixes (`JARVIS_HARDENING_REPORT.md`):**
- `S-01`: `kill_switch.py` broken TTS import — fixed (`from voice.tts import speak`)
- `S-02`: CORS wildcard in `bridge/server.py` — fixed to localhost-only allowlist
- `S-03`: Unauthenticated `/api/ops/graph` endpoint — `_check_token()` added
- `S-04`: `policy/engine.py` always returned True — `_BLOCKED_INTERACTIVE` frozenset added

**Performance fix (`STARTUP_FIX_NOTES.md`) — 28-second cold boot → 8-10 seconds:**

Root cause: Chatterbox initialization was sequential behind sounddevice enumeration.
Three bugs combined to cause a 28-second wait before first TTS speech:

1. `_find_output()` (audio device scan, up to 10s on Windows) blocked Chatterbox from loading
2. Even after Chatterbox finished, `_ready=True` wasn't set until Kokoro finished too
3. `warmup()` had an inverted guard — `if ready: return` — that prevented warmup from ever running

**Fix (`voice/tts.py`, `voice/backends/chatterbox_backend.py`, `main.py`):**
- Extracted Chatterbox init into its own parallel thread
- `_ready=True` set as soon as Chatterbox loads (not waiting for Kokoro)
- Inverted warmup guard replaced with correct `if not self.is_ready(): return`
- `_SafeStreamHandler` added to suppress logging noise from closed Qt streams
- Watchdog updated to treat missing `bridge/server.py`/`jarvis_ops/main.py` as optional services
  with exponential backoff (was thrashing every 30s trying to restart non-existent servers)

**Before/After:**
| | Before | After |
|-|--------|-------|
| Chatterbox loading start | t+13s | t+~0s |
| First speech | t+28s | t+8-10s |

---

## EVERY FILE EVER WRITTEN
*The complete archaeological record of the build — grouped by subsystem*
*(Note: exact file creation timestamps unavailable — bash environment is down while JARVIS runs.*
*Files listed in approximate build order based on modification time from directory enumeration.)*

```
ROOT (4 files)
  main.py                         — application entry point
  config.py                       — all constants and flags
  generate_sounds.py              — one-time WAV synthesis script
  validate_imports.py             — import validation utility

AGENTS/ (4 files)
  agents/__init__.py
  agents/worker.py                — AgentWorker: keyword routing, tool loop
  agents/autonomous.py            — AutonomousAgent: background proposals
  agents/monitor.py               — system monitoring agent

AUDIO/ (2 files)
  audio/__init__.py
  audio/sound_engine.py           — UI sound effects (P1)

AUTONOMY/ (8 files)
  autonomy/__init__.py
  autonomy/recon_loop.py          — 7-gate autonomous scanning engine
  autonomy/finding_engine.py      — dedup → score → verify → store pipeline
  autonomy/preference_engine.py   — operator approval learning
  autonomy/strategy.py            — ReconStage, MissionState (Agent 18)
  autonomy/hunt_director.py       — next-target proposals, never auto-executes
  autonomy/strategy_learner.py    — tool effectiveness tracker
  autonomy/self_improver.py       — self-improvement scaffolding

BRIDGE/ (3 files)
  bridge/__init__.py
  bridge/scope.py                 — is_in_scope() fails closed on error
  bridge/server.py                — FastAPI bridge for Parrot Linux VM

EVOLUTION/ (2 files)
  evolution/__init__.py
  evolution/engine.py             — evolution scaffolding (future)

GUI/ (26 files)
  gui/__init__.py
  gui/main_window.py              — QMainWindow, all layout, event handling
  gui/splash.py                   — animated Iron Man HUD boot screen
  gui/mini_window.py              — Ctrl+Shift+J overlay HUD (Agent 13)
  gui/settings_panel.py           — settings dialog (redesigned)
  gui/theme.py                    — ThemeManager singleton
  gui/widgets.py                  — legacy widgets (superseded)
  gui/panels/__init__.py
  gui/panels/telemetry_panel.py   — left panel, extracted (Agent 09)
  gui/panels/scan_graph.py        — target/findings tree (Agent 08)
  gui/panels/agent_monitor.py     — AGENTS tab
  gui/panels/pipeline_monitor.py  — PIPELINES tab
  gui/panels/memory_panel.py      — MEMORY tab
  gui/panels/intelligence_panel.py — INTEL tab: profile, CVEs, hunt proposals
  gui/widgets/__init__.py         — ArcReactor, PTT, ThinkDots, WaveformVisualizer, Bubble
  gui/widgets/panel_header.py     — HUD section header (Agent 14)
  gui/widgets/voice_button.py     — state-aware voice button (Agent 14)
  gui/widgets/hud_header.py       — HUD header variant
  gui/widgets/voice_orb.py        — voice-reactive orb widget
  gui/widgets/theme_bar.py        — persona theme selector
  gui/widgets/ai_core_widget.py   — AI CORE tab widget
  gui/widgets/orb_widget.py       — standalone orb
  gui/widgets/audio_meter.py      — real-time audio level meter
  gui/windows/__init__.py
  gui/windows/resource_monitor.py — floating resource monitor
  gui/windows/presentation_window.py — presentation/demo mode

INTELLIGENCE/ (5 files)
  intelligence/__init__.py
  intelligence/correlator.py      — CVE↔target cross-reference daemon
  intelligence/hacktivity_monitor.py — HackerOne disclosure watcher
  intelligence/coaching_engine.py — 7-rule operator hint system
  intelligence/context_predictor.py — pre-session context preloader

LLM/ (11 files)
  llm/__init__.py
  llm/client.py                   — Ollama client, streaming, _strip_think()
  llm/prompts.py                  — all 4 persona prompts + AUTO_SYSTEM
  llm/router.py                   — LLMRouter, token stats, routing log
  llm/local_judge.py              — phi4-mini fast decisions
  llm/response_cache.py           — query response caching
  llm/chains/__init__.py
  llm/chains/recon_analyst.py     — analyze_scan_results chain
  llm/chains/vuln_reasoner.py     — reason_vulnerability chain
  llm/chains/triage_engine.py     — triage_findings chain
  llm/chains/strategy_advisor.py  — suggest_next_action chain

MEMORY/ (10 files)
  memory/__init__.py
  memory/manager.py               — MemoryManager: recall() across 6 layers
  memory/store.py                 — working memory backing store
  memory/retrieval.py             — semantic retrieval
  memory/models.py                — MemoryRecord, MemoryLayer
  memory/promoter.py              — tier promotion engine
  memory/operator_model.py        — skill scores, blindspot hints
  memory/tools.py                 — operator_model_summary, operator_blindspots
  memory/tests/__init__.py
  memory/tests/test_memory.py     — memory pipeline unit tests

POLICY/ (3 files)
  policy/__init__.py
  policy/autonomy_policy.py       — AutonomyPolicyEngine, hard allowlist/blocklist
  policy/engine.py                — PolicyEngine, _BLOCKED_INTERACTIVE frozenset

REPORTING/ (4 files)
  reporting/__init__.py
  reporting/cvss_calculator.py    — pure CVSS 3.1 base score (no LLM, no network)
  reporting/h1_formatter.py       — HackerOne markdown template (DRAFT watermark)
  reporting/report_engine.py      — generate_report_for_finding(), never auto-submits

RESEARCH/ (10 files)
  research/__init__.py
  research/engine.py              — ResearchEngine: multi-source polling
  research/evaluator.py           — classify_severity(), should_surface()
  research/sources/__init__.py
  research/sources/nvd.py         — NIST NVD API v2, 3-page pagination
  research/sources/hackerone.py   — H1 public disclosures
  research/sources/github.py      — GitHub advisory feed
  research/sources/shodan.py      — Shodan CVE feed
  research/sources/ollama_registry.py — Ollama model registry
  research/sources/twitter.py     — security Twitter/X feed

RUNTIME/ (7 files)
  runtime/__init__.py
  runtime/boot_manager.py         — 16-step startup sequencing daemon
  runtime/kill_switch.py          — EMERGENCY_STOP.flag + Python state
  runtime/watchdog.py             — Ollama health + optional service backoff
  runtime/integrity.py            — SHA256 tamper detection
  runtime/self_healer.py          — 60s health checks, one-shot guards
  runtime/night_watchman.py       — overnight monitoring daemon

SCHEDULER/ (4 files)
  scheduler/__init__.py
  scheduler/recon_scheduler.py    — timed recon job scheduler
  scheduler/morning_briefing.py   — startup weather + intel briefing (P4)
  scheduler/job_executor.py       — subfinder → httpx → nuclei → FindingEngine

SECURITY/ (4 files)
  security/__init__.py
  security/sanitizer.py           — wrap_untrusted(), injection stripping
  security/secrets.py             — Windows DPAPI via keyring
  security/rate_limiter.py        — sliding window per (tool, target)

STORAGE/ (5 files)
  storage/__init__.py
  storage/db.py                   — all SQLite helpers, 15+ table schema
  storage/audit_log.py            — ImmutableAuditLog, hash-chained
  storage/companion_db.py         — operator skill tracking (Agent 06)
  storage/settings_store.py       — JSON-backed preferences, geometry persist

TOOLS/ (11 files)
  tools/__init__.py
  tools/registry.py               — TOOL_SCHEMAS + dispatch() + REGISTRY
  tools/system_tools.py           — system_status, CPU/RAM/disk/network
  tools/shell_tools.py            — run_command, open_app (allowlisted)
  tools/project_tools.py          — projects, notes, proposals, targets, findings
  tools/report_tools.py           — draft_report, verify, score, list_unverified
  tools/voice_tools.py            — voices, profiles, switch_persona
  tools/network_tools.py          — weather, dns, whois, geoip, subfinder, httpx, nuclei
  tools/program_tools.py          — 6 program management tools
  tools/browser_tools.py          — browser automation
  tools/vision_tools.py           — vision/screenshot analysis

VOICE/ (16 files)
  voice/__init__.py
  voice/tts.py                    — DO NOT TOUCH: full TTS pipeline
  voice/stt.py                    — DO NOT TOUCH: whisper + wake word + PTT
  voice/profiles.py               — VoiceProfile, PROFILES, PERSONA_TO_PROFILE
  voice/text_normalizer.py        — markdown/table stripping before speak()
  voice/postfx.py                 — audio post-processing
  voice/validate_voice.py         — backend validation
  voice/response_translator.py    — persona-aware tool output (Agent 07)
  voice/clip_manager.py           — Chatterbox reference WAV management
  voice/wake_listener.py          — ambient wake word detection (Agent 03)
  voice/backends/__init__.py
  voice/backends/base.py          — abstract backend interface
  voice/backends/chatterbox_backend.py — zero-shot voice clone (GPU preferred)
  voice/backends/kokoro_backend.py     — Kokoro ONNX (CPU-capable)
  voice/backends/piper_backend.py      — Piper offline neural TTS
  voice/backends/sapi_backend.py       — Windows SAPI (always available)

TOTAL: 143 Python files across 19 directories
```

---

## THE SUBSYSTEMS — WHAT EXISTS NOW

```
gui/          THE FACE
              PySide6, Iron Man HUD aesthetic. 8-tab center panel: AI CORE / CHAT / SCAN /
              RESEARCH / AGENTS / PIPELINES / MEMORY / INTEL. 4 persona buttons in topbar.
              Animated orb, waveform visualizer, streaming chat bubbles. MiniHUD overlay.
              26 files. The only subsystem the operator looks at directly.

agents/       THE BRAIN WORKERS
              AgentWorker: one conversational turn. Keyword routing before LLM (15+ patterns),
              tool loop (MAX_ROUNDS=4), smart schema selection (_slim_schemas: 40+ → ~12).
              AutonomousAgent: background proposals with ProposalCard approval queue.
              4 files.

tools/        THE HANDS
              50+ tools registered in TOOL_SCHEMAS + dispatch() + REGISTRY.
              Shell (PowerShell, allowlisted), system, network (subfinder/httpx/nuclei/dns/whois),
              project management, program management, report generation, voice control,
              browser automation, vision/screenshot analysis.
              11 files.

voice/        THE VOICE
              TTS fallback chain: Chatterbox (GPU) → Kokoro ONNX (CPU) → Piper → SAPI.
              STT: faster-whisper with wake word + PTT. 4 personas, 4 voice profiles.
              Parallel init threads (cold boot ~8s). DO NOT TOUCH tts.py or stt.py.
              16 files. The most protected subsystem in the codebase.

memory/       THE MEMORY
              6-layer architecture: working → episodic → semantic → preference → project → system.
              recall() retrieves across all layers. MemoryPromoter moves records up tiers.
              OperatorModel tracks skill scores and blindspots. Gets smarter the longer it runs.
              10 files.

autonomy/     THE WILL
              ReconLoop with 7-gate safety chain. FindingEngine with full H1 pipeline.
              HuntDirector proposes targets but never auto-executes. StrategyLearner tracks
              what works. PreferenceEngine learns operator approval patterns.
              RECON_LOOP_ENABLED=False by default. 8 files.

intelligence/ THE INTUITION
              Threat correlator maps CVEs to your actual targets. HacktivityMonitor watches
              HackerOne public disclosures. CoachingEngine delivers 7-rule hints after pause.
              ContextPredictor preloads session context 5min before you sit down.
              5 files.

security/     THE CONSCIENCE
              Rate limiter (sliding window per tool+target). Sanitizer wraps all external data
              in untrusted envelopes before LLM injection. DPAPI secrets (no hardcoded tokens).
              Two-cycle security audit cleaned 19 issues. 4 files.

bridge/       THE REACH
              FastAPI bridge for Parrot Linux VM. CORS restricted to localhost only.
              scope.py is the single gating function for all autonomous network actions —
              fails closed on any error. 3 files.

storage/      THE SOUL
              SQLite at jarvis.db — 15+ tables. ImmutableAuditLog with hash-chained records
              (separate audit_log.db). CompanionDB for skill tracking. Every policy decision
              logged immutably. 5 files.

runtime/      THE HEARTBEAT
              16-step boot sequence. Kill switch (Python state + filesystem flag). Watchdog
              with optional service backoff. Integrity check (SHA256). Self-healer checks
              every 60s. Night watchman for overnight monitoring.
              7 files.

reporting/    THE OUTPUT
              CVSS 3.1 base score math (pure Python, no LLM, no network). HackerOne markdown
              template with DRAFT watermark. Report engine that never auto-submits.
              4 files.

research/     THE EYES
              5 live data sources: NVD (NIST), HackerOne, GitHub, Shodan, Twitter/X.
              Evaluator classifies severity and decides what surfaces. Gated on
              RESEARCH_ENGINE_ENABLED. 10 files.

llm/          THE MIND
              qwen3:14b at ~60 t/s (native function-call head). phi4-mini judge at ~180 t/s.
              4 reasoning chains for recon, vuln analysis, triage, and strategy.
              think:False by default; /think prefix enables per-query reasoning.
              KEEP_ALIVE=2m so LLM unloads before Chatterbox loads. 11 files.

scheduler/    THE CLOCK
              Morning briefing on startup. ReconScheduler queues program-scoped jobs.
              JobExecutor runs subfinder → httpx → nuclei → FindingEngine sequentially.
              4 files.

audio/        THE PRESENCE
              UI sound engine for boot, ready, thinking, error events.
              One-time setup: python generate_sounds.py.
              2 files.

evolution/    THE FUTURE
              Scaffolding for future self-evolution capabilities. Currently stub.
              2 files.
```

---

## THE REAL NUMBERS FROM THE DATABASE

**Database query unavailable** — bash environment is down while JARVIS is running.
This is a documented condition: bash fork failures occur when JARVIS holds process resources.
Fix: stop JARVIS, then run the queries.

**What the schema tells us (from `storage/db.py` `db_init()`):**

| Table | What it stores |
|-------|---------------|
| `messages` | Every conversation turn — role, content, timestamp |
| `actions` | Every tool execution — tool name, args, result, timestamp |
| `memory_records` | Semantic memory: key, value, layer, embedding, created_at |
| `projects` | Named workspaces |
| `programs` | Bug bounty programs with scope_domains JSON |
| `scan_targets` | Recon scope: target, project, notes |
| `findings` | Informal findings from project context |
| `findings_canonical` | Full H1 pipeline: severity, host, template_id, priority_score, bounty_potential, payout_usd, verified |
| `jobs` | Recon pipeline jobs: program_id, domain, status |
| `research_items` | CVEs and disclosures: source, severity, affects_targets, actioned |
| `tool_effectiveness` | Per-tool stats: finding_rate, false_positive_rate, avg_duration |
| `companion_preferences` | Operator adaptation settings per persona |
| `jarvis_preferences` | Per-tool approval/rejection/modification counts |
| `denied_actions` | Audit trail of every rejected autonomous action |
| `ambient_log` | Wake word and ambient event log |

**To query when JARVIS is stopped:**
```python
import sqlite3
db = 'C:/Users/aliin/OneDrive/Desktop/Jarvis/jarvis_lab/jarvis.db'
conn = sqlite3.connect(db)
print('MESSAGES:', conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0])
print('ACTIONS:', conn.execute('SELECT COUNT(*) FROM actions').fetchone()[0])
print('MEMORY_RECORDS:', conn.execute('SELECT COUNT(*) FROM memory_records').fetchone()[0])
print('PROGRAMS:', conn.execute('SELECT COUNT(*) FROM programs').fetchone()[0])
print('FINDINGS:', conn.execute('SELECT COUNT(*) FROM findings_canonical').fetchone()[0])
r = conn.execute('SELECT * FROM actions ORDER BY created_at ASC LIMIT 1').fetchone()
print('FIRST ACTION:', r)
```

---

## THE HURDLES

Every hard thing that was built through and not around.

**1. The Confirmation Gate That Didn't Exist**
`_SAFE_RE = re.compile(r".*")` — a regex that matched everything. The shell confirmation
gate was completely dead code. Every command ran immediately without operator approval.
Found in security cycle 2. Fixed with `_SAFE_COMMANDS` tight allowlist.

**2. The 28-Second Boot**
First TTS speech took 28 seconds. Root cause: three bugs compounding. sounddevice enumeration
blocked Chatterbox. Chatterbox's `warmup()` exited immediately due to an inverted boolean guard
(`if ready: return` — should have been `if not ready: return`). Even after Chatterbox loaded,
the system waited for Kokoro to finish before declaring itself ready.
Fixed with parallel init threads and early-ready logic. Boot now ~8-10s.

**3. The Watchdog Thrash**
Watchdog checked for `jarvis_ops/main.py` and `bridge/server.py` every 30 seconds. Neither
file existed (bridge runs on the Parrot VM, jarvis_ops is stub-only). Watchdog kept trying to
restart them, failing, logging warnings, repeating until max_restarts (5) hit. Silent failure
mode after that. Fixed with optional service flag + exponential backoff.

**4. The Self-Healer That Spoke Every 60 Seconds**
`_check_daemon_liveliness()` called `_escalate()` (which calls `speak()`) every 60 seconds
when a daemon was found dead. No one-shot guard. JARVIS would announce daemon failures
repeatedly every minute until the session ended. Fixed with `_daemon_alerted: set` guard —
same pattern already used in `_check_db_health()`.

**5. The CORS Wildcard**
`allow_origins=["*"]` in bridge/server.py. The bridge was designed for Parrot VM to call in,
but with a wildcard CORS policy any browser on the network could make authenticated-looking
requests. Fixed to localhost-only allowlist.

**6. The Panel Phantom**
MEMORY.md (the project's own memory) listed 5 panel files that didn't exist on disk:
telemetry_panel.py, chat_panel.py, terminal_panel.py, center_panel.py, approval_queue.py.
Reality: all panel logic was monolithic in main_window.py. Agent 00 caught this.
Agent 09 extracted TelemetryPanel. The rest remain in the monolith — documented honestly.

**7. The HAL Realization** *(architecture decision, not a bug)*
Early in design: should JARVIS be able to run commands without asking? The answer became a
7-gate safety chain. Every autonomous network action passes: kill switch → quiet hours →
daily budget → scope validation → wildcard confirmation → domain validation → policy engine.
`RECON_LOOP_ENABLED=False` by default. `HUNT_AUTO_APPROVE_THRESHOLD=0.0` forever.
No feature can override the scope check. `is_in_scope()` fails closed on any error.

---

## WHAT THIS DOCUMENT PROVES

This is not a prototype. It is not a demo. It is not a weekend hack.

**143 Python files.** Written across 19 directories. Organized into 5 architectural layers,
each with hard boundaries. Every tool in a registry. Every audit decision hash-chained.
Every autonomous action gated through a 7-step safety check. A 6-layer memory system that
makes the operator's usage patterns part of the system. Four TTS backends in a fallback chain
so the voice never goes silent. A security audit that found the confirmation gate was dead code
and fixed it the same day.

**One person. Seven days. These files.**

The only thing that couldn't run while writing this document is the bash shell —
because JARVIS was already running.

---

*Generated: 2026-03-18*
*Source files: ARCHITECTURE.md, AGENTS.md, HANDOFF_POST_ENDGAME.md, JARVIS_PROJECT_CONTEXT.md,*
*AUDIT_REPORT.md, SECURITY_REPORT.md, JARVIS_HARDENING_REPORT.md, STARTUP_FIX_NOTES.md,*
*MODEL_UPGRADE_REPORT.md — plus complete directory enumeration (143 files across 19 directories)*
