"""
llm/chains/strategy_advisor.py — Given history + current program -> suggest next move.

SECURITY: Suggestion only. Does NOT execute anything. No network calls.
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from security.sanitizer import wrap_untrusted
except ImportError:
    def wrap_untrusted(text: str, source: str = "external") -> str:
        return f"[{source}]\n{text[:4000]}"


class StrategyAdvisor:
    """Generate a single recommended next action for the operator."""

    def suggest_next_action(
        self,
        operator_summary: str = "",
        program_data: dict = None,
        recent_findings: list = None,
    ) -> dict:
        """
        Given context, suggest one specific next recon or testing action.
        Returns suggestion dict. Never executes anything.
        """
        program_data    = program_data    or {}
        recent_findings = recent_findings or []

        safe_op   = wrap_untrusted(operator_summary[:800], "operator_model")
        safe_prog = wrap_untrusted(str(program_data)[:800], "program_data")
        safe_find = wrap_untrusted(str(recent_findings[:5])[:600], "recent_findings")

        prompt = (
            f"Operator profile: {safe_op}\n\n"
            f"Active program: {safe_prog}\n\n"
            f"Recent findings (last 5): {safe_find}\n\n"
            "Suggest ONE specific next recon or testing action. Be concrete:\n"
            "- What tool to run\n"
            "- What target or endpoint\n"
            "- What vulnerability class to look for\n"
            "- Why this is the best next move given the context\n\n"
            "Keep it to 3-4 sentences. This is a suggestion — the operator decides."
        )
        system = (
            "You are a senior bug bounty strategist advising an operator. "
            "Give one specific, actionable suggestion. "
            "Only suggest legal authorized testing actions within the program scope."
        )

        suggestion = ""
        try:
            import config as _c
            model = getattr(_c, 'OLLAMA_MODEL', 'qwen3:14b')
            from llm.client import LLM
            client = LLM(model=model)
            result = client.complete(
                [{"role": "user", "content": prompt}],
                system=system,
            )
            suggestion = result.get("content", "") or ""
        except Exception as e:
            logger.warning(f"[StrategyAdvisor] LLM call failed: {e}")

        if not suggestion:
            # Rule-based fallback
            if not recent_findings:
                suggestion = "Run subfinder on the active program's primary domain to enumerate subdomains. This is the first step in any recon workflow."
            else:
                suggestion = "Review the most recent findings for IDOR chains — individual IDORs are often low severity but chains escalate to critical."

        return {
            "ok":         True,
            "suggestion": suggestion,
            "source":     "llm" if suggestion else "fallback",
        }


def tool_suggest_next_action(program_id: int = 0) -> dict:
    """Tool: suggest the best next action given current program and operator history."""
    # Load operator summary
    operator_summary = ""
    try:
        from memory.operator_model import get_skill_summary
        operator_summary = get_skill_summary()
    except Exception:
        pass

    # Load program data
    program_data = {}
    try:
        from storage.db import get_program
        if program_id:
            program_data = get_program(int(program_id)) or {}
        else:
            from storage.db import get_active_program
            program_data = get_active_program() or {}
    except Exception:
        pass

    # Load recent findings
    recent_findings = []
    try:
        from storage.db import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT title, severity, status FROM findings_canonical ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
        recent_findings = [dict(r) for r in rows]
    except Exception:
        pass

    advisor = StrategyAdvisor()
    result = advisor.suggest_next_action(operator_summary, program_data, recent_findings)
    return {
        "ok":        result["ok"],
        "output":    result["suggestion"],
        "error":     None,
        "artifacts": [],
        "meta":      {"source": result["source"]},
    }
