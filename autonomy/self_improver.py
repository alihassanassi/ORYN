"""
autonomy/self_improver.py — JARVIS self-improvement engine.

JARVIS reviews his own recent responses and proposes improvements to his
own behavior — through the normal operator approval pipeline.

ANTI-HAL GUARANTEE:
  Self-improvement proposals NEVER auto-apply.
  Every change requires explicit operator approval.
  Only conversational config changes are proposed (prompts, response style).
  JARVIS can NEVER propose changes to safety systems, scope gates,
  kill switch, policy engine, or audit log.
  JARVIS cannot modify his own safety constraints. Ever.

This is JARVIS getting better at serving you.
Not JARVIS getting better at serving himself.
"""
from __future__ import annotations
import json
import logging
import threading

logger = logging.getLogger(__name__)

REVIEW_TRIGGER_CONVERSATIONS = 10   # review every N conversations
REVIEW_MESSAGE_WINDOW        = 20   # analyze last N messages

# Things JARVIS is NEVER allowed to propose changing
PROTECTED_SYSTEMS = [
    "kill_switch", "scope_gate", "policy_engine",
    "audit_log", "rate_limiter", "approval_system",
    "safety_constraints", "scope_enforcement",
    "blocked_commands", "autonomy_policy",
]


class SelfImprover:
    """
    Monitors conversation quality and proposes improvements to JARVIS's
    conversational behavior through the standard approval pipeline.
    """

    def __init__(self):
        self._conversation_count = 0
        self._lock = threading.Lock()

    def on_conversation_complete(self) -> None:
        """Call after each completed conversation turn."""
        with self._lock:
            self._conversation_count += 1
            if self._conversation_count >= REVIEW_TRIGGER_CONVERSATIONS:
                self._conversation_count = 0
                threading.Thread(
                    target=self._run_self_review,
                    daemon=True,
                    name="jarvis-self-improver",
                ).start()

    def _run_self_review(self) -> None:
        """Analyze recent responses and propose one improvement."""
        try:
            import config as _cfg
            if not getattr(_cfg, 'SELF_IMPROVEMENT_ENABLED', True):
                return
            recent = self._get_recent_exchanges()
            if not recent:
                return
            proposal = self._analyze_and_propose(recent)
            if proposal:
                self._submit_proposal(proposal)
        except Exception as e:
            logger.debug("[SelfImprover] Review error: %s", e)

    def _get_recent_exchanges(self) -> list[dict]:
        try:
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT role, content FROM messages "
                    "ORDER BY rowid DESC LIMIT ?",
                    (REVIEW_MESSAGE_WINDOW,)
                ).fetchall()
            return [{"role": r[0], "content": r[1]} for r in rows]
        except Exception as e:
            logger.debug("[SelfImprover] DB read error: %s", e)
            return []

    def _analyze_and_propose(self, exchanges: list[dict]) -> dict | None:
        """Use LocalJudge (phi4-mini) to analyze exchanges and propose one improvement."""
        try:
            from llm.local_judge import LocalJudge
            judge = LocalJudge()

            exchange_text = "\n".join(
                f"{e['role'].upper()}: {(e['content'] or '')[:200]}"
                for e in exchanges[:10]
            )

            prompt = (
                "You are JARVIS reviewing your own recent conversations.\n"
                "Identify ONE specific improvement to your behavior.\n"
                "Only propose changes to: persona response style, conversation handling, "
                "or emotional intelligence. NEVER propose changes to safety systems.\n\n"
                f"Recent exchanges:\n{exchange_text}\n\n"
                "Respond ONLY in JSON: "
                '{"category": "...", "issue": "...", "proposal": "...", "confidence": 0.0}'
            )

            result = judge.complete_fast(prompt, max_tokens=200)
            # Strip markdown fences if present
            clean = result.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            data = json.loads(clean.strip())

            # Safety check — never propose changing protected systems
            proposal_text = (data.get('proposal', '') + data.get('issue', '')).lower()
            if any(s in proposal_text for s in PROTECTED_SYSTEMS):
                logger.info("[SelfImprover] Blocked proposal targeting safety system")
                return None

            if float(data.get('confidence', 0)) < 0.6:
                return None

            return data
        except Exception as e:
            logger.debug("[SelfImprover] Analysis error: %s", e)
            return None

    def _submit_proposal(self, proposal: dict) -> None:
        """Submit improvement proposal to the operator approval queue."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                # pending_approvals table may not exist on all installs — create if needed
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS pending_approvals "
                    "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "type TEXT, title TEXT, description TEXT, "
                    "data TEXT, created_at TEXT)"
                )
                conn.execute(
                    "INSERT INTO pending_approvals "
                    "(type, title, description, data, created_at) "
                    "VALUES (?, ?, ?, ?, datetime('now'))",
                    (
                        "self_improvement",
                        f"Self-improvement: {proposal.get('category', 'general')}",
                        proposal.get('issue', ''),
                        json.dumps(proposal),
                    )
                )
            logger.info(
                "[SelfImprover] Proposed improvement: %s",
                proposal.get('category', 'unknown')
            )
        except Exception as e:
            logger.debug("[SelfImprover] Submit error: %s", e)


# Module-level singleton — imported lazily so it never blocks boot
_improver: SelfImprover | None = None


def get_self_improver() -> SelfImprover:
    global _improver
    if _improver is None:
        _improver = SelfImprover()
    return _improver


def on_conversation_complete() -> None:
    """Convenience function called from agents/worker.py after each turn."""
    try:
        get_self_improver().on_conversation_complete()
    except Exception:
        pass
