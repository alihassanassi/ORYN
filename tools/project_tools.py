"""
tools/project_tools.py — Project and notes tools.
"""
from __future__ import annotations
from storage.db import (
    list_projects, set_active_project, get_active_project,
    append_note, get_notes, save_target, list_targets,
    save_finding, list_findings,
)


def tool_list_projects() -> str:
    projs = list_projects()
    if not projs:
        return "No projects found."
    lines = []
    for p in projs:
        marker = "● " if p["active"] else "○ "
        lines.append(f"{marker}{p['name']}")
    return "\n".join(lines)


def tool_switch_project(name: str) -> str:
    set_active_project(name)
    return f"Switched to project '{name}'."


def tool_save_note(content: str) -> str:
    proj = get_active_project()
    append_note(proj, content)
    return f"Note saved to {proj}."


def tool_read_notes() -> str:
    proj  = get_active_project()
    notes = get_notes(proj)
    return notes if notes else f"No notes in {proj} yet."


def tool_show_proposals() -> str:
    return "No proposals queued."


def tool_save_target(target: str, notes: str = "") -> str:
    proj = get_active_project()
    save_target(proj, target, notes)
    return f"Target '{target}' saved to {proj}."


def tool_list_targets() -> str:
    proj    = get_active_project()
    targets = list_targets(proj)
    if not targets:
        return f"No targets in {proj}."
    lines = [f"Targets in {proj}:"]
    for t in targets:
        lines.append(f"  [{t['id']}] {t['target']}  — {t['notes'] or 'no notes'}")
    return "\n".join(lines)


def tool_save_finding(title: str, detail: str = "", severity: str = "info",
                      target: str = "") -> str:
    proj = get_active_project()
    save_finding(proj, target, title, detail, severity)
    return f"Finding '{title}' saved to {proj}."


def tool_list_findings() -> str:
    proj     = get_active_project()
    findings = list_findings(proj)
    if not findings:
        return f"No findings in {proj}."
    lines = [f"Findings in {proj}:"]
    for f in findings:
        lines.append(
            f"  [{f['id']}] [{f['severity'].upper()}] {f['title']}"
            f"  — {f['target'] or 'no target'}"
        )
    return "\n".join(lines)
