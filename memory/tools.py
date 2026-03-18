"""
memory/tools.py — JARVIS tool implementations for the memory subsystem.

These functions match the tools/registry.py dispatch() pattern:
  - Each function takes explicit keyword args
  - Returns a plain string (the tool result)
  - No exceptions bubble up — all errors return a descriptive string

Registered tools:
  remember, recall, forget, pin_memory, inspect_memory, memory_stats,
  memory_hygiene
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _mm():
    """Lazy import of MemoryManager to avoid circular imports at module load."""
    from memory.manager import MemoryManager
    return MemoryManager()


def tool_remember(
    key:        str,
    value:      str,
    layer:      str = "semantic",
    category:   str = "user_fact",
    confidence: float = 1.0,
    tags:       Optional[list] = None,
    project_id: Optional[int] = None,
    pinned:     bool = False,
    expires_days: Optional[int] = None,
) -> str:
    """
    Store a memory record. Called when the operator explicitly asks JARVIS
    to remember something.

    Returns a confirmation string.
    """
    try:
        mem_id = _mm().remember(
            key=key,
            value=value,
            layer=layer,
            category=category,
            confidence=float(confidence),
            source="user_explicit",
            project_id=project_id,
            tags=tags,
            pinned=pinned,
            expires_days=expires_days,
        )
        if mem_id < 0:
            return f"Memory write failed for key '{key}'."
        pin_note = " (pinned)" if pinned else ""
        return f"Memory stored: '{key}' = '{value[:80]}' [layer={layer}]{pin_note} (id={mem_id})"
    except Exception as e:
        logger.error("[tool_remember] error: %s", e)
        return f"Error storing memory: {e}"


def tool_recall(
    query:      str,
    project_id: Optional[int] = None,
) -> str:
    """
    Retrieve relevant memories for a query.
    Returns formatted memory context or a message indicating nothing was found.
    """
    try:
        ctx = _mm().recall(query=query, project_id=project_id)
        if not ctx:
            return "No relevant memories found for that query."
        return ctx
    except Exception as e:
        logger.error("[tool_recall] error: %s", e)
        return f"Error recalling memories: {e}"


def tool_forget(memory_id: int) -> str:
    """
    Soft-delete a memory by ID. Pinned memories cannot be forgotten.
    """
    try:
        _mm().forget(int(memory_id))
        return f"Memory {memory_id} suppressed (soft-deleted). Pinned memories are unaffected."
    except Exception as e:
        logger.error("[tool_forget] error: %s", e)
        return f"Error forgetting memory {memory_id}: {e}"


def tool_pin_memory(memory_id: int) -> str:
    """
    Pin a memory so it is never pruned or forgotten.
    """
    try:
        _mm().pin(int(memory_id))
        return f"Memory {memory_id} pinned. It will not be pruned or forgotten."
    except Exception as e:
        logger.error("[tool_pin_memory] error: %s", e)
        return f"Error pinning memory {memory_id}: {e}"


def tool_inspect_memory(
    layer:      Optional[str] = None,
    project_id: Optional[int] = None,
    limit:      int = 20,
) -> str:
    """
    List memory records in a human-readable format.
    Optionally filtered by layer or project.
    """
    try:
        records = _mm().inspect(
            layer=layer,
            project_id=int(project_id) if project_id else None,
            limit=int(limit),
        )
        if not records:
            return "No memory records found with those filters."

        lines = [f"Memory records ({len(records)} shown):"]
        for r in records:
            pin_mark = " [PINNED]" if r.get("pinned") else ""
            expire_note = f"  expires={r['expires_at'][:10]}" if r.get("expires_at") else ""
            lines.append(
                f"  [{r['id']:4d}] {r['layer']:10s} | {r['key'][:40]:40s} = "
                f"{str(r['value'])[:60]:60s} "
                f"(conf={r['confidence']:.2f}, acc={r['access_count']}){pin_mark}{expire_note}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error("[tool_inspect_memory] error: %s", e)
        return f"Error inspecting memory: {e}"


def tool_memory_stats() -> str:
    """
    Show memory subsystem statistics: record counts per layer, totals, conflicts.
    """
    try:
        stats = _mm().get_stats()
        if "error" in stats:
            return f"Memory stats error: {stats['error']}"

        lines = ["Memory subsystem stats:"]
        lines.append(f"  Total active:   {stats.get('total_active', 0)}")
        lines.append(f"  Total pinned:   {stats.get('total_pinned', 0)}")
        lines.append(f"  Open conflicts: {stats.get('open_conflicts', 0)}")
        lines.append("  By layer:")
        for key, val in stats.items():
            if key.startswith("layer."):
                layer_name = key[6:]
                lines.append(f"    {layer_name:12s}: {val}")
        return "\n".join(lines)
    except Exception as e:
        logger.error("[tool_memory_stats] error: %s", e)
        return f"Error getting memory stats: {e}"


def tool_memory_hygiene() -> str:
    """
    Run memory maintenance: prune expired/stale records, enforce size caps,
    promote eligible episodic → semantic memories.
    """
    try:
        result = _mm().run_hygiene()
        if "error" in result:
            return f"Hygiene error: {result['error']}"

        lines = ["Memory hygiene complete:"]
        lines.append(f"  Expired pruned:    {result.get('expired_pruned', 0)}")
        lines.append(f"  Stale pruned:      {result.get('stale_pruned', 0)}")
        lines.append(f"  Superseded pruned: {result.get('superseded_pruned', 0)}")
        lines.append(f"  Promoted to semantic: {result.get('promoted', 0)}")

        layer_pruned = result.get("layer_pruned", {})
        if layer_pruned:
            lines.append("  Layer caps enforced:")
            for layer, count in layer_pruned.items():
                lines.append(f"    {layer}: {count} removed")

        return "\n".join(lines)
    except Exception as e:
        logger.error("[tool_memory_hygiene] error: %s", e)
        return f"Error running hygiene: {e}"
