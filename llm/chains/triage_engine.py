"""
llm/chains/triage_engine.py — Score many findings, surface the top ones.

Uses fast local model for rationale. Read-only from DB. No network calls.
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from security.sanitizer import wrap_untrusted
except ImportError:
    def wrap_untrusted(text: str, source: str = "external") -> str:
        return f"[{source}]\n{text[:4000]}"


_SEVERITY_BASE = {"critical": 9.0, "high": 7.0, "medium": 5.0, "low": 3.0, "info": 1.0}


class TriageEngine:
    """Score a list of findings and return the top N worth pursuing."""

    def score_finding(self, finding: dict) -> float:
        """Rule-based score. LLM is additive, not blocking."""
        base = _SEVERITY_BASE.get(finding.get("severity", "info").lower(), 1.0)
        score = base
        # Bonus for unverified (more potential value)
        if finding.get("status") == "unverified":
            score += 0.5
        # Penalty for already submitted
        if finding.get("status") in ("submitted", "closed", "duplicate"):
            score -= 5.0
        # Bonus for high bounty potential
        if finding.get("bounty_potential") in ("high", "critical"):
            score += 1.0
        # Priority score from DB if available
        priority = float(finding.get("priority_score", 0.0) or 0.0)
        score += priority * 0.5
        return max(0.0, score)

    def triage(self, findings: list[dict], top_n: int = 3) -> dict:
        """
        Score all findings and return top_n with rationale.
        findings: list of finding dicts from findings_canonical.
        """
        if not findings:
            return {"ok": True, "top_findings": [], "total": 0, "rationale": "No findings to triage."}

        scored = [(f, self.score_finding(f)) for f in findings]
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_n]

        # Get LLM rationale for the top finding
        rationale = ""
        if top:
            best = top[0][0]
            safe_finding = wrap_untrusted(str(best)[:1000], "finding")
            try:
                import config as _c
                fast_model = getattr(_c, 'OLLAMA_JUDGE_MODEL', 'phi4-mini')
                from llm.client import LLM
                client = LLM(model=fast_model)
                resp = client.complete(
                    [{"role": "user", "content": (
                        f"This is the highest-priority finding:\n{safe_finding}\n\n"
                        "In one sentence, explain why this should be investigated first."
                    )}],
                    system="You are a security triage analyst. Be concise.",
                )
                rationale = resp.get("content", "") or ""
            except Exception:
                pass

        return {
            "ok": True,
            "top_findings": [
                {**f, "_triage_score": round(s, 2)}
                for f, s in top
            ],
            "total":     len(findings),
            "rationale": rationale or (
                f"Top finding: {top[0][0].get('title', 'unknown')} (score {top[0][1]:.1f})" if top else ""
            ),
        }

    def triage_from_db(self, program_id: int = None, top_n: int = 3) -> dict:
        """Load unverified findings from DB and triage them."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                query = "SELECT * FROM findings_canonical WHERE status='unverified'"
                params = []
                if program_id:
                    query += " AND program_id=?"
                    params.append(program_id)
                query += " ORDER BY created_at DESC LIMIT 100"
                rows = conn.execute(query, params).fetchall()
            findings = [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"[TriageEngine] DB read failed: {e}")
            findings = []
        return self.triage(findings, top_n=top_n)


def tool_triage_findings(program_id: int = 0, top_n: int = 3) -> dict:
    """Tool: score all unverified findings and return top N worth chasing."""
    engine = TriageEngine()
    result = engine.triage_from_db(
        program_id=int(program_id) if program_id else None,
        top_n=int(top_n),
    )
    if not result["top_findings"]:
        return {"ok": True, "output": "No unverified findings to triage.", "error": None, "artifacts": [], "meta": result}
    lines = []
    for i, f in enumerate(result["top_findings"], 1):
        lines.append(f"  {i}. [{f.get('severity','?').upper()}] {f.get('title','unknown')} (score: {f.get('_triage_score',0)})")
    return {
        "ok":        True,
        "output":    f"Top {len(result['top_findings'])} of {result['total']} findings:\n" + "\n".join(lines) + (f"\n\n{result['rationale']}" if result["rationale"] else ""),
        "error":     None,
        "artifacts": [],
        "meta":      result,
    }
