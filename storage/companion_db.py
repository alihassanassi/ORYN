"""
storage/companion_db.py — Operator companion model for JARVIS.

Tracks operator skill level, work patterns, and persona preferences.
Used to inject adaptation hints into every LLM system prompt so
JARVIS gets smarter about how to talk to the operator over time.

All data stays local. Nothing leaves the machine.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

SKILL_DOMAINS = [
    'web_recon', 'vulnerability_assessment', 'report_writing',
    'scope_analysis', 'tool_usage', 'bug_bounty_strategy',
]


def update_skill_observation(domain: str, evidence: str, level_delta: float) -> None:
    """
    Record a skill observation.
    level_delta > 0: expert signal (used advanced technique correctly)
    level_delta < 0: learning signal (asked a basic question)
    level_delta = 0: neutral (correction, no skill delta)
    """
    if domain not in SKILL_DOMAINS:
        return
    try:
        from storage.db import get_db
        with get_db() as conn:
            conn.execute(
                "INSERT INTO companion_skills (domain, evidence, level_delta, created_at) "
                "VALUES (?,?,?,datetime('now'))",
                (domain, evidence[:200], float(level_delta))
            )
    except Exception as e:
        logger.debug("[Companion] skill update error: %s", e)


def get_operator_profile() -> dict:
    """Returns current operator profile for display or context injection."""
    try:
        from storage.db import get_db
        with get_db() as conn:
            skills: dict[str, float] = {}
            for domain in SKILL_DOMAINS:
                row = conn.execute(
                    "SELECT AVG(level_delta) FROM ("
                    "SELECT level_delta FROM companion_skills "
                    "WHERE domain=? ORDER BY created_at DESC LIMIT 20"
                    ")", (domain,)
                ).fetchone()
                skills[domain] = round(float(row[0] or 0.5), 2)

            recent = conn.execute(
                "SELECT COUNT(*), MAX(ts) FROM messages "
                "WHERE ts > datetime('now','-7 days')"
            ).fetchone()

            try:
                wins = conn.execute(
                    "SELECT COUNT(*), SUM(CAST(COALESCE(severity,'0') AS REAL)) "
                    "FROM findings WHERE created_at > datetime('now','-365 days')"
                ).fetchone()
                findings_count = wins[0] if wins else 0
            except Exception:
                findings_count = 0

        return {
            'skill_levels':   skills,
            'messages_7d':    recent[0] if recent else 0,
            'last_active':    recent[1] if recent else None,
            'findings_count': findings_count,
        }
    except Exception as e:
        logger.debug("[Companion] profile error: %s", e)
        return {}


def get_adaptation_hint(persona: str = 'jarvis') -> str:
    """
    One-line hint injected into every LLM system prompt.
    Tells the LLM how to calibrate depth/vocabulary for this operator.
    """
    try:
        profile = get_operator_profile()
        skills  = profile.get('skill_levels', {})

        recon_level = skills.get('web_recon', 0.5)
        vuln_level  = skills.get('vulnerability_assessment', 0.5)
        avg_skill   = (recon_level + vuln_level) / 2

        if avg_skill < 0.3:
            depth = "explain foundational concepts clearly; operator is still learning"
        elif avg_skill < 0.6:
            depth = "assume intermediate knowledge; skip basics but explain advanced topics"
        else:
            depth = "treat as expert peer; use technical shorthand freely"

        findings = profile.get('findings_count', 0)
        context  = (f"Operator has {findings} recorded finding{'s' if findings != 1 else ''}."
                    if findings > 0 else "Operator is building their bug bounty track record.")

        return f"Operator calibration: {depth}. {context}"
    except Exception as e:
        logger.debug("[Companion] adaptation hint error: %s", e)
        return ""
