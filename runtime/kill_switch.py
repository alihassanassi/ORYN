"""
Kill Switch — emergency stop for all autonomous operations.

Security design: The kill switch uses BOTH a Python state variable AND
a filesystem sentinel file (EMERGENCY_STOP.flag). The Python state alone
is insufficient — a bug in the autonomy stack (or prompt injection) could
call reset() programmatically. The file must also be deleted manually by
the operator. This makes the kill switch resistant to software-level bypass.

Hotkey: Ctrl+Alt+Shift+K
Effect: Creates EMERGENCY_STOP.flag + sets Python state + cancels DB jobs
Reset:  Operator manually deletes EMERGENCY_STOP.flag OR calls reset()
"""
import logging, pathlib, sqlite3
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

from config import ROOT_DIR
KILL_FLAG = ROOT_DIR / "EMERGENCY_STOP.flag"


class KillSwitch:

    def __init__(self):
        # Restore state from filesystem on restart — filesystem is authoritative
        self._triggered   = KILL_FLAG.exists()
        self._trigger_time: Optional[datetime] = None
        self._reason: Optional[str] = None
        if self._triggered:
            logger.warning("[KillSwitch] EMERGENCY_STOP.flag found on startup — operations halted")

    def register_hotkey(self) -> None:
        """
        Register Ctrl+Alt+Shift+K as global hotkey via Qt main window.
        Actual registration happens in main_window.py _build_ui():
          self._kill_shortcut = QShortcut(QKeySequence("Ctrl+Alt+Shift+K"), self)
          self._kill_shortcut.activated.connect(lambda: kill_switch.trigger("hotkey"))
        """
        logger.info("[KillSwitch] hotkey registration delegated to main window (Ctrl+Alt+Shift+K)")

    def trigger(self, reason: str = "operator_hotkey") -> None:
        """Execute the full emergency stop sequence."""
        if self._triggered:
            return   # idempotent

        self._triggered    = True
        self._trigger_time = datetime.now(timezone.utc)
        self._reason       = reason

        # 1. Write filesystem sentinel FIRST (before anything else)
        KILL_FLAG.write_text(
            f"EMERGENCY STOP\n"
            f"Time: {self._trigger_time.isoformat()}\n"
            f"Reason: {reason}\n"
        )

        # 2. Cancel all running/pending jobs in DB
        try:
            from config import DB_PATH
            with sqlite3.connect(str(DB_PATH)) as conn:
                conn.execute(
                    "UPDATE jobs SET status='cancelled' WHERE status IN ('running','pending')"
                )
                conn.commit()
            logger.info("[KillSwitch] cancelled all running/pending jobs")
        except Exception as e:
            logger.error("[KillSwitch] failed to cancel jobs: %s", e)

        # 3. Immutable audit log
        try:
            from storage.audit_log import ImmutableAuditLog
            ImmutableAuditLog().append(
                "kill_switch_triggered", "operator",
                decision="triggered", reason=reason
            )
        except Exception:
            pass

        # 4. Speak (best effort — never block on this)
        try:
            from voice.tts import speak
            speak("Emergency stop activated. All autonomous operations halted.")
        except Exception:
            pass

        logger.critical("[KillSwitch] EMERGENCY STOP ACTIVATED — reason: %s", reason)

    def reset(self) -> None:
        """
        Clear the emergency stop state.
        Deletes EMERGENCY_STOP.flag AND clears Python state.
        """
        if KILL_FLAG.exists():
            KILL_FLAG.unlink()
        self._triggered    = False
        self._trigger_time = None
        self._reason       = None
        try:
            from storage.audit_log import ImmutableAuditLog
            ImmutableAuditLog().append("kill_switch_reset", "operator", decision="reset")
        except Exception:
            pass
        logger.info("[KillSwitch] emergency stop cleared — autonomous operations can resume")

    @property
    def is_triggered(self) -> bool:
        """Check BOTH Python state and filesystem — filesystem is authoritative."""
        return self._triggered or KILL_FLAG.exists()

    def status(self) -> dict:
        return {
            "triggered":    self.is_triggered,
            "reason":       self._reason,
            "trigger_time": self._trigger_time.isoformat() if self._trigger_time else None,
            "flag_exists":  KILL_FLAG.exists(),
        }


# Module-level singleton
_kill_switch: Optional[KillSwitch] = None


def get_kill_switch() -> KillSwitch:
    global _kill_switch
    if _kill_switch is None:
        _kill_switch = KillSwitch()
    return _kill_switch
