"""
autonomy/strategy_learner.py — Learn from scan results to improve recon workflows.

After every completed scan, records what worked and what didn't.
After 20+ samples per tool+tech_stack combo, generates improvement proposals
for operator review.

All workflow changes require operator approval — nothing auto-modifies pipelines.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class StrategyLearner:
    """Records tool effectiveness and generates improvement proposals."""

    @staticmethod
    def record_tool_run(
        tool_name:      str,
        target:         str,
        result:         dict,
        tech_stack:     str = "",
        duration_secs:  float = 0.0,
    ) -> None:
        """
        Record the outcome of a tool run. Call this after every tool execution.

        result: tool result dict with 'ok', 'artifacts' keys.
        """
        try:
            found_bug     = bool(result.get("artifacts")) and result.get("ok", False)
            false_pos     = result.get("meta", {}).get("false_positive", False)
            tech_key      = (tech_stack or "unknown")[:50]
            tool_key      = tool_name[:50]

            from storage.db import get_db
            with get_db() as conn:
                # Upsert tool effectiveness record
                existing = conn.execute(
                    "SELECT id, finding_rate, false_positive_rate, avg_duration_secs, sample_count "
                    "FROM tool_effectiveness WHERE tool_name=? AND tech_stack=?",
                    (tool_key, tech_key)
                ).fetchone()

                if existing:
                    n = existing["sample_count"] + 1
                    # Rolling average update
                    new_fr  = (existing["finding_rate"]        * existing["sample_count"] + (1 if found_bug else 0)) / n
                    new_fpr = (existing["false_positive_rate"] * existing["sample_count"] + (1 if false_pos else 0)) / n
                    new_dur = (existing["avg_duration_secs"]   * existing["sample_count"] + duration_secs) / n
                    conn.execute(
                        "UPDATE tool_effectiveness "
                        "SET finding_rate=?, false_positive_rate=?, avg_duration_secs=?, sample_count=?, last_updated=? "
                        "WHERE id=?",
                        (new_fr, new_fpr, new_dur, n, datetime.now().isoformat(), existing["id"])
                    )
                    # Generate proposal if enough samples
                    if n >= 20:
                        StrategyLearner._maybe_propose(tool_key, tech_key, new_fr, new_fpr, new_dur, n)
                else:
                    conn.execute(
                        "INSERT INTO tool_effectiveness "
                        "(tool_name, tech_stack, finding_rate, false_positive_rate, avg_duration_secs, sample_count, last_updated) "
                        "VALUES (?,?,?,?,?,1,?)",
                        (
                            tool_key, tech_key,
                            1.0 if found_bug else 0.0,
                            1.0 if false_pos else 0.0,
                            duration_secs,
                            datetime.now().isoformat()
                        )
                    )
        except Exception as e:
            logger.debug(f"[StrategyLearner] Record failed: {e}")

    @staticmethod
    def _maybe_propose(
        tool_name: str,
        tech_stack: str,
        finding_rate: float,
        false_positive_rate: float,
        avg_duration_secs: float,
        sample_count: int,
    ) -> None:
        """Create a workflow improvement proposal if stats are notable."""
        try:
            # Only propose if finding_rate is very low or FPR is very high
            if finding_rate >= 0.05 and false_positive_rate <= 0.20:
                return  # Performing adequately

            if finding_rate < 0.02:
                title = (
                    f"Low effectiveness: {tool_name} on {tech_stack} targets "
                    f"({finding_rate*100:.1f}% find rate over {sample_count} runs). "
                    "Consider deprioritizing or replacing in pipeline."
                )
            elif false_positive_rate > 0.30:
                title = (
                    f"High false positive rate: {tool_name} on {tech_stack} "
                    f"({false_positive_rate*100:.0f}% FPR). "
                    "Consider adding verification step to pipeline."
                )
            else:
                return

            from storage.db import get_db
            with get_db() as conn:
                # Check for existing unactioned proposal for this combo
                existing = conn.execute(
                    "SELECT id FROM research_items "
                    "WHERE source='strategy_learner' AND actioned=0 "
                    "AND title LIKE ?",
                    (f"%{tool_name}%{tech_stack}%",)
                ).fetchone()
                if existing:
                    return
                import json
                conn.execute(
                    "INSERT INTO research_items "
                    "(source, item_type, title, severity, url, affects_targets, actioned, raw_data, created_at) "
                    "VALUES (?,?,?,?,?,0,0,?,datetime('now'))",
                    (
                        "strategy_learner",
                        "workflow_proposal",
                        title[:200],
                        "info",
                        "",
                        json.dumps({
                            "tool_name":           tool_name,
                            "tech_stack":          tech_stack,
                            "finding_rate":        finding_rate,
                            "false_positive_rate": false_positive_rate,
                            "avg_duration_secs":   avg_duration_secs,
                            "sample_count":        sample_count,
                        }),
                    )
                )
            logger.info(f"[StrategyLearner] Workflow proposal created: {title[:80]}")
        except Exception as e:
            logger.debug(f"[StrategyLearner] Propose failed: {e}")

    @staticmethod
    def get_effectiveness_report() -> list[dict]:
        """Return tool effectiveness stats sorted by finding rate."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT tool_name, tech_stack, finding_rate, false_positive_rate, "
                    "avg_duration_secs, sample_count, last_updated "
                    "FROM tool_effectiveness "
                    "WHERE sample_count >= 3 "
                    "ORDER BY finding_rate DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.debug(f"[StrategyLearner] Report failed: {e}")
            return []


# ── Tool function ─────────────────────────────────────────────────────────────

def tool_strategy_effectiveness() -> dict:
    """Tool: show tool effectiveness stats from historical run data."""
    rows = StrategyLearner.get_effectiveness_report()
    if not rows:
        return {
            "ok": True,
            "output": "No effectiveness data yet. Data accumulates after 3+ runs per tool.",
            "error": None, "artifacts": [], "meta": {}
        }
    lines = ["Tool Effectiveness Report:"]
    for r in rows[:10]:
        lines.append(
            f"  {r['tool_name']} / {r['tech_stack']}: "
            f"find_rate={r['finding_rate']*100:.1f}% "
            f"fpr={r['false_positive_rate']*100:.0f}% "
            f"n={r['sample_count']}"
        )
    return {
        "ok": True,
        "output": "\n".join(lines),
        "error": None,
        "artifacts": [],
        "meta": {"rows": rows},
    }
