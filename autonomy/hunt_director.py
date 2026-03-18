"""
autonomy/hunt_director.py — Continuously evaluate highest-value next recon action.

Surfaces proposals for operator approval. NEVER auto-executes.

SECURITY — CRITICAL:
  - All proposals are SUGGESTIONS ONLY
  - No tool call fires without operator approval
  - HUNT_AUTO_APPROVE_THRESHOLD default is 0.0 (disabled)
  - Scope validated for every proposed target before proposal created
  - Rate limit: max 1 proposal per HUNT_PROPOSAL_INTERVAL_SECS (default 300s)
  - Max HUNT_MAX_PROPOSALS_PER_DAY proposals per day
  - Proposals expire after 24 hours if not actioned

NEVER auto-approve if:
  - Target is not in active program scope
  - Target is a lab machine (NET.is_lab_machine())
  - Action involves exploit payloads
  - Action would modify target state
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class HuntDirector:
    """Background service: propose the highest-value next recon action."""

    def __init__(self, notify_callback=None):
        self._notify    = notify_callback
        self._thread    = None
        self._stop_evt  = threading.Event()
        self._last_proposal: datetime | None = None
        self._proposals_today = 0
        self._proposals_today_date: str = ""

    def start(self) -> None:
        """Start hunt director in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, name="HuntDirector", daemon=True
        )
        self._thread.start()
        logger.info("[HuntDirector] Started (auto-approve DISABLED by default)")

    def stop(self) -> None:
        self._stop_evt.set()

    def _loop(self) -> None:
        import config as _c
        interval = getattr(_c, 'HUNT_PROPOSAL_INTERVAL_SECS', 300)
        while not self._stop_evt.is_set():
            try:
                self._maybe_propose()
            except Exception as e:
                logger.warning(f"[HuntDirector] Loop error: {e}")
            self._stop_evt.wait(interval)

    def _maybe_propose(self) -> None:
        """Evaluate whether to create a new hunt proposal."""
        import config as _c

        # Kill switch check
        try:
            from runtime.kill_switch import get_kill_switch
            if get_kill_switch().is_set():
                return
        except Exception:
            pass

        # Rate limit: max 1 proposal per interval
        interval = getattr(_c, 'HUNT_PROPOSAL_INTERVAL_SECS', 300)
        if self._last_proposal:
            elapsed = (datetime.now() - self._last_proposal).total_seconds()
            if elapsed < interval:
                return

        # Daily cap
        today = datetime.now().strftime("%Y-%m-%d")
        if self._proposals_today_date != today:
            self._proposals_today = 0
            self._proposals_today_date = today
        max_daily = getattr(_c, 'HUNT_MAX_PROPOSALS_PER_DAY', 20)
        if self._proposals_today >= max_daily:
            logger.debug("[HuntDirector] Daily proposal cap reached")
            return

        # Score candidates and create best proposal
        proposal = self._score_and_select()
        if proposal:
            self._create_proposal(proposal)
            self._last_proposal = datetime.now()
            self._proposals_today += 1

    def _score_and_select(self) -> dict | None:
        """Score potential next actions and return the highest-value one."""
        candidates = self._build_candidates()
        if not candidates:
            return None
        # Score each candidate
        scored = [(c, self._score(c)) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        best, best_score = scored[0]

        import config as _c
        threshold = getattr(_c, 'HUNT_AUTO_APPROVE_THRESHOLD', 0.0)
        best["hunt_score"] = round(best_score, 3)
        best["auto_approvable"] = (threshold > 0.0 and best_score >= threshold)

        # Safety: NEVER auto-approve exploit or destructive actions
        if best.get("action_type") in ("exploit", "payload", "modify"):
            best["auto_approvable"] = False

        # Safety: NEVER auto-approve if target is a lab machine
        try:
            from config.network import NET
            if NET.is_lab_machine(best.get("target", "")):
                best["auto_approvable"] = False
        except Exception:
            best["auto_approvable"] = False  # fail safe

        return best

    def _build_candidates(self) -> list[dict]:
        """Build list of candidate next actions from DB state."""
        candidates = []
        try:
            from storage.db import get_db, get_active_program
            prog = get_active_program()
            if not prog:
                return []
            prog_id = prog.get("id")

            with get_db() as conn:
                # Stale targets (not scanned in 7+ days)
                stale = conn.execute(
                    "SELECT target, notes, created_at FROM scan_targets "
                    "WHERE project=? ORDER BY created_at ASC LIMIT 10",
                    (prog.get("name", ""),)
                ).fetchall()

                # Targets with no findings yet
                all_targets = conn.execute(
                    "SELECT DISTINCT target FROM scan_targets WHERE project=?",
                    (prog.get("name", ""),)
                ).fetchall()
                targets_with_findings = conn.execute(
                    "SELECT DISTINCT host FROM findings_canonical WHERE program_id=?",
                    (prog_id,)
                ).fetchall()

            found_hosts = {r["host"] for r in targets_with_findings}
            unexplored = [r["target"] for r in all_targets if r["target"] not in found_hosts]

            for target in unexplored[:5]:
                # Scope check — MANDATORY
                try:
                    from bridge.scope import is_in_scope
                    if not is_in_scope(target):
                        continue
                except Exception:
                    continue
                # Lab machine check — MANDATORY
                try:
                    from config.network import NET
                    if NET.is_lab_machine(target):
                        continue
                except Exception:
                    continue
                candidates.append({
                    "action_type":  "subfinder",
                    "target":       target,
                    "program_id":   prog_id,
                    "program_name": prog.get("name", ""),
                    "rationale":    f"No findings yet on {target} — unexplored surface.",
                    "staleness":    1.0,
                })

        except Exception as e:
            logger.debug(f"[HuntDirector] Candidate build failed: {e}")

        return candidates

    def _score(self, candidate: dict) -> float:
        """
        Score a candidate action using the hunt value formula.

        hunt_value = (
            target_staleness_score    * 0.30 +
            cve_density_score         * 0.25 +
            unexplored_surface_score  * 0.20 +
            historical_finding_rate   * 0.15 +
            operator_preference_score * 0.10
        )
        """
        staleness    = float(candidate.get("staleness",    0.5))
        cve_density  = float(candidate.get("cve_density",  0.0))
        unexplored   = float(candidate.get("unexplored",   0.5))
        finding_rate = float(candidate.get("finding_rate", 0.0))
        op_pref      = float(candidate.get("op_pref",      0.5))

        return (
            staleness    * 0.30 +
            cve_density  * 0.25 +
            unexplored   * 0.20 +
            finding_rate * 0.15 +
            op_pref      * 0.10
        )

    def _create_proposal(self, proposal: dict) -> None:
        """Write proposal to research_items as a pending_approval record."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                # Expire old unactioned proposals
                conn.execute(
                    "UPDATE research_items SET actioned=1 "
                    "WHERE source='hunt_director' AND actioned=0 "
                    "AND created_at < datetime('now', '-1 day')"
                )
                conn.execute(
                    "INSERT INTO research_items "
                    "(source, item_type, title, severity, url, affects_targets, actioned, raw_data, created_at) "
                    "VALUES (?,?,?,?,?,1,0,?,datetime('now'))",
                    (
                        "hunt_director",
                        "hunt_proposal",
                        f"Hunt proposal: {proposal['action_type']} on {proposal['target']}",
                        "info",
                        "",
                        json.dumps(proposal),
                    )
                )
            logger.info(f"[HuntDirector] Proposal created: {proposal['action_type']} on {proposal['target']} (score={proposal['hunt_score']})")
            if self._notify:
                try:
                    self._notify(f"Hunt director: new proposal — {proposal['action_type']} on {proposal['target']}")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[HuntDirector] Proposal create failed: {e}")

    def status(self) -> dict:
        import config as _c
        return {
            "running":               self._thread is not None and self._thread.is_alive(),
            "last_proposal":         self._last_proposal.isoformat() if self._last_proposal else None,
            "proposals_today":       self._proposals_today,
            "auto_approve_enabled":  getattr(_c, 'HUNT_AUTO_APPROVE_THRESHOLD', 0.0) > 0.0,
            "auto_approve_threshold": getattr(_c, 'HUNT_AUTO_APPROVE_THRESHOLD', 0.0),
        }


# ── Tool functions ────────────────────────────────────────────────────────────

def tool_hunt_director_status() -> dict:
    """Tool: show hunt director state and last proposal."""
    try:
        from storage.db import get_db
        import config as _c
        with get_db() as conn:
            pending = conn.execute(
                "SELECT title, raw_data, created_at FROM research_items "
                "WHERE source='hunt_director' AND actioned=0 "
                "ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
        enabled = getattr(_c, 'HUNT_DIRECTOR_ENABLED', False)
        threshold = getattr(_c, 'HUNT_AUTO_APPROVE_THRESHOLD', 0.0)
        lines = [f"Hunt Director: {'ENABLED' if enabled else 'DISABLED'}"]
        lines.append(f"Auto-approve threshold: {threshold} ({'DISABLED' if threshold == 0.0 else 'ACTIVE'})")
        lines.append(f"Pending proposals: {len(pending)}")
        for p in pending:
            raw = json.loads(p["raw_data"] or "{}")
            lines.append(f"  • {p['title']} (score={raw.get('hunt_score', '?')})")
        return {"ok": True, "output": "\n".join(lines), "error": None, "artifacts": [], "meta": {"pending": len(pending)}}
    except Exception as e:
        return {"ok": False, "output": f"Error: {e}", "error": str(e), "artifacts": [], "meta": {}}


def tool_hunt_director_enable() -> dict:
    """Tool: enable the hunt director loop."""
    try:
        import config as _c
        _c.HUNT_DIRECTOR_ENABLED = True
        return {"ok": True, "output": "Hunt director enabled. It will propose next actions every 5 minutes. Auto-approve remains DISABLED unless you explicitly raise the threshold.", "error": None, "artifacts": [], "meta": {}}
    except Exception as e:
        return {"ok": False, "output": f"Error: {e}", "error": str(e), "artifacts": [], "meta": {}}


def tool_hunt_director_disable() -> dict:
    """Tool: disable the hunt director loop."""
    try:
        import config as _c
        _c.HUNT_DIRECTOR_ENABLED = False
        return {"ok": True, "output": "Hunt director disabled.", "error": None, "artifacts": [], "meta": {}}
    except Exception as e:
        return {"ok": False, "output": f"Error: {e}", "error": str(e), "artifacts": [], "meta": {}}
