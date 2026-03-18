"""
report_tools.py — Tool wrappers for finding engine operations.

These tools are called by the agent worker and registered in the tool registry.
All tool functions follow the same pattern as other tool modules.
"""
import logging
logger = logging.getLogger(__name__)

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from autonomy.finding_engine import FindingEngine
        _engine = FindingEngine()
    return _engine


def tool_draft_report(finding_id: int) -> str:
    from storage.db import get_db
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT id, program_id, title, severity, host, template_id, "
                "matched_at, raw_output, status FROM findings_canonical WHERE id=?",
                (finding_id,)
            ).fetchone()
            if not row:
                return f"Finding {finding_id} not found."
            finding = {
                "id": row[0], "title": row[2], "severity": row[3],
                "host": row[4], "template_id": row[5],
                "matched_at": row[6], "raw_output": row[7] or "",
            }
            program_id = row[1]
            prog_row = conn.execute(
                "SELECT id, name FROM programs WHERE id=?", (program_id,)
            ).fetchone()
        program = {"id": prog_row[0], "name": prog_row[1]} if prog_row else {"id": None, "name": "Unknown"}
        path = _get_engine().draft_report(finding, program, finding_id)
        return f"Report drafted: {path}"
    except Exception as e:
        return f"Error drafting report: {e}"


def tool_verify_finding(finding_id: int) -> str:
    from storage.db import get_db
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT host, template_id FROM findings_canonical WHERE id=?",
                (finding_id,)
            ).fetchone()
        if not row:
            return f"Finding {finding_id} not found."
        result = _get_engine().verify_finding({"host": row[0], "template_id": row[1]})
        status = "CONFIRMED" if result["verified"] else "UNCONFIRMED"
        if result.get("needs_operator"):
            status = "REQUIRES OPERATOR VERIFICATION"
        return f"Verification: {status} via {result['method']} — {result['evidence']}"
    except Exception as e:
        return f"Error verifying finding: {e}"


def tool_score_finding(finding_id: int) -> str:
    from storage.db import get_db
    from llm.local_judge import LocalJudge
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT title, severity, template_id FROM findings_canonical WHERE id=?",
                (finding_id,)
            ).fetchone()
        if not row:
            return f"Finding {finding_id} not found."
        score = LocalJudge().score_finding({
            "title": row[0], "severity": row[1], "template_id": row[2]
        })
        return (
            f"Bounty potential: {score['bounty_potential'].upper()} | "
            f"Priority: {score['priority_score']:.0f}/100 | "
            f"Reason: {score['reason']}"
        )
    except Exception as e:
        return f"Error scoring finding: {e}"


def tool_finding_digest() -> str:
    from storage.db import get_db
    try:
        with get_db() as conn:
            counts = conn.execute(
                "SELECT severity, COUNT(*) FROM findings_canonical GROUP BY severity"
            ).fetchall()
            top3 = conn.execute(
                "SELECT title, severity, host, bounty_potential FROM findings_canonical "
                "ORDER BY priority_score DESC LIMIT 3"
            ).fetchall()
        sev_order = ["critical", "high", "medium", "low", "info"]
        lines = ["=== FINDING DIGEST ==="]
        for sev, cnt in sorted(counts, key=lambda x: sev_order.index(x[0]) if x[0] in sev_order else 99):
            lines.append(f"  {sev.upper()}: {cnt}")
        if top3:
            lines.append("\nTop 3 by priority:")
            for t, s, h, bp in top3:
                lines.append(f"  [{s.upper()}] {t} — {h} (bounty: {bp})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error generating digest: {e}"


def tool_list_unverified_findings(program_id: int = None) -> str:
    from storage.db import get_db
    try:
        query  = "SELECT id, title, severity, host FROM findings_canonical WHERE verified=0"
        params = []
        if program_id:
            query += " AND program_id=?"
            params.append(program_id)
        with get_db() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return "No unverified findings."
        lines = [f"[{r[0]}] [{r[2].upper()}] {r[1]} — {r[3]}" for r in rows]
        return f"{len(rows)} unverified findings:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing findings: {e}"
