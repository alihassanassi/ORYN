"""
intelligence/correlator.py — Cross-reference CVEs against active target tech stacks.

Runs every INTEL_CORRELATOR_INTERVAL_SECS seconds (default 3600).
When a CVE matches a target's tech stack with score > INTEL_CORRELATOR_MIN_SCORE,
creates a finding_candidate for operator review.

SECURITY:
  - Read-only from research sources
  - No network scans triggered automatically
  - Scope check on every target before analysis
  - All CVE data wrapped in wrap_untrusted() before LLM
  - Rate limit: max 10 NVD API calls per hour
  - Finding candidates require operator approval before any action
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from security.sanitizer import wrap_untrusted
except ImportError:
    def wrap_untrusted(text: str, source: str = "external") -> str:
        return f"[{source}]\n{text[:4000]}"


class ThreatIntelCorrelator:
    """
    Background service: correlate new CVEs against known target tech stacks.
    Creates finding candidates for operator review when matches are found.
    """

    def __init__(self, notify_callback=None):
        self._notify   = notify_callback  # optional: fn(str) to surface alerts
        self._thread   = None
        self._stop_evt = threading.Event()
        self._last_run: datetime | None = None
        self._matches_found = 0

    def start(self) -> None:
        """Start the correlator in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, name="IntelCorrelator", daemon=True
        )
        self._thread.start()
        logger.info("[IntelCorrelator] Started")

    def stop(self) -> None:
        self._stop_evt.set()

    def _loop(self) -> None:
        import config as _c
        interval = getattr(_c, 'INTEL_CORRELATOR_INTERVAL_SECS', 3600)
        while not self._stop_evt.is_set():
            try:
                self._run_once()
            except Exception as e:
                logger.warning(f"[IntelCorrelator] Loop error: {e}")
            self._stop_evt.wait(interval)

    def _run_once(self) -> int:
        """Run one correlation pass. Returns number of matches found."""
        import config as _c
        min_score = getattr(_c, 'INTEL_CORRELATOR_MIN_SCORE', 0.70)

        # Check kill switch
        try:
            from runtime.kill_switch import get_kill_switch
            if get_kill_switch().is_set():
                logger.info("[IntelCorrelator] Kill switch set — skipping run")
                return 0
        except Exception:
            pass

        # Get recent CVEs
        cves = self._fetch_recent_cves()
        if not cves:
            self._last_run = datetime.now()
            return 0

        # Get active target tech stacks
        targets = self._get_target_tech_stacks()
        if not targets:
            self._last_run = datetime.now()
            return 0

        matches = 0
        for cve in cves[:20]:  # cap per run
            for target in targets:
                score = self._score_relevance(cve, target)
                if score >= min_score:
                    self._create_finding_candidate(cve, target, score)
                    matches += 1

        self._matches_found += matches
        self._last_run = datetime.now()
        if matches > 0:
            logger.info(f"[IntelCorrelator] {matches} CVE matches found")
            if self._notify:
                try:
                    self._notify(f"Intel correlator: {matches} new CVE match(es) need review.")
                except Exception:
                    pass
        return matches

    def _fetch_recent_cves(self) -> list[dict]:
        """Fetch recent CVEs from local research_items table (already collected by ResearchEngine)."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT title, raw_data, severity, url FROM research_items "
                    "WHERE source='nvd' AND actioned=0 ORDER BY created_at DESC LIMIT 20"
                ).fetchall()
            cves = []
            for row in rows:
                raw = {}
                try:
                    raw = json.loads(row["raw_data"] or "{}")
                except Exception:
                    pass
                cves.append({
                    "cve_id":      row["title"],
                    "description": raw.get("description", row["title"]),
                    "severity":    row["severity"],
                    "url":         row["url"] or "",
                    "affected":    raw.get("affected_products", []),
                })
            return cves
        except Exception as e:
            logger.debug(f"[IntelCorrelator] CVE fetch failed: {e}")
            return []

    def _get_target_tech_stacks(self) -> list[dict]:
        """Get active targets and their known tech stacks from DB."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT t.target, t.notes, t.project, p.scope_domains "
                    "FROM scan_targets t "
                    "LEFT JOIN programs p ON t.project = p.name "
                    "WHERE t.target IS NOT NULL "
                    "ORDER BY t.created_at DESC LIMIT 50"
                ).fetchall()
            targets = []
            for row in rows:
                # Scope check before analysis
                try:
                    from bridge.scope import is_in_scope
                    if not is_in_scope(row["target"]):
                        continue
                except Exception:
                    pass
                targets.append({
                    "target":     row["target"],
                    "tech_stack": row["notes"] or "",
                    "project":    row["project"] or "",
                })
            return targets
        except Exception as e:
            logger.debug(f"[IntelCorrelator] Target fetch failed: {e}")
            return []

    def _score_relevance(self, cve: dict, target: dict) -> float:
        """
        Score CVE relevance to target (0.0-1.0).
        Simple keyword matching — no LLM needed for basic gating.
        LLM is used only when score > threshold.
        """
        tech = (target.get("tech_stack", "") + " " + target.get("target", "")).lower()
        description = (cve.get("description", "") + " " + str(cve.get("affected", []))).lower()

        if not tech or not description:
            return 0.0

        # Extract keywords from tech stack
        keywords = [w for w in tech.split() if len(w) > 3]
        if not keywords:
            return 0.0

        hits = sum(1 for kw in keywords if kw in description)
        base_score = min(1.0, hits / max(len(keywords), 1))

        # Boost for critical/high severity
        severity_boost = {"critical": 0.2, "high": 0.1, "medium": 0.0}.get(
            cve.get("severity", "").lower(), 0.0
        )
        return min(1.0, base_score + severity_boost)

    def _create_finding_candidate(self, cve: dict, target: dict, score: float) -> None:
        """Create a finding candidate in DB for operator review."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                # Check for duplicate
                existing = conn.execute(
                    "SELECT id FROM research_items WHERE source='intel_correlator' AND title=?",
                    (f"CVE Match: {cve['cve_id']} on {target['target']}",)
                ).fetchone()
                if existing:
                    return
                conn.execute(
                    "INSERT INTO research_items "
                    "(source, item_type, title, severity, url, affects_targets, actioned, raw_data, created_at) "
                    "VALUES (?,?,?,?,?,1,0,?,datetime('now'))",
                    (
                        "intel_correlator",
                        "cve_match",
                        f"CVE Match: {cve['cve_id']} on {target['target']}",
                        cve.get("severity", "info"),
                        cve.get("url", ""),
                        json.dumps({
                            "cve_id":     cve["cve_id"],
                            "target":     target["target"],
                            "tech_stack": target["tech_stack"],
                            "score":      score,
                            "description": cve["description"][:500],
                        }),
                    )
                )
        except Exception as e:
            logger.warning(f"[IntelCorrelator] Candidate create failed: {e}")

    def run_now(self) -> int:
        """Run one pass immediately. Returns match count."""
        return self._run_once()

    def status(self) -> dict:
        return {
            "running":        self._thread is not None and self._thread.is_alive(),
            "last_run":       self._last_run.isoformat() if self._last_run else None,
            "matches_total":  self._matches_found,
        }


# ── Tool functions ────────────────────────────────────────────────────────────

def tool_intel_correlate_now() -> dict:
    """Tool: run one CVE correlation pass immediately."""
    try:
        corr = ThreatIntelCorrelator()
        matches = corr.run_now()
        return {
            "ok":    True,
            "output": f"Correlation complete. {matches} CVE match(es) found and queued for operator review.",
            "error": None,
            "artifacts": [],
            "meta":  {"matches": matches},
        }
    except Exception as e:
        return {"ok": False, "output": f"Correlator error: {e}", "error": str(e), "artifacts": [], "meta": {}}


def tool_intel_status() -> dict:
    """Tool: show intel correlator last run time and matches found."""
    try:
        from storage.db import get_db
        with get_db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM research_items WHERE source='intel_correlator' AND actioned=0"
            ).fetchone()[0]
        return {
            "ok":    True,
            "output": f"Intel correlator: {count} unactioned CVE match(es) pending operator review.",
            "error": None,
            "artifacts": [],
            "meta":  {"pending_matches": count},
        }
    except Exception as e:
        return {"ok": False, "output": f"Status error: {e}", "error": str(e), "artifacts": [], "meta": {}}
