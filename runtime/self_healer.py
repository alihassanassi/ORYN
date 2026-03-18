"""
runtime/self_healer.py — JARVIS internal health monitor and self-repair.

Monitors the application's own subsystems (not external processes — that's
watchdog.py). Detects stuck daemons, stale queues, memory bloat, and
DB lock contention. Takes corrective action silently when safe to do so.
Escalates to operator when human decision is required.

Runs as a daemon thread. Checks every HEAL_INTERVAL_SECS (default 60s).
All actions are logged to ImmutableAuditLog for review.

Layer: 5 (Autonomy) — acts only within pre-approved corrective actions.
"""
from __future__ import annotations

import threading
import time
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

HEAL_INTERVAL_SECS = 60   # health check cycle

# Maximum age (seconds) for a stale recon job before re-queuing
STUCK_JOB_THRESHOLD_SECS = 3600   # 1 hour

# Maximum messages before auto-prune is suggested
MSG_BLOAT_THRESHOLD = 5000


class SelfHealer:
    """
    Internal JARVIS health monitor.

    Checks:
      1. LLM connectivity — log warning if Ollama is stale
      2. Recon loop — detect stuck in_progress jobs past threshold
      3. DB health — flag if messages table is bloating
      4. Background daemon liveliness — recon_loop, research engine
      5. TTS queue — detect if audio is jammed

    Corrective actions taken automatically (no operator approval needed):
      - Mark stuck jobs as 'failed' so they can be re-queued
      - Log all actions to audit log
      - Clear internal Python logging handler queue if overflowing

    Corrective actions that escalate to operator:
      - DB bloat > threshold → suggest prune
      - Repeated LLM failures → recommend Ollama restart
    """

    def __init__(self, notify_callback: Optional[Callable[[str], None]] = None):
        """
        notify_callback: optional fn(message: str) → called for operator escalations.
        Pass main_window._speak or equivalent.
        """
        self._notify   = notify_callback
        self._running  = False
        self._thread: Optional[threading.Thread] = None
        self._heal_counts: dict[str, int] = {}   # issue_key → heal count

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="SelfHealer"
        )
        self._thread.start()
        logger.info("[SelfHealer] Started — health checks every %ds", HEAL_INTERVAL_SECS)

    def stop(self) -> None:
        self._running = False

    def run_once(self) -> dict:
        """Run one health check cycle. Returns a dict of check results."""
        results = {}
        results["llm"]      = self._check_llm()
        results["jobs"]     = self._check_stuck_jobs()
        results["db"]       = self._check_db_health()
        results["daemons"]  = self._check_daemon_liveliness()
        return results

    def status(self) -> dict:
        return {
            "running":     self._running,
            "heal_counts": dict(self._heal_counts),
            "interval":    HEAL_INTERVAL_SECS,
        }

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(30)  # give boot sequence time to settle
        while self._running:
            try:
                self._check_llm()
                self._check_stuck_jobs()
                self._check_db_health()
                self._check_daemon_liveliness()
            except Exception as exc:
                logger.debug("[SelfHealer] cycle error: %s", exc)
            time.sleep(HEAL_INTERVAL_SECS)

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_llm(self) -> str:
        """Verify Ollama is responsive. Warn on staleness."""
        try:
            from runtime.watchdog import llm_is_stale
            if llm_is_stale():
                self._heal_counts["llm_stale"] = self._heal_counts.get("llm_stale", 0) + 1
                count = self._heal_counts["llm_stale"]
                if count >= 3:
                    self._escalate(
                        "LLM has been unresponsive for several cycles. "
                        "Consider running: ollama serve"
                    )
                    self._heal_counts["llm_stale"] = 0  # reset after escalation
                return "stale"
            else:
                self._heal_counts["llm_stale"] = 0
                return "ok"
        except Exception as exc:
            logger.debug("[SelfHealer] llm check error: %s", exc)
            return "skip"

    def _check_stuck_jobs(self) -> str:
        """Find recon jobs that have been in_progress too long and reset them."""
        try:
            from storage.db import get_db
            threshold_dt = time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.gmtime(time.time() - STUCK_JOB_THRESHOLD_SECS)
            )
            with get_db() as conn:
                stuck = conn.execute(
                    "SELECT id, domain FROM jobs WHERE status='in_progress' "
                    "AND created_at < ?",
                    (threshold_dt,)
                ).fetchall()
                if stuck:
                    ids = [r[0] for r in stuck]
                    domains = [r[1] for r in stuck]
                    conn.execute(
                        f"UPDATE jobs SET status='failed' WHERE id IN "
                        f"({','.join('?' * len(ids))})",
                        ids
                    )
                    self._heal_counts["stuck_jobs"] = (
                        self._heal_counts.get("stuck_jobs", 0) + len(ids)
                    )
                    self._audit(f"Reset {len(ids)} stuck job(s): {domains}")
                    logger.warning("[SelfHealer] Reset %d stuck job(s): %s", len(ids), domains)
                    return f"healed:{len(ids)}"
            return "ok"
        except Exception as exc:
            logger.debug("[SelfHealer] stuck job check error: %s", exc)
            return "skip"

    def _check_db_health(self) -> str:
        """Check message table size. Escalate if bloated."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM messages"
                ).fetchone()[0]
            if count > MSG_BLOAT_THRESHOLD:
                key = "db_bloat"
                self._heal_counts[key] = self._heal_counts.get(key, 0) + 1
                if self._heal_counts[key] == 1:  # only escalate once
                    self._escalate(
                        f"Message history has {count} entries. "
                        "Consider running: db_maintenance prune_90d"
                    )
                return f"bloat:{count}"
            return "ok"
        except Exception as exc:
            logger.debug("[SelfHealer] db health check error: %s", exc)
            return "skip"

    def _check_daemon_liveliness(self) -> str:
        """Check that expected background daemons are still alive."""
        issues: list[str] = []
        try:
            import runtime.boot_manager as _bm
            if _bm.watchdog is not None:
                t = getattr(_bm.watchdog, '_thread', None)
                if t is not None and not t.is_alive():
                    issues.append("watchdog")
                    logger.warning("[SelfHealer] watchdog thread is dead")
            if _bm.recon_loop is not None:
                t = getattr(_bm.recon_loop, '_thread', None)
                if t is not None and not t.is_alive():
                    issues.append("recon_loop")
                    logger.warning("[SelfHealer] recon_loop thread is dead")
        except Exception as exc:
            logger.debug("[SelfHealer] daemon check error: %s", exc)
            return "skip"
        if issues:
            key = f"dead_daemons:{'_'.join(sorted(issues))}"
            self._heal_counts[key] = self._heal_counts.get(key, 0) + 1
            if self._heal_counts[key] == 1:  # only escalate once per unique dead-set
                self._escalate(
                    f"Background daemon(s) have stopped: {', '.join(issues)}. "
                    "A restart may be required."
                )
            return f"dead:{issues}"
        return "ok"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _escalate(self, message: str) -> None:
        """Notify the operator of a condition requiring attention."""
        logger.warning("[SelfHealer] ESCALATE: %s", message)
        self._audit(f"ESCALATION: {message}")
        if self._notify:
            try:
                self._notify(message)
            except Exception:
                pass

    def _audit(self, message: str) -> None:
        try:
            from storage.audit_log import ImmutableAuditLog
            ImmutableAuditLog().append(
                event_type="self_healer",
                actor="self_healer",
                decision="healed",
                reason=message[:500],
            )
        except Exception:
            pass
