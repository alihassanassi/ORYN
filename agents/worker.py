"""
agents/worker.py — AgentWorker: one full conversational turn with tool calling.

Runs off the main thread via QThreadPool. Emits Qt signals so all GUI updates
are queued back to the main thread automatically.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from llm.client import LLM
from llm.prompts import JARVIS_PERSONA, PERSONA_PROMPTS
from security.sanitizer import _strip_injections, wrap_untrusted
from storage.db import get_notes, get_recent_commands, log_command
from tools.registry import TOOL_SCHEMAS, dispatch, dispatch_parallel

try:
    from voice.response_translator import translate_tool_result as _translate_tool_result
    _TRANSLATOR_AVAILABLE = True
except Exception:
    _TRANSLATOR_AVAILABLE = False


class _AgentSignals(QObject):
    reply        = Signal(str)
    token        = Signal(str)        # streaming text chunk
    tool_start   = Signal(str, str)   # tool_name, display_args
    tool_end     = Signal(str, str)   # tool_name, output
    need_confirm = Signal(str, str)   # tool_name, command
    done         = Signal()
    error        = Signal(str)


class AgentWorker(QRunnable):
    """Runs one full agent turn (possibly multi-step with tools) off the main thread."""

    MAX_ROUNDS = 4  # 6→4: cuts worst-case tool loop latency by 33%

    # ── Smart schema selector ─────────────────────────────────────────────────
    # Sending all 40+ schemas (~4000 tokens) on every call costs ~5s of prefill.
    # Map intent keywords → tool groups; only send what this turn actually needs.
    _CORE_TOOLS = frozenset({
        "system_status", "run_command", "open_app",
        "list_projects", "switch_project", "save_note", "read_notes",
        "token_stats", "list_capabilities", "self_reflect",
    })
    _SCHEMA_GROUPS: dict[str, frozenset] = {
        "recon":    frozenset({"run_subfinder", "run_httpx", "run_nuclei",
                               "dns_lookup", "whois_lookup", "geolocate_ip",
                               "url_analyze", "scope_check"}),
        "findings": frozenset({"save_finding", "list_findings", "save_target",
                               "list_targets", "draft_report", "verify_finding",
                               "score_finding", "list_unverified_findings",
                               "finding_digest", "list_report_drafts", "calculate_cvss"}),
        "programs": frozenset({"list_programs", "create_program", "add_scope",
                               "program_status", "set_program_status"}),
        "voice":    frozenset({"list_voices", "set_voice", "list_voice_profiles",
                               "set_voice_profile", "switch_persona",
                               "list_clips", "add_clip", "remove_clip", "validate_clip"}),
        "system":   frozenset({"cleanup_disk", "get_clipboard"}),
        "research": frozenset({"research_digest", "search_research", "morning_briefing",
                               "intel_correlate_now", "intel_status"}),
        "strategy": frozenset({"strategy_briefing", "preference_summary",
                               "recon_loop_start", "recon_loop_stop",
                               "recon_loop_status", "recon_loop_pause",
                               "kill_switch_trigger", "kill_switch_reset",
                               "watchdog_status", "hunt_director_status",
                               "hunt_director_enable", "hunt_director_disable",
                               "strategy_effectiveness"}),
        "memory":   frozenset({"db_maintenance"}),
        "chains":   frozenset({"analyze_scan_results", "reason_vulnerability",
                               "triage_findings", "suggest_next_action"}),
        "operator": frozenset({"operator_model_summary", "operator_blindspots"}),
    }
    _GROUP_TRIGGERS = [
        (re.compile(r"scan|subfinder|httpx|nuclei|target|dns|whois|geolocat|url.analyz|scope", re.I),
         ["recon"]),
        (re.compile(r"finding|report|draft|verify|score|unverified|triage|cvss|bounty", re.I),
         ["findings"]),
        (re.compile(r"program|scope|create.program|add.scope|bug.bounty", re.I),
         ["programs"]),
        (re.compile(r"voice|persona|switch.to|set.voice|profile|clip|chatterbox", re.I),
         ["voice"]),
        (re.compile(r"disk|cleanup|temp.files|recycle|clipboard", re.I),
         ["system"]),
        (re.compile(r"briefing|morning|research|digest|intel|cve|vuln", re.I),
         ["research"]),
        (re.compile(r"strategy|mission|stage|kill.switch|watchdog|recon.loop|hunt", re.I),
         ["strategy"]),
        (re.compile(r"database|maintenance|vacuum|db.stats", re.I),
         ["memory"]),
        (re.compile(r"analyz.*scan|reason.*vuln|triage|next.action", re.I),
         ["chains"]),
        (re.compile(r"operator.model|blindspot|skill|my.weak", re.I),
         ["operator"]),
    ]

    @staticmethod
    def _slim_schemas(text: str) -> list[dict]:
        """Return only schemas relevant to this input (~10-12 vs 40+), saving ~3000 prefill tokens."""
        try:
            selected = set(AgentWorker._CORE_TOOLS)
            for pattern, groups in AgentWorker._GROUP_TRIGGERS:
                if pattern.search(text):
                    for g in groups:
                        selected.update(AgentWorker._SCHEMA_GROUPS.get(g, frozenset()))
            slim = [s for s in TOOL_SCHEMAS if s.get("function", {}).get("name") in selected]
            return slim if slim else TOOL_SCHEMAS  # safety fallback
        except Exception:
            return TOOL_SCHEMAS  # never break the agent loop

    # Continuation words — "go", "yes", "do it" etc. must hit the tool path
    # so the LLM can look at history and execute the last proposed action.
    _CONTINUATION_WORDS: frozenset = frozenset({
        'go', 'yes', 'do it', 'proceed', 'run', 'run it',
        'execute', 'fire', 'launch', 'start', 'continue',
        'approved', 'approve', 'ok', 'okay', 'sure', 'yep',
        'do that', 'go ahead', 'make it so', 'carry on',
    })

    _TOOL_RE = re.compile(
        r'\b(clean|cleanup|free\s+space|temp\s+files|recycle|'
        r'scan|run|open|launch|execute|ssh|ping|nmap|wireshark|burp|'
        r'terminal|powershell|cmd|command|check|status|list\s+project|'
        r'switch\s+project|save\s+note|read\s+note|disk|cpu|ram|memory|'
        r'network|process|voice|what.{0,20}(running|status)|'
        # Program management
        r'program|scope|create\s+program|add\s+scope|'
        # Recon / targets / findings
        r'target|finding|findings|report|draft|verify\s+finding|score|'
        r'unverified|triage|recon|subfinder|httpx|nuclei|ffuf|'
        # Intelligence / research / briefing
        r'briefing|morning|research|digest|intel|cve|vulnerability|'
        # Network tools
        r'weather|dns|whois|geolocat|clipboard|url\s+analyz|'
        # Strategy / autonomy
        r'strategy|mission|stage|kill\s+switch|watchdog|recon\s+loop|'
        # DB / admin
        r'database|maintenance|vacuum|token\s+stats|preference|capabilities|'
        # Voice / persona
        r'persona|switch\s+to\s+(jarvis|india|ct7567|morgan)|voice\s+profile|'
        r'set\s+voice|list\s+voice|'
        # Memory subsystem
        r'remember|recall|forget|pin\s+memory|inspect\s+memory|memory\s+stats|'
        r'memory\s+hygiene|what\s+do\s+you\s+know|what\s+did\s+i\s+say)\b',
        re.IGNORECASE,
    )

    @staticmethod
    def _needs_tools(text: str) -> bool:
        # Continuation commands must hit the full tool path so the LLM
        # can inspect history and execute the last proposed action.
        if text.lower().strip() in AgentWorker._CONTINUATION_WORDS:
            return True
        return bool(AgentWorker._TOOL_RE.search(text))

    def __init__(self, llm: LLM, project: str, user_input: str,
                 prior_history: list[dict]):
        super().__init__()
        self.llm            = llm
        self.project        = project
        self.user_input     = user_input
        self.prior_history  = prior_history
        self.signals        = _AgentSignals()
        self._confirm_result: Optional[bool] = None
        self._confirm_event = threading.Event()

    def confirm(self, approved: bool):
        self._confirm_result = approved
        self._confirm_event.set()

    def _fire_llm_extraction(
        self,
        safe_input: str,
        response_text: str,
        project_id,
        session_id: str,
    ) -> None:
        """
        Fire-and-forget LLM-assisted memory extraction in a daemon thread.
        Never blocks response delivery. Silently swallows all errors.
        """
        _llm_ref = self.llm

        def _run():
            try:
                from memory.promoter import MemoryPromoter
                _promoter = MemoryPromoter()
                _promoter.extract_with_llm(
                    user_message=safe_input,
                    assistant_response=response_text,
                    project_id=project_id,
                    session_id=session_id,
                    llm_client=_llm_ref,
                )
            except Exception:
                pass

        try:
            threading.Thread(target=_run, daemon=True).start()
        except Exception:
            pass

    @Slot()
    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.done.emit()

    def _run_inner(self):
        notes = get_notes(self.project)
        cmds  = get_recent_commands(self.project, 4)
        # Sanitize operator input — strip injection patterns before LLM ingestion
        safe_input = _strip_injections(self.user_input)

        parts = [f"[Active project: {self.project}]"]
        if notes:
            snippet = notes[-400:].replace("\n", " | ")
            safe_notes = wrap_untrusted(snippet, "stored_notes")
            parts.append(f"[Project notes: {safe_notes}]")
        if cmds:
            safe_cmds = wrap_untrusted(", ".join(cmds), "recent_commands")
            parts.append(f"[Recent commands: {safe_cmds}]")
        try:
            from voice.wake_listener import get_ambient_context_global
            _ambient = get_ambient_context_global(3)
            if _ambient:
                parts.append(f"[{_ambient}]")
        except Exception:
            pass
        parts.append(safe_input)
        enriched = "\n".join(parts)

        history = list(self.prior_history)
        history.append({"role": "user", "content": enriched})

        # Select persona-appropriate system prompt
        try:
            import config as _pcfg
            _active_persona = getattr(_pcfg, 'ACTIVE_PERSONA', 'jarvis')
            system_content = PERSONA_PROMPTS.get(_active_persona, JARVIS_PERSONA)
        except Exception:
            system_content = JARVIS_PERSONA

        # Operator adaptation hint (companion_db)
        try:
            from storage.companion_db import get_adaptation_hint
            import config as _c
            _hint = get_adaptation_hint(getattr(_c, 'ACTIVE_PERSONA', 'jarvis'))
            if _hint:
                system_content = system_content + f"\n\n{_hint}"
        except Exception:
            pass

        # Memory context injection — prepend relevant memories to system prompt
        # Max 800 tokens; skipped silently on any error
        _mem_project_id = None
        _mem_session_id = ""
        try:
            from memory.manager import MemoryManager
            import config as _mc
            _persona = getattr(_mc, 'ACTIVE_PERSONA', 'jarvis')
            _mm = MemoryManager()
            _mem_session_id = _mm.get_session_id()
            _project_id = None
            try:
                from storage.db import get_db as _gdb
                with _gdb() as _dbc:
                    _proj_row = _dbc.execute(
                        "SELECT id FROM projects WHERE name=? LIMIT 1", (self.project,)
                    ).fetchone()
                    if _proj_row:
                        _project_id = _proj_row[0]
            except Exception:
                pass
            _mem_project_id = _project_id
            _mem_ctx = _mm.recall(
                query=safe_input,
                project_id=_project_id,
                persona=_persona,
                max_tokens=800,
            )
            if _mem_ctx:
                system_content = system_content + f"\n\n{_mem_ctx}"
            # Ingest user message for memory extraction (non-blocking)
            try:
                _mm.ingest_from_message("user", safe_input, project_id=_project_id)
            except Exception:
                pass
        except Exception:
            pass  # memory system never blocks the agent loop

        # Context predictor — inject preloaded session context when fresh
        try:
            from intelligence.context_predictor import get_context_predictor
            _preloaded = get_context_predictor().get_preloaded_context()
            if _preloaded:
                _ctx_summary = (
                    f"[Pre-session context: "
                    f"{len(_preloaded.get('messages', []))} recent messages loaded, "
                    f"{len(_preloaded.get('research_items', []))} threat items pending, "
                    f"{len(_preloaded.get('hunt_proposals', []))} hunt proposals queued]"
                )
                system_content = system_content + f"\n\n{_ctx_summary}"
        except Exception:
            pass

        # Fast-path: skip tool schema when no tool action is needed
        if not self._needs_tools(safe_input):
            full = ""
            for chunk in self.llm.complete_stream(history, system=system_content):
                self.signals.token.emit(chunk)
                full += chunk
            _fast_reply = full or "I'm listening, sir. What do you need?"
            # Check for pending coaching hint
            try:
                from intelligence.coaching_engine import CoachingEngine
                _hint = CoachingEngine.get_hint_if_due()
                if _hint:
                    _fast_reply = _fast_reply + f"\n\n[Coach: {_hint}]"
            except Exception:
                pass
            self.signals.reply.emit(_fast_reply)
            try:
                from runtime.watchdog import record_llm_success
                record_llm_success("ollama")
            except Exception:
                pass
            # LLM-assisted extraction (fire-and-forget, non-blocking)
            self._fire_llm_extraction(
                safe_input, _fast_reply, _mem_project_id, _mem_session_id
            )
            # Self-improvement counter (fire-and-forget)
            try:
                from autonomy.self_improver import on_conversation_complete
                on_conversation_complete()
            except Exception:
                pass
            return

        _schemas = AgentWorker._slim_schemas(safe_input)
        for _round in range(self.MAX_ROUNDS):
            resp       = self.llm.complete(history, system=system_content, tools=_schemas)
            content    = resp.get("content", "")
            tool_calls = resp.get("tool_calls", [])

            if not tool_calls:
                _tool_reply = content or "Ready when you are, sir."
                self.signals.reply.emit(_tool_reply)
                try:
                    from runtime.watchdog import record_llm_success
                    record_llm_success("ollama")
                except Exception:
                    pass
                # LLM-assisted extraction (fire-and-forget, non-blocking)
                self._fire_llm_extraction(
                    safe_input, _tool_reply, _mem_project_id, _mem_session_id
                )
                # Self-improvement counter (fire-and-forget)
                try:
                    from autonomy.self_improver import on_conversation_complete
                    on_conversation_complete()
                except Exception:
                    pass
                return

            history.append({
                "role":       "assistant",
                "content":    content or None,
                "tool_calls": [
                    {
                        "id":       tc["id"],
                        "type":     "function",
                        "function": {
                            "name":      tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in tool_calls
                ],
            })

            # Parallel execution for multi-tool responses
            if len(tool_calls) > 1:
                try:
                    _parallel_results = dispatch_parallel([
                        {"name": tc["name"], "arguments": tc["arguments"]}
                        for tc in tool_calls
                    ])
                except Exception:
                    _parallel_results = None
            else:
                _parallel_results = None

            for _tc_idx, tc in enumerate(tool_calls):
                name    = tc["name"]
                args    = tc["arguments"]
                tc_id   = tc["id"]

                display = json.dumps(args) if args else ""
                self.signals.tool_start.emit(name, display)

                # Use parallel result if available, otherwise sequential dispatch
                if _parallel_results is not None and _tc_idx < len(_parallel_results):
                    output, needs_confirm = _parallel_results[_tc_idx]
                else:
                    output, needs_confirm = dispatch(name, args)

                if needs_confirm:
                    try:
                        import config as _acfg
                        _auto = getattr(_acfg, 'AUTO_AGENT_ENABLED', False)
                    except Exception:
                        _auto = False
                    if _auto:
                        # Auto-agent active — execute without waiting for operator
                        args["confirmed"] = True
                        output, _ = dispatch(name, args)
                    else:
                        self._confirm_event.clear()
                        self.signals.need_confirm.emit(name, output)
                        self._confirm_event.wait(timeout=120)
                        if self._confirm_result:
                            args["confirmed"] = True
                            output, _ = dispatch(name, args)
                        else:
                            output = "Operator declined execution."

                self.signals.tool_end.emit(name, output)

                # Notify coaching engine of activity
                try:
                    from intelligence.coaching_engine import record_activity
                    record_activity(name)
                except Exception:
                    pass

                # Record tool effectiveness data point
                try:
                    from autonomy.strategy_learner import StrategyLearner
                    StrategyLearner.record_tool_run(
                        tool_name=name,
                        tech_stack="unknown",
                        found_something=bool("finding" in output.lower() or "vuln" in output.lower()),
                        is_false_positive=False,
                        duration_secs=0.0,
                    )
                except Exception:
                    pass

                if name == "run_command":
                    log_command(self.project, args.get("command", ""), output)

                # Translate raw tool output into natural language before LLM
                # re-ingestion — kills robotic "pipeline stage N" phrasing.
                if _TRANSLATOR_AVAILABLE:
                    try:
                        import config as _cfg
                        _persona = getattr(_cfg, 'ACTIVE_PERSONA', 'jarvis')
                        output = _translate_tool_result(
                            name,
                            {'ok': True, 'output': output},
                            _persona,
                        )
                    except Exception:
                        pass  # fall back to raw output — never crash the agent

                # Wrap tool output before LLM re-ingestion — prevents injected
                # content from scanned hosts from hijacking the conversation.
                safe_output = wrap_untrusted(output, source=name)

                history.append({
                    "role":         "tool",
                    "tool_call_id": tc_id,
                    "content":      safe_output,
                    "name":         name,
                })

        self.signals.reply.emit(
            "I've completed the maximum tool rounds for this request, sir. "
            "All available approaches have been attempted."
        )
