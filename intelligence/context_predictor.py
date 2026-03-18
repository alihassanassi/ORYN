"""
intelligence/context_predictor.py — Background daemon that pre-warms session context.

Learns the operator's typical session start time from history and pre-fetches
relevant context 5 minutes before the predicted start, so JARVIS is already
loaded and aware when the operator arrives.

Stored entirely in companion_preferences (persona='system').
ENABLED = False by default — operator must opt in via config or direct call.

Thread safety: threading.Lock for cache, threading.Event for stop signal.
Kill switch aware: sleeps 60s when EMERGENCY_STOP.flag is present.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Severity ranking used when sorting research items for the preload cache
_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high":     1,
    "medium":   2,
    "low":      3,
    "info":     4,
}


class ContextPredictor:
    """
    Pre-warms JARVIS session context by predicting when the operator will
    next start a session and pre-fetching relevant DB data ahead of time.

    Lifecycle:
        predictor = ContextPredictor()
        predictor.start()               # called by boot_manager
        predictor.record_session_start()  # called by main_window on startup
        ctx = predictor.get_preloaded_context()  # called by AgentWorker
        predictor.stop()               # called on shutdown
    """

    ENABLED: bool = False          # operator must opt in
    HISTORY_WINDOW: int = 14       # rolling window of session starts to average
    PRELOAD_LEAD_MINUTES: int = 5  # minutes before predicted start to preload
    CACHE_TTL_MINUTES: int = 30    # minutes before cached context is considered stale
    POLL_INTERVAL_SECS: int = 60   # how often the daemon loop checks the clock

    def __init__(self) -> None:
        self._stop_event   = threading.Event()
        self._cache_lock   = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background daemon thread. No-op if ENABLED is False."""
        if not self.ENABLED:
            logger.debug("[ContextPredictor] disabled — not starting daemon")
            return
        if self._thread and self._thread.is_alive():
            logger.debug("[ContextPredictor] daemon already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._preload_loop,
            name="context_predictor",
            daemon=True,
        )
        self._thread.start()
        logger.info("[ContextPredictor] daemon started")

    def stop(self) -> None:
        """Signal the daemon thread to stop on its next poll cycle."""
        self._stop_event.set()
        logger.info("[ContextPredictor] stop signal sent")

    def record_session_start(self) -> None:
        """
        Record the current time as a session start event.
        Called by main_window.py immediately after the GUI initialises.
        Appends to the rolling history stored in companion_preferences.
        """
        try:
            now_iso = datetime.now().isoformat()
            history = self._load_history()
            history.append(now_iso)
            # Keep only the most recent HISTORY_WINDOW entries
            history = history[-self.HISTORY_WINDOW:]
            self._save_history(history)
            logger.info("[ContextPredictor] session start recorded: %s", now_iso)
        except Exception:
            logger.exception("[ContextPredictor] failed to record session start")

    def get_preloaded_context(self) -> Optional[dict]:
        """
        Return the cached pre-loaded context if it is still fresh, else None.

        Freshness check: the 'ts' field in the cached JSON must be within the
        last CACHE_TTL_MINUTES minutes.
        """
        try:
            with self._cache_lock:
                row = self._read_preference("preloaded_context")
            if row is None:
                return None
            data = json.loads(row)
            ts = datetime.fromisoformat(data.get("ts", "1970-01-01"))
            age = datetime.now() - ts
            if age > timedelta(minutes=self.CACHE_TTL_MINUTES):
                logger.debug("[ContextPredictor] cached context is stale (age=%s)", age)
                return None
            return data
        except Exception:
            logger.debug("[ContextPredictor] get_preloaded_context error", exc_info=True)
            return None

    # ── Internal daemon ───────────────────────────────────────────────────────

    def _preload_loop(self) -> None:
        """
        Daemon thread body. Wakes every POLL_INTERVAL_SECS and decides whether
        a preload should be triggered based on the predicted session start time.
        """
        logger.debug("[ContextPredictor] preload loop entered")
        _preloaded_this_window = False   # avoid re-triggering within the same 5-min window

        while not self._stop_event.is_set():
            try:
                # ── Kill switch gate ──────────────────────────────────────────
                from runtime.kill_switch import KILL_FLAG
                if KILL_FLAG.exists():
                    logger.debug("[ContextPredictor] kill switch active — sleeping 60s")
                    self._stop_event.wait(60)
                    continue

                # ── Prediction check ──────────────────────────────────────────
                predicted = self._predict_next_start()
                if predicted is not None:
                    now = datetime.now()
                    delta = (predicted - now).total_seconds()
                    in_window = -60 <= delta <= self.PRELOAD_LEAD_MINUTES * 60

                    if in_window and not _preloaded_this_window:
                        logger.info(
                            "[ContextPredictor] within preload window (predicted=%s, delta=%.0fs) — preloading",
                            predicted.strftime("%H:%M"), delta,
                        )
                        self._do_preload()
                        _preloaded_this_window = True
                    elif not in_window:
                        # Reset flag once we've left the window so next cycle works
                        _preloaded_this_window = False

            except Exception:
                logger.exception("[ContextPredictor] unexpected error in preload loop")

            self._stop_event.wait(self.POLL_INTERVAL_SECS)

        logger.debug("[ContextPredictor] preload loop exiting")

    def _predict_next_start(self) -> Optional[datetime]:
        """
        Compute the predicted next session start time using a simple rolling
        mean of the hour-of-day from the last HISTORY_WINDOW sessions.

        Returns a datetime for today at the predicted hour:minute, or None if
        fewer than 2 historical data points exist.
        """
        try:
            history = self._load_history()
            if len(history) < 2:
                return None

            # Convert to hour-of-day floats (hour + minute/60)
            hour_floats: list[float] = []
            for iso in history[-self.HISTORY_WINDOW:]:
                try:
                    dt = datetime.fromisoformat(iso)
                    hour_floats.append(dt.hour + dt.minute / 60.0)
                except Exception:
                    continue

            if not hour_floats:
                return None

            mean_hour_float = sum(hour_floats) / len(hour_floats)
            mean_hour   = int(mean_hour_float)
            mean_minute = int((mean_hour_float - mean_hour) * 60)

            today = datetime.now().date()
            predicted = datetime(today.year, today.month, today.day,
                                 mean_hour, mean_minute, 0)

            # If today's predicted time has already passed, aim for tomorrow
            if predicted < datetime.now() - timedelta(minutes=self.PRELOAD_LEAD_MINUTES):
                predicted += timedelta(days=1)

            return predicted

        except Exception:
            logger.debug("[ContextPredictor] prediction error", exc_info=True)
            return None

    def _do_preload(self) -> None:
        """
        Fetch and cache the four context buckets:
          1. Last 10 messages from the active project
          2. Top 3 unactioned research items by severity
          3. Active program scope summary
          4. Pending hunt proposals

        Writes result to companion_preferences(persona='system', key='preloaded_context').
        All DB access is read-only except for the final preference write.
        """
        try:
            from storage.db import get_db

            messages: list[dict]       = []
            research_items: list[dict] = []
            program_scope: dict        = {}
            hunt_proposals: list[dict] = []

            with get_db() as conn:
                # 1. Last 10 messages from active project
                try:
                    proj_row = conn.execute(
                        "SELECT name FROM projects WHERE active=1 LIMIT 1"
                    ).fetchone()
                    active_project = proj_row["name"] if proj_row else "Home Lab"

                    msg_rows = conn.execute(
                        "SELECT role, content, ts FROM messages "
                        "WHERE project=? ORDER BY id DESC LIMIT 10",
                        (active_project,),
                    ).fetchall()
                    messages = [
                        {"role": r["role"], "content": r["content"][:500], "ts": r["ts"]}
                        for r in reversed(msg_rows)
                    ]
                except Exception:
                    logger.debug("[ContextPredictor] messages fetch error", exc_info=True)

                # 2. Top 3 unactioned research items by severity
                try:
                    ri_rows = conn.execute(
                        "SELECT id, source, item_type, title, severity, url "
                        "FROM research_items WHERE actioned=0 "
                        "ORDER BY created_at DESC LIMIT 50"
                    ).fetchall()
                    # Sort by severity rank, take top 3
                    sorted_ri = sorted(
                        ri_rows,
                        key=lambda r: _SEVERITY_RANK.get(
                            (r["severity"] or "info").lower(), 99
                        ),
                    )
                    research_items = [
                        {
                            "id":        r["id"],
                            "source":    r["source"],
                            "item_type": r["item_type"],
                            "title":     r["title"],
                            "severity":  r["severity"],
                            "url":       r["url"],
                        }
                        for r in sorted_ri[:3]
                    ]
                except Exception:
                    logger.debug("[ContextPredictor] research items fetch error", exc_info=True)

                # 3. Active program scope summary
                try:
                    prog_row = conn.execute(
                        "SELECT id, name, status, scope_domains, platform "
                        "FROM programs WHERE status='active' ORDER BY id LIMIT 1"
                    ).fetchone()
                    if prog_row:
                        try:
                            scope_domains = json.loads(prog_row["scope_domains"] or "[]")
                        except Exception:
                            scope_domains = []
                        program_scope = {
                            "id":       prog_row["id"],
                            "name":     prog_row["name"],
                            "platform": prog_row["platform"],
                            "domains":  scope_domains,
                        }
                except Exception:
                    logger.debug("[ContextPredictor] program scope fetch error", exc_info=True)

                # 4. Pending hunt proposals
                try:
                    hunt_rows = conn.execute(
                        "SELECT id, title, severity, url, created_at "
                        "FROM research_items "
                        "WHERE item_type='hunt_proposal' AND actioned=0 "
                        "ORDER BY created_at DESC LIMIT 10"
                    ).fetchall()
                    hunt_proposals = [
                        {
                            "id":         r["id"],
                            "title":      r["title"],
                            "severity":   r["severity"],
                            "url":        r["url"],
                            "created_at": r["created_at"],
                        }
                        for r in hunt_rows
                    ]
                except Exception:
                    logger.debug("[ContextPredictor] hunt proposals fetch error", exc_info=True)

            # Assemble and persist the cache
            cache_payload = {
                "ts":             datetime.now().isoformat(),
                "active_project": active_project,
                "messages":       messages,
                "research_items": research_items,
                "program_scope":  program_scope,
                "hunt_proposals": hunt_proposals,
            }
            cache_json = json.dumps(cache_payload)

            with self._cache_lock:
                self._write_preference("preloaded_context", cache_json)

            logger.info(
                "[ContextPredictor] preload complete — %d messages, %d research, "
                "%d hunt proposals, program=%s",
                len(messages),
                len(research_items),
                len(hunt_proposals),
                program_scope.get("name", "none"),
            )

        except Exception:
            logger.exception("[ContextPredictor] _do_preload failed")

    # ── Storage helpers ───────────────────────────────────────────────────────

    def _load_history(self) -> list[str]:
        """Return session start history as a list of ISO timestamp strings."""
        try:
            raw = self._read_preference("session_start_history")
            if raw is None:
                return []
            return json.loads(raw)
        except Exception:
            return []

    def _save_history(self, history: list[str]) -> None:
        """Persist session start history list."""
        self._write_preference("session_start_history", json.dumps(history))

    def _read_preference(self, key: str) -> Optional[str]:
        """
        Read a value from companion_preferences where persona='system'.
        Returns the raw string value, or None if not found.
        """
        try:
            from storage.db import get_db
            with get_db() as conn:
                row = conn.execute(
                    "SELECT value FROM companion_preferences "
                    "WHERE persona='system' AND key=?",
                    (key,),
                ).fetchone()
            return row["value"] if row else None
        except Exception:
            logger.debug("[ContextPredictor] read_preference(%r) error", key, exc_info=True)
            return None

    def _write_preference(self, key: str, value: str) -> None:
        """
        Upsert a value into companion_preferences where persona='system'.
        """
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO companion_preferences"
                    "(persona, key, value, updated_at) "
                    "VALUES('system', ?, ?, datetime('now'))",
                    (key, value),
                )
        except Exception:
            logger.debug("[ContextPredictor] write_preference(%r) error", key, exc_info=True)


# ── Module-level singleton ────────────────────────────────────────────────────

_instance: Optional[ContextPredictor] = None


def get_context_predictor() -> ContextPredictor:
    """Return the module-level ContextPredictor singleton, creating it if needed."""
    global _instance
    if _instance is None:
        _instance = ContextPredictor()
    return _instance
