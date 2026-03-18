"""
memory/operator_model.py — Persistent operator skill and behavior model.

Tracks operator skills, hunting style, technique win rates, and blindspots
across sessions. All data persists via memory.manager with layer='semantic'.

SECURITY: No network calls. No subprocess. Read-only DB access for history.
No PII — operator stats only.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Default model structure ───────────────────────────────────────────────────

_DEFAULT_MODEL: dict = {
    "skill_scores": {
        "xss":          0.0,
        "sqli":         0.0,
        "idor":         0.0,
        "ssrf":         0.0,
        "auth_bypass":  0.0,
        "api_security": 0.0,
        "logic_flaws":  0.0,
        "recon":        0.0,
    },
    "hunting_style":     {},
    "technique_win_rate": {},       # {"subfinder": [wins, attempts], ...}
    "identified_blindspots": [],
    "finding_history":   [],
    "program_preferences": [],
    "sessions_count":    0,
    "last_updated":      None,
}

# Vuln classes we track
VULN_CLASSES = list(_DEFAULT_MODEL["skill_scores"].keys())

# Techniques that indicate blindspots if never tried
_TECHNIQUE_CHECKLIST = [
    "graphql_introspection",
    "oauth_flow_testing",
    "password_reset_logic",
    "race_condition",
    "mass_assignment",
    "idor_chaining",
    "jwt_attacks",
    "xxe_injection",
    "cache_poisoning",
    "request_smuggling",
]


def _load_raw() -> dict:
    """Load the operator model from memory store. Returns default if not found."""
    try:
        from memory.store import MemoryStore
        store = MemoryStore()
        records = store.search_by_key("operator_model", layer="semantic")
        if records:
            raw = records[0].value
            if isinstance(raw, str):
                data = json.loads(raw)
            else:
                data = raw
            # Merge with defaults to handle new keys added over time
            merged = dict(_DEFAULT_MODEL)
            merged.update(data)
            merged["skill_scores"] = {**_DEFAULT_MODEL["skill_scores"], **data.get("skill_scores", {})}
            return merged
    except Exception as e:
        logger.debug(f"[OperatorModel] Load failed: {e}")
    return dict(_DEFAULT_MODEL)


def _save_raw(model: dict) -> None:
    """Persist the operator model via memory.manager."""
    try:
        model["last_updated"] = datetime.now().isoformat()
        from memory.manager import MemoryManager
        mm = MemoryManager()
        mm.remember(
            key="operator_model",
            value=json.dumps(model),
            layer="semantic",
            category="system",
            confidence=1.0,
            source="system",
            tags=["operator", "model", "skills"],
        )
    except Exception as e:
        logger.warning(f"[OperatorModel] Save failed: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def get_operator_model() -> dict:
    """Return the full operator model dict."""
    return _load_raw()


def update_from_session(session_data: dict) -> None:
    """
    Update the model from a completed session.

    session_data keys (all optional):
        findings: list[dict]  — each with 'vuln_class', 'severity', 'program'
        tools_used: list[str]
        techniques_tried: list[str]
        program: str
        duration_secs: int
    """
    model = _load_raw()
    model["sessions_count"] = model.get("sessions_count", 0) + 1

    # Update finding history
    for finding in session_data.get("findings", []):
        entry = {
            "vuln_class": finding.get("vuln_class", "unknown"),
            "severity":   finding.get("severity",   "info"),
            "program":    finding.get("program",     "unknown"),
            "date":       datetime.now().strftime("%Y-%m-%d"),
        }
        model["finding_history"].append(entry)
        # Boost skill score for the relevant class
        vc = finding.get("vuln_class", "")
        if vc in model["skill_scores"]:
            current = model["skill_scores"][vc]
            severity_boost = {"critical": 0.15, "high": 0.10, "medium": 0.05, "low": 0.02}.get(
                finding.get("severity", "low"), 0.01
            )
            model["skill_scores"][vc] = min(1.0, current + severity_boost)

    # Update technique win rates
    for tool in session_data.get("tools_used", []):
        wins, attempts = model["technique_win_rate"].get(tool, [0, 0])
        model["technique_win_rate"][tool] = [wins, attempts + 1]
    for finding in session_data.get("findings", []):
        tool = finding.get("found_by", "")
        if tool and tool in model["technique_win_rate"]:
            w, a = model["technique_win_rate"][tool]
            model["technique_win_rate"][tool] = [w + 1, a]

    # Update program preferences (most recent = highest priority)
    prog = session_data.get("program", "")
    if prog:
        prefs = model.get("program_preferences", [])
        if prog in prefs:
            prefs.remove(prog)
        prefs.insert(0, prog)
        model["program_preferences"] = prefs[:20]  # keep top 20

    # Update hunting style
    techniques = session_data.get("techniques_tried", [])
    for t in techniques:
        model["hunting_style"][t] = model["hunting_style"].get(t, 0) + 1

    # Recompute blindspots
    tried = set(model["hunting_style"].keys())
    model["identified_blindspots"] = [t for t in _TECHNIQUE_CHECKLIST if t not in tried]

    _save_raw(model)


def get_skill_summary() -> str:
    """
    Return a short text summary of operator skills for LLM system prompt injection.
    Example: 'Operator strengths: recon (0.7), api_security (0.5). Blindspots: graphql_introspection, jwt_attacks.'
    """
    model = _load_raw()
    scores = model.get("skill_scores", {})
    strengths = sorted(
        [(k, v) for k, v in scores.items() if v >= 0.3],
        key=lambda x: x[1], reverse=True
    )
    weak = [k for k, v in scores.items() if v < 0.1]
    blindspots = model.get("identified_blindspots", [])[:3]

    parts = []
    if strengths:
        parts.append("Operator strengths: " + ", ".join(f"{k} ({v:.1f})" for k, v in strengths[:4]))
    if blindspots:
        parts.append("Untried techniques: " + ", ".join(blindspots))
    if model.get("sessions_count", 0) == 0:
        parts.append("New operator — no session history yet.")

    return " ".join(parts) if parts else "No operator model data yet."


def get_blindspot_hint() -> str:
    """Return a single actionable hint about an untried technique."""
    model = _load_raw()
    blindspots = model.get("identified_blindspots", [])
    if not blindspots:
        return ""
    hint_map = {
        "graphql_introspection": "You haven't tried GraphQL introspection yet. Several active programs expose GraphQL APIs.",
        "oauth_flow_testing":    "OAuth flow testing is untried. Auth bugs are high-severity and often overlooked.",
        "password_reset_logic":  "Password reset logic flaws are untested — common source of account takeover bugs.",
        "race_condition":        "Race condition testing hasn't been attempted. High-value, low-competition finding type.",
        "mass_assignment":       "Mass assignment attacks on JSON APIs are untried.",
        "idor_chaining":         "IDOR chaining hasn't been tried. Single IDORs are often low severity; chains are critical.",
        "jwt_attacks":           "JWT algorithm confusion attacks are untested.",
        "xxe_injection":         "XXE injection hasn't been tested. Still present in enterprise XML parsers.",
        "cache_poisoning":       "Cache poisoning via unkeyed headers is untried.",
        "request_smuggling":     "HTTP request smuggling hasn't been tested. CDN targets are especially susceptible.",
    }
    return hint_map.get(blindspots[0], f"Try {blindspots[0].replace('_', ' ')} — it's in your blindspot list.")


def get_best_program_match(available_programs: list) -> str:
    """Return the program name from available_programs that best matches operator history."""
    model = _load_raw()
    prefs = model.get("program_preferences", [])
    for preferred in prefs:
        for prog in available_programs:
            name = prog.get("name", "") if isinstance(prog, dict) else str(prog)
            if preferred.lower() in name.lower():
                return name
    # Fall back to first available
    if available_programs:
        p = available_programs[0]
        return p.get("name", str(p)) if isinstance(p, dict) else str(p)
    return ""


# ── Tool functions (registered by tools/registry.py) ─────────────────────────

def tool_operator_model_summary() -> dict:
    """Tool: return operator skill summary as text."""
    summary = get_skill_summary()
    model = _load_raw()
    return {
        "ok": True,
        "output": summary,
        "error": None,
        "artifacts": [],
        "meta": {
            "sessions": model.get("sessions_count", 0),
            "strengths": {k: v for k, v in model.get("skill_scores", {}).items() if v >= 0.3},
        },
    }


def tool_operator_blindspots() -> dict:
    """Tool: return list of untried techniques."""
    model = _load_raw()
    blindspots = model.get("identified_blindspots", [])
    hint = get_blindspot_hint()
    return {
        "ok": True,
        "output": hint or "No blindspots identified yet.",
        "error": None,
        "artifacts": [],
        "meta": {"blindspots": blindspots},
    }
