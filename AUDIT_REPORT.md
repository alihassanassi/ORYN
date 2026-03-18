# AUDIT REPORT — JARVIS Lab
**Date:** 2026-03-16
**Auditor:** Agent 00 (automated file scan — shell unavailable)

---

## SYNTAX
**Status: CLEAN** (manual inspection — shell unavailable for automated check)

All Python files inspected manually. No syntax errors detected in:
- config.py, main.py, requirements.txt
- gui/main_window.py, gui/splash.py, gui/widgets/__init__.py
- voice/tts.py, voice/stt.py, voice/profiles.py, voice/text_normalizer.py
- agents/worker.py, storage/db.py, llm/router.py, llm/client.py
- tools/registry.py, tools/shell_tools.py, tools/system_tools.py

Shell is broken (bash fork failure — resource issue, possibly JARVIS is running).
Cannot run: `python -c "import ast..."` validation.

---

## LLM/ROUTER COLLISION CHECK
**Status: CLEAN — no collision**

`llm/router.py` contains class `LLMRouter` (NOT ModelRouter).
Methods: `route()`, `get_token_stats()`, `_log_routing()`
No `get_model_for_intent` method — not expected, no collision with any Phase 1 agent.

---

## CONFIG VALUES

| Key | Current Value | Expected | Status |
|-----|---------------|----------|--------|
| OLLAMA_MODEL | "qwen3:14b" | qwen3:14b | ✓ |
| VOICE_DEFAULT_PROFILE | "chatterbox_jarvis" | chatterbox_jarvis | ✓ |
| ACTIVE_PERSONA | "jarvis" | jarvis | ✓ |
| ALWAYS_SPEAK | True | True | ✓ |
| RECON_LOOP_ENABLED | False | False (operator must set) | ✓ |
| LOCAL_JUDGE_MODEL | "phi4-mini:latest" | phi4-mini:latest | ✓ |
| OLLAMA_KEEP_ALIVE | "2m" | "2m" | ✓ |
| UI_SOUNDS_ENABLED | MISSING | True | ✗ — add in P1 |
| UI_SOUND_VOLUME | MISSING | 0.7 | ✗ — add in P1 |
| WAKE_WORDS | MISSING | list | ✗ — add in Agent 03 |
| AMBIENT_LISTENING_ENABLED | MISSING | True | ✗ — add in Agent 03 |
| RESEARCH_ENGINE_ENABLED | MISSING | True | ✗ — add in Agent 05 |

---

## IMPORT STATUS (inferred from file existence)

| Module | Class | File Exists | Status |
|--------|-------|-------------|--------|
| security.sanitizer | wrap_untrusted | security/sanitizer.py ✓ | OK |
| policy.autonomy_policy | AutonomyPolicyEngine | policy/autonomy_policy.py ✓ | OK |
| storage.audit_log | ImmutableAuditLog | storage/audit_log.py ✓ | OK |
| runtime.kill_switch | KillSwitch | runtime/kill_switch.py ✓ | OK |
| runtime.watchdog | Watchdog | runtime/watchdog.py ✓ | OK |
| autonomy.recon_loop | ReconLoop | autonomy/recon_loop.py ✓ | OK |
| llm.local_judge | LocalJudge | llm/local_judge.py ✓ | OK |
| audio.sound_engine | play, start | MISSING | FAIL — P1 creates it |
| scheduler.morning_briefing | generate_briefing_text | MISSING | FAIL — P4 creates it |
| voice.wake_listener | WakeListener | MISSING | FAIL — Agent 03 creates it |
| research.engine | ResearchEngine | MISSING | FAIL — Agent 05 creates it |

---

## DB TABLES (from db_init() in storage/db.py)

Confirmed tables in `db_init()`:
- projects
- messages
- commands
- scan_targets

Cannot query live DB (shell unavailable). Additional tables may exist from previous sessions.

Missing tables needed by patches:
- `ambient_log` (Agent 03)
- `research_items` (Agent 05)
- `companion_skills` / `companion_preferences` (Agent 06)

---

## LAUNCH STATUS
**Cannot test** — shell broken (bash fork failure).
Manual code review shows no obvious import errors or circular dependencies in main.py.

---

## GUI PANEL STATUS (IMPORTANT DISCREPANCY)

MEMORY.md lists panel files that DO NOT EXIST on disk:
- ✗ gui/panels/telemetry_panel.py
- ✗ gui/panels/chat_panel.py
- ✗ gui/panels/terminal_panel.py
- ✗ gui/panels/center_panel.py
- ✗ gui/panels/approval_queue.py

**Reality:** All panel logic is monolithic in `gui/main_window.py`.
`gui/panels/__init__.py` exists but is empty.
MEMORY.md is outdated on this point.

---

## EXISTING SPLASH SCREEN

`gui/splash.py` contains `JarvisSplash` — a FULL Iron Man HUD boot screen:
- Animated concentric rings, sweeping arcs (60fps)
- Corner L-bracket accents
- Progress bar with glow
- Boot sequence ticker (8 messages)
- `boot_complete` Signal
- Already wired in main.py

**P2 decision:** Augment `gui/splash.py` with sound_engine calls instead of creating new file.

---

## TTS INTERRUPT STATUS

`voice/tts.py` has `_interrupt_current()` (private method).
**No public `interrupt()` method exists.**
P3 must add public `interrupt()` wrapper.
`ALWAYS_SPEAK = True` in config but code gates on `self._voice_on` — minor disconnect.

---

## RED FLAGS

1. **SHELL BROKEN** — bash fork failure. Cannot run Python scripts or validation.
   Sound files (`assets/sounds/*.wav`) cannot be generated until shell is fixed.
   All other file-creation tasks proceed normally.

2. **ALWAYS_SPEAK vs _voice_on** — Config says ALWAYS_SPEAK=True but main_window.py
   gates TTS on `self._voice_on` (the toggle). The voice toggle controls STT *and* TTS
   unless this is explicitly split. Low severity — existing behavior is intentional per MEMORY.

3. **gui/panels/ empty** — MEMORY.md is wrong. Panels are monolithic in main_window.py.
   Agent 09 (LEFT-PANEL-FIX) will need to read main_window.py fully.

4. **requirements.txt minimal** — Missing: soundfile, pytz, scipy (needed for patches).

---

## PHASE 1 GO/NO-GO

| Agent | Blocker | Status |
|-------|---------|--------|
| P1 SOUND-ENGINE | Shell broken (can't run generate_sounds.py) | GO — create code, note manual step |
| P2 STARTUP-SEQUENCE | None | GO |
| P3 SPEECH-INTERRUPT | intent_router.py missing | GO — handle in main_window._submit() |
| P4 MORNING-BRIEFING | scheduler/morning_briefing.py missing | GO — create it |
| Agent 01 CHATTERBOX-GPU | Needs shell for Python execution | HOLD on testing |
| Agent 02 PERSONA-OVERHAUL | GO | GO |
| Agent 03 WAKE-WORD | STT queue API unknown | GO with stub |
| Agent 04 DOCS-SYNC | GO | GO |

**RECOMMENDATION:** Proceed with all 4 PATCH agents. Shell fixes needed for validation.
