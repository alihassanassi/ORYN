"""
Preference Engine — learns operator approval patterns. Advisory only.

Security properties:
  - Preference data is SUGGESTIONS ONLY — never auto-approves
  - Scope violations always escalate regardless of preference history
  - Preference data capped to 90 days to prevent stale-pattern drift
  - No raw approval log stored — aggregated statistics only (data minimization)
  - Cannot override AutonomyPolicyEngine hard rules under any circumstances

CRITICAL SEPARATION: preference engine feeds the operator's decision UI.
It NEVER feeds the AutonomyPolicyEngine. Operator approval ≠ auto-approval.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class PreferenceEngine:

    def record_approval(
        self, tool_name: str, args: dict, approved: bool, modified: bool = False
    ) -> None:
        """
        Records an operator decision for pattern learning.
        Stores aggregated stats only — NOT raw args (data minimization).
        """
        # Never record approvals that involved scope violations
        target  = args.get("target", "")
        prog_id = args.get("program_id")
        if target and prog_id:
            try:
                from bridge.scope import is_in_scope
                if not is_in_scope(target, prog_id):
                    logger.debug("[PreferenceEngine] skipping record for out-of-scope target")
                    return
            except Exception:
                pass

        from storage.db import get_db
        try:
            with get_db() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO jarvis_preferences
                    (tool_name, approved_count, rejected_count, modified_count,
                     last_seen, created_at)
                    VALUES (?, 0, 0, 0, datetime('now'), datetime('now'))
                """, (tool_name,))
                # field is strictly one of two hardcoded column names — not user input.
                # Use explicit if/else to avoid any f-string in SQL.
                if modified:
                    conn.execute(
                        "UPDATE jarvis_preferences SET modified_count=modified_count+1, "
                        "last_seen=datetime('now') WHERE tool_name=?", (tool_name,)
                    )
                if approved:
                    conn.execute(
                        "UPDATE jarvis_preferences SET approved_count=approved_count+1, "
                        "last_seen=datetime('now') WHERE tool_name=?", (tool_name,)
                    )
                else:
                    conn.execute(
                        "UPDATE jarvis_preferences SET rejected_count=rejected_count+1, "
                        "last_seen=datetime('now') WHERE tool_name=?", (tool_name,)
                    )
                # Purge stale data older than 90 days
                conn.execute(
                    "DELETE FROM jarvis_preferences WHERE last_seen < datetime('now','-90 days')"
                )
        except Exception as e:
            logger.debug("[PreferenceEngine] record failed: %s", e)

    def get_approval_probability(self, tool_name: str, args: dict) -> float:
        """
        Returns historical approval rate for this tool.
        INFORMATIONAL only — never used to auto-approve.
        Returns 0.0 if insufficient data (< 3 decisions).
        """
        from storage.db import get_db
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT approved_count, rejected_count FROM jarvis_preferences "
                    "WHERE tool_name=?",
                    (tool_name,)
                ).fetchone()
                if not row:
                    return 0.0
                total = (row[0] or 0) + (row[1] or 0)
                if total < 3:
                    return 0.0
                return (row[0] or 0) / total
        except Exception:
            return 0.0

    def suggest_policy_updates(self) -> list[str]:
        """
        Returns suggestions for the operator — advisory only.
        Presented in Settings panel for operator review.
        NEVER applied automatically.
        """
        from storage.db import get_db
        suggestions = []
        try:
            with get_db() as conn:
                rows = conn.execute("""
                    SELECT tool_name, approved_count, rejected_count
                    FROM jarvis_preferences
                    WHERE approved_count + rejected_count >= 10
                """).fetchall()
            for tool, approved, rejected in rows:
                total = (approved or 0) + (rejected or 0)
                if total == 0:
                    continue
                rate = (approved or 0) / total
                if rate >= 0.95:
                    suggestions.append(
                        f"You've approved '{tool}' {approved}/{total} times. "
                        f"Consider adding it to the policy allowlist for faster processing."
                    )
                elif rate <= 0.15:
                    suggestions.append(
                        f"You've rejected '{tool}' {rejected}/{total} times. "
                        f"Consider reviewing whether this tool should remain in the autonomous allowlist."
                    )
        except Exception as e:
            logger.debug("[PreferenceEngine] suggest failed: %s", e)
        return suggestions

    def get_preferences_summary(self) -> dict:
        """Returns aggregated operator preference profile."""
        from storage.db import get_db
        try:
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT tool_name, approved_count, rejected_count, modified_count "
                    "FROM jarvis_preferences "
                    "ORDER BY approved_count+rejected_count DESC LIMIT 20"
                ).fetchall()
            tools = []
            for tool, a, r, m in rows:
                total = (a or 0) + (r or 0)
                if total > 0:
                    tools.append({
                        "tool":              tool,
                        "total":             total,
                        "approval_rate":     round((a or 0) / total, 2),
                        "modification_rate": round((m or 0) / total, 2),
                    })
            return {
                "tools":            tools,
                "suggestion_count": len(self.suggest_policy_updates()),
            }
        except Exception:
            return {"tools": [], "suggestion_count": 0}
