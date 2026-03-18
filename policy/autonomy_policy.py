"""
AutonomyPolicyEngine — hard rules for what autonomous actions are permitted.

This is NOT the same as policy/engine.py (the per-action policy gate).
This layer governs whether the AUTONOMY SYSTEM ITSELF is allowed to
propose or execute a given action.

Critical security property: this policy engine cannot be modified
by the LLM, the preference engine, or any config flag.
The hard rules are enforced at the code level, not the config level.

Separation of powers: the autonomy stack proposes, this engine decides.
The autonomy stack cannot approve its own proposals.
"""
import logging
from bridge.scope import is_in_scope
from runtime.kill_switch import KILL_FLAG
from storage.audit_log import ImmutableAuditLog

logger = logging.getLogger(__name__)

# Tools that are NEVER permitted in autonomous mode — require explicit operator command
_NEVER_AUTONOMOUS = frozenset({
    # Active exploitation
    "sqlmap", "metasploit", "msfconsole", "msfvenom",
    # Destructive/noisy scanning
    "nmap_aggressive", "masscan", "zap_attack",
    # Credential testing
    "hydra", "medusa", "crackmapexec",
    # Any tool that modifies server state
    "curl_post_payload", "ffuf_bruteforce",
    # Report submission (never automated — human must submit)
    "submit_report", "submit_to_hackerone", "submit_to_bugcrowd",
})

# Tools permitted in autonomous mode (read-only recon only)
_AUTONOMOUS_ALLOWLIST = frozenset({
    "subfinder", "dnsx", "httpx", "gau", "katana_passive",
    "nuclei_safe",   # nuclei with only safe/detection templates, no active exploit
    "waybackurls", "assetfinder", "amass_passive",
})

_NUCLEI_NEVER_AUTONOMOUS_TAGS = frozenset({
    "intrusive", "dos", "rce-active", "sqli-active",
    "fuzzing", "bruteforce", "auth-bypass-active",
})


class AutonomyPolicyDecision:
    __slots__ = ("permitted", "reason", "requires_operator")

    def __init__(self, permitted: bool, reason: str, requires_operator: bool = False):
        self.permitted = permitted
        self.reason = reason
        self.requires_operator = requires_operator

    def __bool__(self):
        return self.permitted

    def __repr__(self):
        return f"AutonomyPolicyDecision(permitted={self.permitted}, reason={self.reason!r})"


