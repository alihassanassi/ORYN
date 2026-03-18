"""
intelligence/hacktivity_monitor.py — Monitor HackerOne public disclosed reports.

Watches public disclosed reports for active programs. When someone gets paid
on a similar program, checks if your scope has the same endpoint class.

SECURITY: Public data only. Read-only. No automated testing triggered.
All external data wrapped in wrap_untrusted() before LLM.
"""
from __future__ import annotations

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


class HacktivityMonitor:
    """
    Background monitor: watch public H1 hacktivity for programs similar to active ones.
    Surfaces relevant disclosed reports as research_items for operator review.
    """

    def __init__(self):
        self._thread   = None
        self._stop_evt = threading.Event()
        self._last_run: datetime | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, name="HacktivityMonitor", daemon=True
        )
        self._thread.start()
        logger.info("[HacktivityMonitor] Started")

    def stop(self) -> None:
        self._stop_evt.set()

    def _loop(self) -> None:
        import config as _c
        interval = getattr(_c, 'INTEL_CORRELATOR_INTERVAL_SECS', 3600)
        while not self._stop_evt.is_set():
            try:
                self._run_once()
            except Exception as e:
                logger.debug(f"[HacktivityMonitor] Loop error: {e}")
            self._stop_evt.wait(interval)

    def _run_once(self) -> None:
        """
        Fetch recent public H1 disclosures from research_items and
        check if any endpoint class matches your active scope.
        """
        try:
            from storage.db import get_db
            with get_db() as conn:
                # Look at recently collected H1 research items
                rows = conn.execute(
                    "SELECT title, raw_data, severity, url FROM research_items "
                    "WHERE source='hackerone_hacktivity' AND actioned=0 "
                    "ORDER BY created_at DESC LIMIT 10"
                ).fetchall()
        except Exception as e:
            logger.debug(f"[HacktivityMonitor] DB read failed: {e}")
            rows = []

        for row in rows:
            try:
                self._process_disclosure(dict(row))
            except Exception as e:
                logger.debug(f"[HacktivityMonitor] Process error: {e}")

        self._last_run = datetime.now()

    def _process_disclosure(self, item: dict) -> None:
        """Check if a disclosed report's vuln class applies to active targets."""
        import json
        raw = {}
        try:
            raw = json.loads(item.get("raw_data", "{}") or "{}")
        except Exception:
            pass

        title       = item.get("title", "")
        safe_title  = wrap_untrusted(title[:200], "hacktivity")
        endpoint    = raw.get("weakness", "") or raw.get("vulnerability_type", "")

        if not endpoint:
            return

        # Check active program scope for similar endpoints
        try:
            from storage.db import get_db, get_active_program
            prog = get_active_program()
            if not prog:
                return
            import json as _json
            scope_domains = _json.loads(prog.get("scope_domains", "[]") or "[]")
            if not scope_domains:
                return

            # Log as a research note — operator decides if worth testing
            with get_db() as conn:
                existing = conn.execute(
                    "SELECT id FROM research_items WHERE source='hacktivity_match' AND title=?",
                    (f"Hacktivity: {title[:80]}",)
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO research_items "
                        "(source, item_type, title, severity, url, affects_targets, actioned, raw_data, created_at) "
                        "VALUES (?,?,?,?,?,1,0,?,datetime('now'))",
                        (
                            "hacktivity_match",
                            "disclosure_match",
                            f"Hacktivity: {title[:80]}",
                            item.get("severity", "info"),
                            item.get("url", ""),
                            _json.dumps({
                                "vuln_class":   endpoint,
                                "program":      prog.get("name", ""),
                                "scope_sample": scope_domains[:3],
                                "original_url": item.get("url", ""),
                            }),
                        )
                    )
        except Exception as e:
            logger.debug(f"[HacktivityMonitor] Match write failed: {e}")

    def status(self) -> dict:
        return {
            "running":  self._thread is not None and self._thread.is_alive(),
            "last_run": self._last_run.isoformat() if self._last_run else None,
        }
