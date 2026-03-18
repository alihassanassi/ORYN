"""
policy/engine.py — Per-action policy gate.

Existing policy gate — extend, never replace.
This stub provides the PolicyEngine interface for the autonomy stack.
The full cloud-synced version may contain additional policy rules.
"""
import logging

logger = logging.getLogger(__name__)


class PolicyEngine:
    """
    Per-action policy gate. Evaluates whether a given action is permitted.
    Separate from AutonomyPolicyEngine — this governs interactive/operator actions.
    AutonomyPolicyEngine governs autonomous actions.
    """

    # S-04 fix: last-resort blocklist for destructive commands that should never
    # be issued even interactively by the operator. Kept minimal — operator is
    # trusted; this is a safety net only. Autonomous actions are governed by
    # AutonomyPolicyEngine (policy/autonomy_policy.py), not this class.
    _BLOCKED_INTERACTIVE: frozenset[str] = frozenset({
        "format",
        "dd if=",
        "mkfs",
        "rm -rf",
        "del /f /s",
        "remove-item -recurse -force",
    })

    def check(self, action: str, args: dict, operator_id: str = "operator") -> bool:
        """
        Returns True if the action is permitted.
        Logs all decisions.
        """
        action_lower = action.lower()
        for blocked in self._BLOCKED_INTERACTIVE:
            if blocked in action_lower:
                reason = f"matches interactive blocklist term '{blocked}'"
                self.log_denied(action, args, reason)
                return False

        # Default: permit operator actions unless explicitly blocked
        logger.debug("[PolicyEngine] check action=%s args=%s", action, list(args.keys()))
        return True

    def log_denied(self, action: str, args: dict, reason: str) -> None:
        """Records a policy denial. Also writes to DB if available."""
        logger.warning("[PolicyEngine] DENIED action=%s reason=%s", action, reason)
        try:
            from storage.db import log_denied_action
            log_denied_action(action, str(args)[:500], reason)
        except Exception:
            pass


# Module-level singleton
_engine: PolicyEngine | None = None


def get_engine() -> PolicyEngine:
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine
