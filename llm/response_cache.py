"""
llm/response_cache.py — In-memory response cache for JARVIS.

Caches deterministic, read-only tool results in RAM.
48GB RAM available — max 512MB cache size (trivial overhead).
Cache is ephemeral: wiped on restart by design.

SAFETY:
  - Network tools (subfinder, httpx, nuclei) are NEVER cached.
  - Mutation tools (save_*, kill_switch_*) are NEVER cached.
  - Security-sensitive results are NEVER cached.
  - All entries expire via TTL.
"""
from __future__ import annotations
import hashlib
import time
import threading
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Tools safe to cache: deterministic, read-only, non-network
CACHEABLE_TOOLS: dict[str, float] = {
    "system_status":           30.0,   # 30s TTL
    "list_programs":           60.0,
    "list_projects":           60.0,
    "list_findings":           30.0,
    "list_targets":            30.0,
    "list_capabilities":      300.0,   # 5 min — rarely changes
    "operator_model_summary":  120.0,
    "operator_blindspots":    300.0,
    "memory_stats":            60.0,
    "watchdog_status":         30.0,
    "safety_status":           30.0,
    "morning_briefing":       600.0,   # 10 min
    "strategy_briefing":      120.0,
    "finding_digest":          60.0,
    "list_unverified_findings": 30.0,
}

# Tools NEVER cached — network, mutations, security
NEVER_CACHE: frozenset[str] = frozenset({
    "run_subfinder", "run_httpx", "run_nuclei",
    "save_finding", "save_target", "save_note",
    "kill_switch_trigger", "kill_switch_reset",
    "run_command", "open_app",
    "switch_persona", "set_voice_profile", "set_voice",
    "recon_loop_start", "recon_loop_stop",
    "db_maintenance",
})

# Mutation tools that should invalidate related cache entries
_INVALIDATION_MAP: dict[str, list[str]] = {
    "save_finding":  ["list_findings", "finding_digest", "list_unverified_findings"],
    "save_target":   ["list_targets"],
    "save_note":     [],
    "create_program": ["list_programs"],
    "add_scope":     ["list_programs"],
    "set_program_status": ["list_programs"],
}


class ResponseCache:
    """Thread-safe in-memory LRU cache for tool results."""

    MAX_BYTES: int = 512 * 1024 * 1024  # 512MB ceiling

    def __init__(self) -> None:
        self._cache: dict[str, tuple[Any, float, float]] = {}  # key -> (value, ts, ttl)
        self._lock  = threading.Lock()
        self._hits  = 0
        self._misses = 0
        self._evictions = 0

    # ── Key generation ──────────────────────────────────────────────────────
    @staticmethod
    def _key(tool: str, args: dict) -> str:
        raw = f"{tool}:{sorted(args.items())}"
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

    # ── Public API ──────────────────────────────────────────────────────────
    def get(self, tool: str, args: dict) -> Optional[Any]:
        """Return cached result or None if missing/expired/uncacheable."""
        if tool not in CACHEABLE_TOOLS or tool in NEVER_CACHE:
            return None
        k = self._key(tool, args)
        with self._lock:
            entry = self._cache.get(k)
            if entry is None:
                self._misses += 1
                return None
            value, ts, ttl = entry
            if time.monotonic() - ts > ttl:
                del self._cache[k]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, tool: str, args: dict, value: Any) -> None:
        """Store result. Silently skips uncacheable tools."""
        if tool not in CACHEABLE_TOOLS or tool in NEVER_CACHE:
            return
        ttl = CACHEABLE_TOOLS[tool]
        k   = self._key(tool, args)
        with self._lock:
            self._cache[k] = (value, time.monotonic(), ttl)

    def invalidate_for(self, mutation_tool: str) -> None:
        """Evict stale entries after a mutation tool runs."""
        affected = _INVALIDATION_MAP.get(mutation_tool, [])
        if not affected:
            return
        with self._lock:
            stale = [k for k in list(self._cache) if any(t in k for t in affected)]
            for k in stale:
                del self._cache[k]
                self._evictions += 1

    def invalidate_tool(self, tool: str) -> None:
        """Evict all entries for a specific tool name."""
        with self._lock:
            stale = [k for k in list(self._cache)
                     if self._cache[k][0] is not None and tool in k]
            for k in stale:
                del self._cache[k]
                self._evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = self._misses = self._evictions = 0

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            rate  = (self._hits / total * 100) if total else 0.0
            return {
                "entries":    len(self._cache),
                "hits":       self._hits,
                "misses":     self._misses,
                "evictions":  self._evictions,
                "hit_rate":   f"{rate:.1f}%",
            }


# Module-level singleton
response_cache: ResponseCache = ResponseCache()
