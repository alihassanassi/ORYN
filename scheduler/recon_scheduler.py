"""
scheduler/recon_scheduler.py — Recon job enqueueing and pipeline dispatch.

Integrates with the autonomous recon loop. Jobs are persisted to DB
so they survive process restarts and can be resumed.
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def enqueue_recon_for_program(program_id: int, domain: str) -> int:
    """
    Creates a recon job in the DB for the given program/domain.
    Returns the job ID.

    Called by ReconLoop after all 7 security gates pass.
    This is the ONLY entry point for autonomous recon job creation.
    """
    from storage.db import get_db
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO jobs (program_id, domain, status, created_at) "
                "VALUES (?, ?, 'pending', datetime('now'))",
                (program_id, domain)
            )
            job_id = cur.lastrowid

            # Also record in actions table for budget tracking
            conn.execute(
                "INSERT INTO actions (source, program_id, tool, target, status, created_at) "
                "VALUES ('recon_loop', ?, 'subfinder', ?, 'enqueued', datetime('now'))",
                (program_id, domain)
            )

        logger.info("[Scheduler] enqueued job %d: program=%d domain=%s", job_id, program_id, domain)
        return job_id
    except Exception as e:
        logger.error("[Scheduler] enqueue failed: %s", e)
        return -1


def get_pending_jobs(limit: int = 5) -> list[dict]:
    """Returns pending jobs ordered by creation time."""
    from storage.db import get_db
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, program_id, domain, status, created_at FROM jobs "
                "WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
                (limit,)
            ).fetchall()
        keys = ("id", "program_id", "domain", "status", "created_at")
        return [dict(zip(keys, row)) for row in rows]
    except Exception:
        return []


def mark_job_running(job_id: int) -> None:
    from storage.db import get_db
    with get_db() as conn:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))


def mark_job_complete(job_id: int, status: str = "completed") -> None:
    from storage.db import get_db
    with get_db() as conn:
        conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
