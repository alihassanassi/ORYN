"""
tools/program_tools.py — Bug bounty program management.

Programs are the top-level containers for bug bounty targets.
Each program has a scope (list of in-scope domains) and a platform.
"""
from __future__ import annotations

import json
from datetime import datetime


# ── Domain validation ─────────────────────────────────────────────────────────

def _validate_domain(domain: str) -> str:
    """Returns cleaned domain or raises ValueError."""
    d = domain.strip().lower().lstrip("https://").lstrip("http://").split("/")[0]
    if not d or len(d) > 100 or " " in d or "." not in d:
        raise ValueError(f"Invalid domain: {domain!r}")
    # Block shell-injection characters
    for ch in (";", "&", "|", "`", "$", "(", ")", "<", ">", "\n", "\r"):
        if ch in d:
            raise ValueError(f"Invalid domain (forbidden character {ch!r}): {domain!r}")
    return d


def _parse_scope_json(raw: str) -> list[str]:
    """Safely parse scope_domains JSON, returning an empty list on failure."""
    try:
        result = json.loads(raw or "[]")
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return []


# ── Tools ─────────────────────────────────────────────────────────────────────

def tool_list_programs() -> str:
    """List all bug bounty programs with scope count and status."""
    from storage.db import get_db
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, status, scope_domains, platform, created_at "
            "FROM programs ORDER BY created_at DESC"
        ).fetchall()
    if not rows:
        return "No programs. Add one with: create_program <name> <platform> <domain1,domain2>"
    lines = []
    for r in rows:
        domains = _parse_scope_json(r[3])
        lines.append(f"[{r[0]}] {r[1]} ({r[4]}) — {r[2]} — {len(domains)} domains")
    return "\n".join(lines)


def tool_create_program(
    name: str,
    platform: str = "hackerone",
    scope_domains: str = "",
) -> str:
    """Create a new bug bounty program with optional in-scope domains."""
    name = name.strip()
    if not name:
        return "Error: program name cannot be empty."

    platform = platform.strip().lower() or "hackerone"

    # Parse and validate comma-separated domains
    raw_domains = [d.strip() for d in scope_domains.split(",") if d.strip()] if scope_domains else []
    valid_domains: list[str] = []
    errors: list[str] = []
    for d in raw_domains:
        try:
            valid_domains.append(_validate_domain(d))
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        return "Domain validation failed:\n" + "\n".join(errors)

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for d in valid_domains:
        if d not in seen:
            seen.add(d)
            deduped.append(d)

    scope_json = json.dumps(deduped)
    created_at = datetime.utcnow().isoformat()

    from storage.db import get_db
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO programs (name, platform, scope_domains, created_at) VALUES (?, ?, ?, ?)",
                (name, platform, scope_json, created_at),
            )
            new_id = cur.lastrowid
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            return f"Error: a program named '{name}' already exists."
        return f"Error creating program: {exc}"

    n = len(deduped)
    return f"Program '{name}' created with {n} in-scope domain{'s' if n != 1 else ''}. Program ID: {new_id}"


def tool_add_scope(program_id: int, domain: str) -> str:
    """Add a domain to an existing program's scope."""
    if not program_id:
        return "Error: program_id is required."

    try:
        clean = _validate_domain(domain)
    except ValueError as exc:
        return f"Error: {exc}"

    from storage.db import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT name, scope_domains FROM programs WHERE id=?",
            (program_id,),
        ).fetchone()
        if not row:
            return f"Error: no program with ID {program_id}."

        program_name = row[0]
        domains = _parse_scope_json(row[1])

        if clean in domains:
            return f"'{clean}' is already in {program_name} scope ({len(domains)} domains total)."

        domains.append(clean)
        conn.execute(
            "UPDATE programs SET scope_domains=? WHERE id=?",
            (json.dumps(domains), program_id),
        )

    return f"Added {clean} to {program_name} scope. Total: {len(domains)} domains."


def tool_program_status(program_id: int | None = None) -> str:
    """
    Get status and finding counts for bug bounty programs.
    If program_id is given, show full details for that program.
    Otherwise show a summary of all programs with finding counts.
    """
    from storage.db import get_db
    with get_db() as conn:
        rows = conn.execute(
            "SELECT p.id, p.name, p.platform, p.status, "
            "COUNT(f.id) as findings, p.scope_domains "
            "FROM programs p LEFT JOIN findings_canonical f ON f.program_id=p.id "
            "WHERE p.id=COALESCE(?,p.id) GROUP BY p.id",
            (program_id,),
        ).fetchall()

    if not rows:
        if program_id:
            return f"No program found with ID {program_id}."
        return "No programs configured."

    lines = []
    for r in rows:
        pid, pname, platform, status, findings, scope_raw = r[0], r[1], r[2], r[3], r[4], r[5]
        domains = _parse_scope_json(scope_raw)
        if program_id:
            # Full detail view for a single program
            lines.append(f"Program: {pname}")
            lines.append(f"  ID:       {pid}")
            lines.append(f"  Platform: {platform}")
            lines.append(f"  Status:   {status}")
            lines.append(f"  Findings: {findings}")
            lines.append(f"  Scope ({len(domains)} domains):")
            for d in domains:
                lines.append(f"    • {d}")
        else:
            # Summary row
            domain_preview = ", ".join(domains[:3])
            if len(domains) > 3:
                domain_preview += f" (+{len(domains) - 3} more)"
            lines.append(
                f"[{pid}] {pname} ({platform}) — {status} — "
                f"{findings} finding{'s' if findings != 1 else ''} — "
                f"{len(domains)} domains"
                + (f": {domain_preview}" if domains else "")
            )

    return "\n".join(lines)


def tool_set_program_status(program_id: int, status: str) -> str:
    """Set the status of a bug bounty program (active, paused, completed)."""
    valid_statuses = {"active", "paused", "completed"}
    status = status.strip().lower()
    if status not in valid_statuses:
        return f"Error: status must be one of: {', '.join(sorted(valid_statuses))}."

    if not program_id:
        return "Error: program_id is required."

    from storage.db import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT name FROM programs WHERE id=?", (program_id,)
        ).fetchone()
        if not row:
            return f"Error: no program with ID {program_id}."
        conn.execute(
            "UPDATE programs SET status=? WHERE id=?",
            (status, program_id),
        )

    return f"Program '{row[0]}' (ID {program_id}) status set to '{status}'."


def tool_scope_check(program_id: int, domain: str) -> str:
    """Check whether a domain is in scope for a bug bounty program."""
    if not program_id:
        return "Error: program_id is required."

    try:
        clean = _validate_domain(domain)
    except ValueError as exc:
        return f"Error: {exc}"

    from bridge.scope import is_in_scope, list_scope_domains
    from storage.db import get_db

    with get_db() as conn:
        row = conn.execute(
            "SELECT name FROM programs WHERE id=?", (program_id,)
        ).fetchone()
    if not row:
        return f"Error: no program with ID {program_id}."

    program_name = row[0]
    in_scope = is_in_scope(clean, program_id)
    scope_domains = list_scope_domains(program_id)

    verdict = "IN SCOPE" if in_scope else "OUT OF SCOPE"
    if not scope_domains:
        return (
            f"{clean} — {verdict} (program '{program_name}' has no scope defined)"
        )

    scope_preview = ", ".join(scope_domains[:5])
    if len(scope_domains) > 5:
        scope_preview += f" (+{len(scope_domains) - 5} more)"

    return (
        f"{clean} — {verdict} for '{program_name}' (ID {program_id})\n"
        f"Scope: {scope_preview}"
    )
