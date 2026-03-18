"""
Autonomous Recon Loop — self-directed target selection and pipeline execution.

Security properties:
  - Every cycle passes through AutonomyPolicyEngine before ANY action
  - Every action logged to ImmutableAuditLog
  - All targets validated via SecuritySanitizer.validate_domain()
  - Quiet hours enforced from config (not memory — survives restarts)
  - Daily job cap enforced from persisted DB (not memory — survives restarts)
  - Kill switch checked via filesystem flag (not Python state)
  - Loop cannot approve its own actions — policy engine is independent
  - Wildcard scope programs require explicit operator confirmation
"""
import threading, time, logging, pathlib
from datetime import datetime, timezone
from typing import Optional
from runtime.kill_switch import KILL_FLAG

logger = logging.getLogger(__name__)


class ReconLoop:

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        self._cycles = 0
        self._last_cycle: Optional[datetime] = None
        self._policy = None
        self._audit  = None

    def _get_policy(self):
        if self._policy is None:
            from policy.autonomy_policy import AutonomyPolicyEngine
            self._policy = AutonomyPolicyEngine()
        return self._policy

    def _get_audit(self):
        if self._audit is None:
            from storage.audit_log import ImmutableAuditLog
            self._audit = ImmutableAuditLog()
        return self._audit

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ReconLoop")
        self._thread.start()
        self._get_audit().append("recon_loop_start", "recon_loop")
        logger.info("[ReconLoop] started")

    def stop(self) -> None:
        self._running = False
        self._get_audit().append("recon_loop_stop", "recon_loop")
        logger.info("[ReconLoop] stopped")

    def pause(self) -> None:
        self._paused = True
        self._get_audit().append("recon_loop_pause", "operator")
        logger.info("[ReconLoop] paused")

    def resume(self) -> None:
        self._paused = False
        self._get_audit().append("recon_loop_resume", "operator")
        logger.info("[ReconLoop] resumed")

    def status(self) -> dict:
        import config
        import datetime as dt
        interval = getattr(config, "RECON_LOOP_INTERVAL", 300)
        next_cycle = None
        if self._last_cycle:
            next_cycle = (self._last_cycle + dt.timedelta(seconds=interval)).isoformat()
        return {
            "running":            self._running,
            "paused":             self._paused,
            "cycles":             self._cycles,
            "last_cycle":         self._last_cycle.isoformat() if self._last_cycle else None,
            "next_cycle":         next_cycle,
            "active_jobs":        self._count_active_jobs(),
            "quiet_hours_active": self._is_quiet_hours(),
            "kill_switch_active": KILL_FLAG.exists(),
        }

    def _loop(self) -> None:
        import config
        while self._running:
            interval = getattr(config, "RECON_LOOP_INTERVAL", 300)
            if not self._paused:
                try:
                    self._cycle()
                except Exception as e:
                    logger.error("[ReconLoop] cycle error: %s", e)
                    self._get_audit().append("recon_loop_error", "recon_loop",
                                             reason=str(e)[:200])
            time.sleep(interval)

    def _cycle(self) -> None:
        """One cycle. Every decision gate documented."""
        self._cycles += 1
        self._last_cycle = datetime.now(timezone.utc)

        # GATE 1: Filesystem kill switch (out-of-process, cannot be bypassed)
        if KILL_FLAG.exists():
            logger.info("[ReconLoop] kill switch active — skipping cycle")
            return

        # GATE 2: Quiet hours
        if self._is_quiet_hours():
            logger.debug("[ReconLoop] quiet hours — skipping cycle")
            return

        # GATE 3: Concurrent job limit
        import config
        max_concurrent = getattr(config, "RECON_MAX_CONCURRENT", 2)
        if self._count_active_jobs() >= max_concurrent:
            logger.debug("[ReconLoop] at job limit — skipping cycle")
            return

        # GATE 4: Daily budget (persisted in DB)
        if not self._get_policy()._daily_budget_available():
            logger.info("[ReconLoop] daily budget exhausted — skipping cycle")
            return

        # SELECT TARGET
        target_info = self._select_target()
        if not target_info:
            logger.debug("[ReconLoop] no eligible targets — skipping cycle")
            return

        program_id = target_info["program_id"]
        domain     = target_info["domain"]

        # GATE 5: Input validation
        try:
            from security.sanitizer import validate_domain
            domain = validate_domain(domain)
        except ValueError as e:
            logger.warning("[ReconLoop] invalid target from DB: %s — %s", domain, e)
            return

        # GATE 6: Wildcard scope confirmation
        if self._is_wildcard_scope(program_id):
            if not self._wildcard_confirmed(program_id):
                logger.info("[ReconLoop] wildcard scope not confirmed for program %d", program_id)
                return

        # GATE 7: Autonomy policy — the hard gate
        decision = self._get_policy().evaluate(
            "subfinder",
            {"target": domain},
            program_id,
            source="recon_loop",
        )
        if not decision:
            logger.warning("[ReconLoop] policy denied: %s", decision.reason)
            return

        # ENQUEUE — only reaches here if all 7 gates pass
        self._enqueue_pipeline(program_id, domain)

    def _select_target(self) -> Optional[dict]:
        """
        Priority scoring:
          score = staleness_factor * 0.5
                + historical_finding_rate * 0.3
                + program_priority * 0.2
        """
        import config
        from storage.db import get_db
        staleness = getattr(config, "RECON_STALENESS_HOURS", 24)
        try:
            with get_db() as conn:
                rows = conn.execute("""
                    SELECT p.id, p.name, p.scope_domains,
                           MAX(a.created_at) as last_scan,
                           COUNT(f.id) as finding_count
                    FROM programs p
                    LEFT JOIN actions a ON a.program_id = p.id AND a.source='recon_loop'
                    LEFT JOIN findings_canonical f ON f.program_id = p.id
                    WHERE p.status = 'active'
                    GROUP BY p.id
                    HAVING last_scan IS NULL
                       OR last_scan < datetime('now', ?)
                    ORDER BY last_scan ASC
                    LIMIT 10
                """, (f"-{staleness} hours",)).fetchall()

                if not rows:
                    return None

                best = None
                best_score = -1.0
                for row in rows:
                    import json as _json
                    domains = _json.loads(row[2] or "[]")
                    if not domains:
                        continue
                    staleness_h = 999.0
                    if row[3]:
                        last = datetime.fromisoformat(row[3].replace("Z", ""))
                        now  = datetime.now(timezone.utc).replace(tzinfo=None)
                        staleness_h = (now - last).total_seconds() / 3600
                    score = (min(staleness_h / staleness, 2.0)) * 0.5 \
                          + (min((row[4] or 0) / 10.0, 1.0))  * 0.3 \
                          + 0.2
                    if score > best_score:
                        best_score = score
                        best = {"program_id": row[0], "domain": domains[0]}
                return best
        except Exception as e:
            logger.error("[ReconLoop] target selection error: %s", e)
            return None

    def _is_quiet_hours(self) -> bool:
        import config
        quiet = getattr(config, "RECON_QUIET_HOURS", [(22, 8)])
        h = datetime.now().hour
        for (start, end) in quiet:
            if start > end:  # wraps midnight
                if h >= start or h < end:
                    return True
            else:
                if start <= h < end:
                    return True
        return False

    def _is_wildcard_scope(self, program_id: int) -> bool:
        from storage.db import get_db
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT scope_domains FROM programs WHERE id=?", (program_id,)
                ).fetchone()
                if row:
                    import json as _json
                    domains = _json.loads(row[0] or "[]")
                    return any(d.startswith("*.") for d in domains)
        except Exception:
            pass
        return False

    def _wildcard_confirmed(self, program_id: int) -> bool:
        """
        Wildcard scope programs require an explicit operator flag in the DB
        before autonomous scanning.
        """
        from storage.db import get_db
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT wildcard_auto_approved FROM programs WHERE id=?",
                    (program_id,)
                ).fetchone()
                return bool(row and row[0])
        except Exception:
            return False  # fail closed

    def _count_active_jobs(self) -> int:
        from storage.db import get_db
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status='running'"
                ).fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def _enqueue_pipeline(self, program_id: int, domain: str) -> None:
        from scheduler.recon_scheduler import enqueue_recon_for_program
        enqueue_recon_for_program(program_id, domain=domain)
        self._get_audit().append(
            "recon_loop_enqueue", "recon_loop",
            target=domain, program_id=program_id, decision="enqueued"
        )
        logger.info("[ReconLoop] enqueued: %s (program %d)", domain, program_id)