class AutonomyPolicyEngine:
    """
    Hard gate on all autonomous actions.

    Usage:
      policy = AutonomyPolicyEngine()
      decision = policy.evaluate(tool_name, args, program_id)
      if not decision:
          logger.warning("Autonomous action blocked: %s", decision.reason)
          return
    """

    def __init__(self):
        self._audit = ImmutableAuditLog()

    def _audit_decision(
        self,
        action: str,
        decision: AutonomyPolicyDecision,
        context: dict | None = None,
    ) -> None:
        """Write a policy decision to the immutable audit log. Never raises."""
        try:
            self._audit.append(
                event_type="policy_decision",
                actor=context.get("source", "autonomy") if context else "autonomy",
                target=context.get("target") if context else None,
                tool=action,
                decision="permit" if decision.permitted else "deny",
                reason=decision.reason,
                requires_operator=decision.requires_operator,
                permitted=decision.permitted,
                context=context or {},
            )
        except Exception as e:
            logger.debug("[Policy] audit write failed: %s", e)

        # Also write denied actions to the dedicated denied_actions table so
        # queries and UI can surface them without scanning the full audit log.
        if not decision.permitted:
            try:
                import json as _json
                from storage.db import log_denied_action
                log_denied_action(
                    action=action,
                    args=_json.dumps(context or {}),
                    reason=decision.reason,
                )
            except Exception as e:
                logger.debug("[Policy] denied_actions log failed: %s", e)

    def evaluate(
        self,
        tool_name: str,
        args: dict,
        program_id: int,
        source: str = "recon_loop",
    ) -> AutonomyPolicyDecision:
        """
        Evaluates whether an autonomous action is permitted.
        All checks are AND conditions — all must pass.

        Logs every decision (permit or deny) to ImmutableAuditLog.
        """
        decision = self._evaluate_internal(tool_name, args, program_id)
        self._audit_decision(
            action=tool_name,
            decision=decision,
            context={
                "tool": tool_name,
                "source": source,
                "target": args.get("target", "unknown"),
                "program_id": program_id,
            },
        )
        return decision

    def _evaluate_internal(
        self, tool_name: str, args: dict, program_id: int
    ) -> AutonomyPolicyDecision:
        """
        HARD RULES — none of these can be overridden by config or LLM.
        """
        # RULE 1: Tool must be on the autonomous allowlist
        if tool_name in _NEVER_AUTONOMOUS:
            return AutonomyPolicyDecision(
                False,
                f"{tool_name} is never permitted in autonomous mode",
                requires_operator=True,
            )
        if tool_name not in _AUTONOMOUS_ALLOWLIST:
            return AutonomyPolicyDecision(
                False,
                f"{tool_name} is not on the autonomous allowlist",
                requires_operator=True,
            )

        # RULE 2: Target must be in scope — ALWAYS, no exceptions
        target = args.get("target") or args.get("domain") or args.get("host", "")
        if not target:
            return AutonomyPolicyDecision(False, "no target specified")

        try:
            from security.sanitizer import validate_domain
            target = validate_domain(target)
        except ValueError as e:
            return AutonomyPolicyDecision(False, f"invalid target: {e}")

        if not is_in_scope(target, program_id):
            return AutonomyPolicyDecision(
                False,
                f"target {target!r} is out of scope for program {program_id}",
                requires_operator=True,
            )

        # RULE 3: Nuclei-specific — only safe template tags
        if tool_name == "nuclei_safe":
            tags = args.get("tags", set())
            if isinstance(tags, str):
                tags = {t.strip() for t in tags.split(",")}
            elif not isinstance(tags, set):
                tags = set(tags)
            forbidden = tags & _NUCLEI_NEVER_AUTONOMOUS_TAGS
            if forbidden:
                return AutonomyPolicyDecision(
                    False,
                    f"nuclei tags not permitted in autonomous mode: {forbidden}",
                    requires_operator=True,
                )

        # RULE 4: No POST requests or payloads in autonomous mode
        method = args.get("method", "GET").upper()
        if method not in ("GET", "HEAD", "OPTIONS"):
            return AutonomyPolicyDecision(
                False,
                f"HTTP method {method} not permitted in autonomous mode",
                requires_operator=True,
            )

        # RULE 5: Daily job cap (persisted — survives restarts)
        if not self._daily_budget_available():
            return AutonomyPolicyDecision(
                False,
                "daily autonomous job limit reached — resume tomorrow",
            )

        # RULE 6: Kill switch file check (filesystem, not Python state)
        if KILL_FLAG.exists():
            return AutonomyPolicyDecision(
                False,
                "emergency stop flag is active — no autonomous actions permitted",
                requires_operator=True,
            )

        return AutonomyPolicyDecision(True, "all policy checks passed")

    def _daily_budget_available(self) -> bool:
        """
        Checks persisted daily job count in DB — survives process restarts.
        RECON_MAX_DAILY_JOBS is a hard ceiling, not a suggestion.
        """
        import config
        from storage.db import get_db
        max_jobs = getattr(config, "RECON_MAX_DAILY_JOBS", 10)
        try:
            with get_db() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) FROM actions
                       WHERE source IN ('recon_loop','autonomy')
                       AND created_at > datetime('now', '-1 day')""",
                ).fetchone()
                return (row[0] if row else 0) < max_jobs
        except Exception as e:
            logger.error("[AutonomyPolicy] daily budget check failed: %s", e)
            return False   # fail closed — deny on error
