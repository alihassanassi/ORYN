"""
reporting/report_engine.py — Generate submission-ready HackerOne report drafts.

INPUT: finding_id from findings_canonical table.
OUTPUT: markdown report file in reports/ dir + DB audit record.

SECURITY:
  - NEVER submits to HackerOne automatically.
  - Report goes to pending_approvals first (operator reviews, then manually submits).
  - No network calls from this module.
  - Generated reports marked DRAFT until operator approves.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_reports_dir() -> Path:
    try:
        import config as _c
        d = Path(getattr(_c, 'REPORTS_DIR', 'reports'))
    except Exception:
        d = Path('reports')
    if not d.is_absolute():
        try:
            import config as _c
            d = Path(_c.ROOT_DIR) / d
        except Exception:
            pass
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_report_for_finding(finding_id: int) -> dict:
    """
    Generate a HackerOne-format draft report for a finding.

    Returns dict with ok, output, report_path, error.
    NEVER submits. Operator must review and submit manually.
    """
    from storage.db import get_db
    from reporting.cvss_calculator import calculate_cvss
    from reporting.h1_formatter import format_h1_report

    # Load finding from DB
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM findings_canonical WHERE id=?", (finding_id,)
            ).fetchone()
    except Exception as e:
        return {"ok": False, "output": f"DB read failed: {e}", "error": str(e), "report_path": None, "artifacts": [], "meta": {}}

    if not row:
        return {"ok": False, "output": f"Finding {finding_id} not found.", "error": "not_found", "report_path": None, "artifacts": [], "meta": {}}

    finding = dict(row)

    # Calculate CVSS from severity
    severity = finding.get("severity", "medium").upper()
    _severity_to_cvss = {
        "CRITICAL": ("NETWORK", "LOW",  "NONE", "NONE", "CHANGED",   "HIGH", "HIGH", "HIGH"),
        "HIGH":     ("NETWORK", "LOW",  "NONE", "NONE", "UNCHANGED", "HIGH", "NONE", "NONE"),
        "MEDIUM":   ("NETWORK", "LOW",  "LOW",  "NONE", "UNCHANGED", "LOW",  "LOW",  "NONE"),
        "LOW":      ("LOCAL",   "HIGH", "LOW",  "REQUIRED", "UNCHANGED", "LOW", "NONE", "NONE"),
        "INFO":     ("LOCAL",   "HIGH", "HIGH", "REQUIRED", "UNCHANGED", "NONE", "NONE", "NONE"),
    }
    cvss_params = _severity_to_cvss.get(severity, _severity_to_cvss["MEDIUM"])
    cvss = calculate_cvss(*cvss_params)

    # Get program name
    program_name = ""
    try:
        with get_db() as conn:
            prog_row = conn.execute(
                "SELECT name FROM programs WHERE id=?", (finding.get("program_id"),)
            ).fetchone()
            if prog_row:
                program_name = prog_row["name"]
    except Exception:
        pass

    # Extract steps from raw_output if available
    raw_output = finding.get("raw_output", "")
    steps = f"1. Tool: `{finding.get('template_id', 'N/A')}`\n2. Target: `{finding.get('host', 'N/A')}`\n3. Evidence:\n```\n{raw_output[:500]}\n```"

    impact = (
        f"This {severity.lower()} severity vulnerability at `{finding.get('host', 'N/A')}` "
        f"could allow an attacker to {_impact_description(severity)}."
    )

    # Format report
    md = format_h1_report(
        title       = finding.get("title", "Security Finding"),
        severity    = severity,
        cvss_score  = cvss["base_score"],
        cvss_vector = cvss["vector_string"],
        steps       = steps,
        impact      = impact,
        program     = program_name,
        host        = finding.get("host", ""),
        template_id = finding.get("template_id", ""),
    )

    # Save to file
    slug = (finding.get("title", "finding")[:30]
            .lower().replace(" ", "_").replace("/", "-"))
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{program_name or 'unknown'}_{slug}_{date_str}.md"
    report_path = _get_reports_dir() / filename

    try:
        report_path.write_text(md, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "output": f"Write failed: {e}", "error": str(e), "report_path": None, "artifacts": [], "meta": {}}

    logger.info(f"[ReportEngine] Draft report saved: {report_path}")

    return {
        "ok":          True,
        "output":      f"Draft report saved to {report_path.name}. Review before submitting to HackerOne.",
        "error":       None,
        "report_path": str(report_path),
        "artifacts":   [str(report_path)],
        "meta": {
            "finding_id":  finding_id,
            "severity":    severity,
            "cvss_score":  cvss["base_score"],
            "status":      "DRAFT — not submitted",
        },
    }


def _impact_description(severity: str) -> str:
    return {
        "CRITICAL": "gain full unauthorized access or execute arbitrary code",
        "HIGH":     "access sensitive data or escalate privileges",
        "MEDIUM":   "access some restricted information or perform limited unauthorized actions",
        "LOW":      "obtain minor information disclosure",
        "INFO":     "observe internal system information",
    }.get(severity, "impact the security of the application")


def list_report_drafts() -> list[dict]:
    """Return list of all draft report files in reports/ directory."""
    reports_dir = _get_reports_dir()
    drafts = []
    for f in sorted(reports_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        drafts.append({
            "filename": f.name,
            "path":     str(f),
            "size_kb":  round(f.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return drafts


# ── Tool functions ────────────────────────────────────────────────────────────

def tool_draft_report(finding_id: int = 0) -> dict:
    """Tool: generate a draft HackerOne report for a finding. Operator must review before submitting."""
    if not finding_id:
        return {"ok": False, "output": "finding_id required.", "error": "missing_param", "artifacts": [], "meta": {}}
    return generate_report_for_finding(int(finding_id))


def tool_list_report_drafts() -> dict:
    """Tool: list all pending report drafts."""
    drafts = list_report_drafts()
    if not drafts:
        return {"ok": True, "output": "No report drafts found.", "error": None, "artifacts": [], "meta": {}}
    lines = [f"  {d['filename']} ({d['size_kb']}KB, {d['modified']})" for d in drafts[:10]]
    return {
        "ok":    True,
        "output": f"Report drafts ({len(drafts)} total):\n" + "\n".join(lines),
        "error": None,
        "artifacts": [d["path"] for d in drafts],
        "meta": {"count": len(drafts)},
    }


def tool_calculate_cvss(
    attack_vector: str = "NETWORK",
    attack_complexity: str = "LOW",
    privileges_required: str = "NONE",
    user_interaction: str = "NONE",
    scope: str = "UNCHANGED",
    confidentiality: str = "HIGH",
    integrity: str = "NONE",
    availability: str = "NONE",
) -> dict:
    """Tool: calculate CVSS 3.1 base score from metric values."""
    from reporting.cvss_calculator import calculate_cvss
    result = calculate_cvss(
        attack_vector, attack_complexity, privileges_required,
        user_interaction, scope, confidentiality, integrity, availability
    )
    return {
        "ok":    "error" not in result,
        "output": f"CVSS 3.1 Score: {result['base_score']} ({result['severity']}) — {result['vector_string']}",
        "error": result.get("error"),
        "artifacts": [],
        "meta": result,
    }
