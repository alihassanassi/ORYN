"""
bridge/scope.py — Scope enforcement gate.

Layer 2 of the 6-layer security onion. Hard gate — cannot be disabled.
Every autonomous action passes through is_in_scope() before execution.
Scope violations always escalate to operator. Never auto-approved.

This file extends (does not replace) any existing scope logic.
"""
import json, logging

logger = logging.getLogger(__name__)


def is_in_scope(target: str, program_id: int) -> bool:
    """
    Returns True ONLY if target is explicitly in scope for program_id.

    Scope is defined by the program's scope_domains JSON field:
      - "example.com"   → matches example.com and all subdomains
      - "*.example.com" → matches all subdomains only (not bare example.com)
      - "192.168.1.1"   → matches exact IP

    Fails closed (returns False) on any error — deny on ambiguity.
    """
    # Safety: never allow scanning JARVIS infrastructure
    from config.network import NET
    if NET.is_lab_machine(target) and not NET.is_safe_to_scan(target):
        return False

    if not target or not program_id:
        return False

    try:
        from storage.db import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT scope_domains FROM programs WHERE id=?", (program_id,)
            ).fetchone()

        if not row:
            logger.warning("[ScopeGate] program %d not found — denying", program_id)
            return False

        domains = json.loads(row[0] or "[]")
        if not domains:
            logger.warning("[ScopeGate] program %d has no scope_domains — denying", program_id)
            return False

        target_lower = target.lower().rstrip(".")

        for domain in domains:
            domain = domain.lower().rstrip(".")
            if domain.startswith("*."):
                # Wildcard: *.example.com matches sub.example.com but NOT example.com
                suffix = domain[2:]
                if target_lower.endswith("." + suffix):
                    return True
            else:
                # Exact or subdomain match: example.com matches example.com and *.example.com
                if target_lower == domain or target_lower.endswith("." + domain):
                    return True

        return False

    except Exception as e:
        logger.error("[ScopeGate] scope check error for %r program=%d: %s", target, program_id, e)
        return False  # fail closed — deny on error


def list_scope_domains(program_id: int) -> list[str]:
    """Returns the scope domains for a program. Empty list if not found."""
    try:
        from storage.db import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT scope_domains FROM programs WHERE id=?", (program_id,)
            ).fetchone()
        return json.loads(row[0] or "[]") if row else []
    except Exception:
        return []
