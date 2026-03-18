# JARVIS Project Context — Always-On Reference

> Drop this file into the Claude.ai Project "Files" section.
> Every conversation in this project will have full context automatically.

---

## Identity

**Project:** J.A.R.V.I.S. (Just A Rather Very Intelligent System)
**Location:** `C:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab`
**Type:** Local cybersecurity operations console — Iron Man HUD aesthetic, PySide6 GUI
**Purpose:** Personal bug bounty / home lab operator console. NOT a cloud service, NOT a toy.
**Stack:** Python 3.11, PySide6, Ollama (qwen3:14b), Kokoro ONNX TTS, SQLite, Windows 11

---

## Hardware & Runtime

- **GPU:** RTX 4070 Ti Super (16GB VRAM)
- **LLM:** Ollama at `http://127.0.0.1:11434/v1`, model `qwen3:14b` (~60 t/s, `think:false`)
- **Fast judge:** `phi4-mini:latest` for structured decisions
- **TTS primary:** Kokoro ONNX (`C:\kokoro\`) — bm_george (JARVIS), bf_emma (India), bm_lewis (CT-7567), am_michael (Morgan)
- **TTS secondary:** Chatterbox (zero-shot voice clone, requires `pip install chatterbox-tts`)
- **TTS fallback:** Windows SAPI
- **STT:** Whisper-based, wake word + PTT

---

## Architecture — 5 Layers

```
Layer 1: GUI          gui/main_window.py, gui/panels/, gui/widgets/
Layer 2: Agents       agents/worker.py (AgentWorker), agents/autonomous.py
Layer 3: Tools        tools/registry.py (TOOL_SCHEMAS + dispatch), tools/*.py
Layer 4: State        storage/db.py (SQLite), storage/settings_store.py, memory/
Layer 5: Autonomy     autonomy/, intelligence/, runtime/, scheduler/
```

---

## Entry Points

| File | Role |
|------|------|
| `main.py` | App entry — creates QApplication, launches JARVIS window |
| `gui/main_window.py` | QMainWindow — all GUI construction and event handling |
| `runtime/boot_manager.py` | Starts all background daemons (Steps 1-16) |
| `agents/worker.py` | AgentWorker — one conversational turn, tool loop |
| `tools/registry.py` | TOOL_SCHEMAS list + dispatch() + REGISTRY dict |
| `config.py` | All constants, paths, LLM options, color tokens P{} |

---

## GUI Structure

```
QMainWindow (1460×900)
├── Left: TelemetryPanel (280px) — system stats, project selector, voice toggle
├── Center: QStackedWidget — 8 tabs:
│   [0] AI CORE   — OrbWidget / AICoreWidget
│   [1] CHAT      — conversation bubbles, streaming
│   [2] SCAN      — ScanGraphPanel (targets/findings tree)
│   [3] RESEARCH  — research items feed
│   [4] AGENTS    — AgentMonitorPanel
│   [5] PIPELINES — PipelineMonitorPanel
│   [6] MEMORY    — MemoryPanel
│   [7] INTEL     — IntelligencePanel (operator profile, CVEs, hunt proposals)
└── Right: QSplitter (460px) — chat input + terminal
```

**Persona buttons** in topbar: JARVIS / INDIA / MORGAN / CT-7567
Each switches: color theme + TTS voice profile + orb label + speaks confirmation + persists.

---

## Personas & Themes

| Persona | Key | Theme | Voice (Kokoro) | Voice (Chatterbox) |
|---------|-----|-------|----------------|-------------------|
| JARVIS | `jarvis` | CIRCUIT (teal #18e0c1) | bm_george | chatterbox_jarvis |
| India | `india` | SAFFRON (orange #ffa020) | bf_emma | chatterbox_india |
| Morgan | `morgan` | SOVEREIGN (gold/purple #b060ff) | am_michael | chatterbox_morgan |
| CT-7567 | `ct7567` | VENOM (green #39d353) | bm_lewis | chatterbox_ct7567 |

---

## Tools (50+ registered)

**Core:** system_status, run_command, open_app, list_projects, switch_project, save_note, read_notes, cleanup_disk, token_stats, list_capabilities, get_clipboard

**Recon:** run_subfinder, run_httpx, run_nuclei, dns_lookup, whois_lookup, geolocate_ip, url_analyze, scope_check

**Findings:** save_finding, list_findings, save_target, list_targets, draft_report, verify_finding, score_finding, list_unverified_findings, finding_digest, list_report_drafts, calculate_cvss

**Programs:** list_programs, create_program, add_scope, program_status, set_program_status

**Voice:** list_voices, set_voice, list_voice_profiles, set_voice_profile, switch_persona, list_clips, add_clip, remove_clip, validate_clip

**Research/Intel:** research_digest, search_research, morning_briefing, intel_correlate_now, intel_status

**Strategy/Autonomy:** strategy_briefing, preference_summary, recon_loop_start/stop/status/pause, kill_switch_trigger/reset, watchdog_status, hunt_director_status/enable/disable, strategy_effectiveness

**LLM Chains:** analyze_scan_results, reason_vulnerability, triage_findings, suggest_next_action

**Memory:** db_maintenance, operator_model_summary, operator_blindspots

---

## Key Files — What They Do

```
config.py                     — constants, P{} colors, OLLAMA_OPTIONS, feature flags
llm/client.py                 — Ollama OpenAI-compat client, streaming, tool call parsing
llm/prompts.py                — JARVIS_PERSONA + all 4 persona prompts + AUTO_SYSTEM
llm/chains/                   — multi-step reasoning: recon_analyst, vuln_reasoner, triage_engine, strategy_advisor
agents/worker.py              — AgentWorker: _slim_schemas(), _needs_tools(), tool loop (MAX_ROUNDS=4)
agents/autonomous.py          — AutonomousAgent: background thinking
tools/registry.py             — TOOL_SCHEMAS (all schemas) + dispatch() + REGISTRY dict
tools/network_tools.py        — subfinder, httpx, nuclei, dns, whois (all rate-limited)
voice/tts.py                  — DO NOT MODIFY: TTS pipeline, single-slot queue, speak()
voice/stt.py                  — DO NOT MODIFY: wake word + PTT mic input
voice/profiles.py             — voice profile definitions per persona
voice/clip_manager.py         — Chatterbox reference WAV management (add/validate/select)
storage/db.py                 — all SQLite helpers, 15+ tables, get_db() context manager
storage/settings_store.py     — JSON-backed operator prefs (audio, display, behavior, persona)
storage/companion_db.py       — skill tracking, get_adaptation_hint(persona)
storage/audit_log.py          — ImmutableAuditLog: hash-chained, every policy decision
memory/manager.py             — MemoryManager: recall(query, project_id, persona, max_tokens=800)
memory/operator_model.py      — skill scores, blindspot hints, program match scoring
intelligence/coaching_engine.py — 7-rule hint system, fires after pause threshold
intelligence/correlator.py    — CVE↔target cross-reference (INTEL_CORRELATOR_ENABLED)
intelligence/context_predictor.py — preloads session context 5min before predicted start
autonomy/hunt_director.py     — proposes next recon targets (HUNT_DIRECTOR_ENABLED, never auto-executes)
autonomy/strategy_learner.py  — rolling tool effectiveness tracker
reporting/cvss_calculator.py  — pure CVSS 3.1 base score math (no LLM, no network)
reporting/h1_formatter.py     — HackerOne markdown report template (DRAFT watermark)
reporting/report_engine.py    — generate_report_for_finding(), never auto-submits
security/rate_limiter.py      — sliding window per (tool, target)
security/sanitizer.py         — wrap_untrusted(), _strip_injections()
runtime/boot_manager.py       — Steps 1-16: integrity→kill_switch→watchdog→audit→LLM→prefs→finding_engine→recon→jobs→research→self_healer→correlator→hacktivity→hunt_director→coaching→context_predictor
runtime/kill_switch.py        — KILL_FLAG (EMERGENCY_STOP.flag), Ctrl+Alt+Shift+K
runtime/self_healer.py        — health checks every 60s, one-shot escalation guards
policy/autonomy_policy.py     — hard gate: _AUTONOMOUS_ALLOWLIST, _NEVER_AUTONOMOUS
bridge/scope.py               — is_in_scope(target, program_id): fails closed on any error
gui/settings_panel.py         — settings dialog (redesigned: cards, badges, sliders, 420px)
gui/theme.py                  — ThemeManager singleton: set_persona(), master_stylesheet()
gui/panels/intelligence_panel.py — INTEL tab: operator profile, coaching hint, threat intel, hunt proposals
```

---

## Database Schema (key tables)

```sql
projects          — id, name, active, notes, created_at
messages          — id, project, role, content, ts
scan_targets      — id, project TEXT, target, notes, created_at  (NO program_id)
findings          — id, project, target, title, detail, severity, created_at
programs          — id, name, status, scope_domains JSON, wildcard_auto_approved, platform, created_at
jobs              — id, program_id, domain, status, created_at
findings_canonical — full H1 pipeline: title, severity, host, template_id, matched_at, raw_output,
                     status, bounty_potential, priority_score, payout_usd, verified, created_at
research_items    — source, item_type, title, severity, url, affects_targets, actioned, raw_data
tool_effectiveness — tool_name, tech_stack, finding_rate, false_positive_rate, avg_duration_secs, sample_count
companion_preferences — persona, key, value, updated_at  (UNIQUE persona+key)
ambient_log       — transcript, mode, responded, priority
jarvis_preferences — tool_name, approved_count, rejected_count, modified_count
denied_actions    — action, args, reason, created_at
```

---

## Feature Flags (config.py)

| Flag | Default | What it enables |
|------|---------|----------------|
| `RECON_LOOP_ENABLED` | False | Autonomous recon loop + job executor |
| `RESEARCH_ENGINE_ENABLED` | False | Background NVD/CVE polling |
| `INTEL_CORRELATOR_ENABLED` | False | CVE↔target cross-reference daemon |
| `INTEL_HACKTIVITY_ENABLED` | False | HackerOne disclosure monitor |
| `HUNT_DIRECTOR_ENABLED` | False | Autonomous target proposal engine |
| `COACHING_ENABLED` | True | Operator skill hints during pauses |
| `CONTEXT_PREDICTOR_ENABLED` | False | Pre-session context preloading |
| `ALWAYS_SPEAK` | True | TTS fires on every reply |

---

## Safety Model (non-negotiable)

1. **Kill switch** always armed — Ctrl+Alt+Shift+K → writes EMERGENCY_STOP.flag, halts all daemons
2. **Scope gate** — `is_in_scope()` checked before every network action; fails closed
3. **Lab machine guard** — `NET.is_lab_machine()` blocks scanning your own machine
4. **No auto-submission** — reports go to DRAFT status; operator reviews manually
5. **Rate limiter** — sliding window per (tool, target): subfinder 10/hr, nuclei 5/hr
6. **Audit log** — hash-chained, every policy decision logged immutably
7. **HUNT_AUTO_APPROVE_THRESHOLD = 0.0** — hunt director never auto-executes
8. **All autonomous tools** gated by AutonomyPolicyEngine._AUTONOMOUS_ALLOWLIST

---

## Operator Collaboration Style

- **This is a cybersecurity ops console, not a toy assistant** — treat it like professional tooling
- Incremental improvements only — no rewrites, no "improvements" beyond what's asked
- **Never touch** `voice/tts.py` or `voice/stt.py` — working voice pipeline, sacred
- The architecture is intentional — 5 layers are hard boundaries
- When adding tools: update TOOL_SCHEMAS + dispatch() + REGISTRY in `tools/registry.py` (all 3 locations)
- All new modules wrapped in try/except — never crash on import failure
- Config flags default to False for any autonomous/network behavior
- Prefer Edit over Write — targeted changes, not rewrites

---

## Current State (as of 2026-03-17)

### What's fully built and working
- Full GUI: 8-tab center panel, 4 persona buttons, settings redesign, INTEL tab
- 50+ tools registered and wired
- Boot sequence: 16-step autonomy stack
- Memory system: 6-layer (working→episodic→semantic→preference→project→system)
- LLM chains: recon_analyst, vuln_reasoner, triage_engine, strategy_advisor
- Reporting: CVSS 3.1 calculator, H1 formatter, report engine
- Intelligence: threat correlator, hacktivity monitor, coaching engine, context predictor
- Autonomy: hunt director (proposal-only), strategy learner, finding engine
- Security: rate limiter, sanitizer, audit log, scope gate, policy engine

### Known bugs fixed
- `kill_switch.py` broken TTS import → fixed (`from voice.tts import speak`)
- `self_healer.py` random speech bug → fixed (one-shot guard on _check_daemon_liveliness)
- `bridge/server.py` CORS wildcard → fixed (localhost-only)
- `/api/ops/graph` unauthenticated → fixed (token auth added)
- `policy/engine.py` always-True → fixed (interactive blocklist added)

### Speed optimizations applied
- Smart schema selection in worker.py (_slim_schemas): 40+ → ~12 schemas per call (~3000 token savings)
- History trim: 40 messages in memory, only last 16 sent to LLM
- max_tokens: 1024 → 350 in client.py
- MAX_ROUNDS: 6 → 4

### To activate recon
1. `RECON_LOOP_ENABLED = True` in config.py
2. Install: `go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest`
3. Install: `go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest`
4. Install: `go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest`

### To activate Chatterbox voice cloning
```
pip install chatterbox-tts>=0.1.6
pip install nvidia-cudnn-cu12  # for GPU acceleration
```
Drop reference WAVs (5-30s) into `voice/reference_clips/{persona}_primary.wav`
