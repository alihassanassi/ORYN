"""
intelligence/coaching_engine.py — Surface tactical suggestions at natural breakpoints.

Monitors operator activity and fires suggestions only when:
  1. Operator has paused > COACHING_PAUSE_THRESHOLD_SECS seconds
  2. Fewer than COACHING_MAX_SUGGESTIONS_PER_SESSION suggestions given this session
  3. A relevant suggestion exists based on recent tool usage

Each suggestion:
  - One sentence max
  - Based on operator history, not generic advice
  - Never suggests out-of-scope or destructive actions
  - Logged to memory with layer='episodic'
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# Module-level state (shared across imports)
_last_activity_time: float = time.time()
_session_suggestions: int = 0
_session_tools_used: list[str] = []
_instance: "CoachingEngine | None" = None


def record_activity(tool_name: str = "") -> None:
    """Call this whenever the operator does something — resets the pause timer."""
    global _last_activity_time, _session_tools_used
    _last_activity_time = time.time()
    if tool_name and tool_name not in _session_tools_used:
        _session_tools_used.append(tool_name)


class CoachingEngine:
    """Background coaching service — fires suggestions at natural pause points."""

    _RULES: list[dict] = [
        {
            "trigger_tool":    "subfinder",
            "hint":            "Consider running httpx on subfinder results to identify live hosts before scanning.",
            "requires_unused": "httpx",
        },
        {
            "trigger_tool":    "httpx",
            "hint":            "After HTTP discovery, nuclei can scan for known CVEs on identified tech stacks.",
            "requires_unused": "nuclei",
        },
        {
            "trigger_count":   5,
            "trigger_tool":    "nuclei",
            "hint":            "If nuclei isn't finding bugs, the target may be well-patched — try logic flaw testing instead.",
            "requires_unused": None,
        },
        {
            "blindspot_key":   "graphql_introspection",
            "hint":            "You haven't tried GraphQL introspection. Several programs expose /graphql endpoints with verbose errors.",
            "requires_unused": None,
        },
        {
            "blindspot_key":   "password_reset_logic",
            "hint":            "Password reset logic flaws are untested — they're a common source of account takeover bugs.",
            "requires_unused": None,
        },
        {
            "blindspot_key":   "oauth_flow_testing",
            "hint":            "OAuth flow testing hasn't been tried. Auth bugs are high-severity and often overlooked.",
            "requires_unused": None,
        },
        {
            "trigger_tool":    "dns_lookup",
            "hint":            "DNS enumeration complete — try whois on interesting domains to identify hosting providers and ASNs.",
            "requires_unused": "whois_lookup",
        },
    ]

    def __init__(self):
        global _instance
        _instance = self
        self._thread    = None
        self._stop_evt  = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, name="CoachingEngine", daemon=True
        )
        self._thread.start()
        logger.info("[CoachingEngine] Started")

    def stop(self) -> None:
        self._stop_evt.set()

    def _loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                hint = self._get_hint_if_due()
                if hint:
                    self._deliver(hint)
            except Exception as e:
                logger.debug(f"[CoachingEngine] Loop error: {e}")
            self._stop_evt.wait(10)  # check every 10s

    def _get_hint_if_due(self) -> str:
        """Return a hint if conditions are met, else empty string."""
        import config as _c
        global _session_suggestions, _last_activity_time, _session_tools_used

        if not getattr(_c, 'COACHING_ENABLED', True):
            return ""

        # Check pause threshold
        pause_secs = getattr(_c, 'COACHING_PAUSE_THRESHOLD_SECS', 30)
        if (time.time() - _last_activity_time) < pause_secs:
            return ""

        # Check session cap
        max_hints = getattr(_c, 'COACHING_MAX_SUGGESTIONS_PER_SESSION', 5)
        if _session_suggestions >= max_hints:
            return ""

        # Check blindspots from operator model
        blindspots = []
        try:
            from memory.operator_model import get_operator_model
            model = get_operator_model()
            blindspots = model.get("identified_blindspots", [])
        except Exception:
            pass

        # Evaluate rules
        for rule in self._RULES:
            hint = self._evaluate_rule(rule, _session_tools_used, blindspots)
            if hint:
                return hint

        return ""

    def _evaluate_rule(self, rule: dict, tools_used: list[str], blindspots: list[str]) -> str:
        """Evaluate one rule. Return hint string if it fires, else ''."""
        # Blindspot rule
        if "blindspot_key" in rule:
            if rule["blindspot_key"] in blindspots:
                required_unused = rule.get("requires_unused")
                if required_unused is None or required_unused not in tools_used:
                    return rule["hint"]
            return ""

        # Tool trigger rule
        trigger_tool = rule.get("trigger_tool", "")
        if trigger_tool and trigger_tool not in tools_used:
            return ""

        # Count trigger (how many times trigger_tool used)
        count_req = rule.get("trigger_count", 1)
        tool_count = tools_used.count(trigger_tool)
        if tool_count < count_req:
            return ""

        # Required unused tool
        required_unused = rule.get("requires_unused")
        if required_unused and required_unused in tools_used:
            return ""  # already tried it

        return rule["hint"]

    def _deliver(self, hint: str) -> None:
        """Deliver a hint via TTS and memory logging."""
        global _session_suggestions, _last_activity_time
        _session_suggestions += 1
        # Reset activity timer so we don't fire again immediately
        _last_activity_time = time.time()

        logger.info(f"[CoachingEngine] Hint: {hint}")

        # Log to memory
        try:
            from memory.manager import MemoryManager
            MemoryManager().remember(
                key=f"coaching_hint_{datetime.now().strftime('%Y%m%d_%H%M')}",
                value=hint,
                layer="episodic",
                category="system",
                confidence=0.8,
                source="system",
                tags=["coaching", "hint"],
            )
        except Exception:
            pass

        # Deliver via TTS if available
        try:
            from tools.voice_tools import _TTS_REF
            if _TTS_REF:
                _TTS_REF[0].speak(hint)
        except Exception:
            pass

    @staticmethod
    def get_hint_if_due() -> str:
        """Static method for agents/worker.py to poll after each response."""
        global _instance
        if _instance is None:
            import config as _c
            if not getattr(_c, 'COACHING_ENABLED', True):
                return ""
            # Create lightweight instance without starting background thread
            engine = CoachingEngine.__new__(CoachingEngine)
            engine._thread = None
            engine._stop_evt = threading.Event()
            _instance = engine
        try:
            return _instance._get_hint_if_due()
        except Exception:
            return ""
