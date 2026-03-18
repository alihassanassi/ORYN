"""
memory/store.py — SQLite storage layer for the JARVIS memory subsystem.

Uses the existing get_db() context manager from storage/db.py so all
memory records live in the same jarvis.db alongside other tables.

Thread-safety: each method opens/closes its own connection via get_db().
No long-lived connections are held.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from memory.models import MemoryRecord, MemoryLayer, ConflictRecord

logger = logging.getLogger(__name__)

# ── SQL table definitions ─────────────────────────────────────────────────────

_CREATE_MEMORIES = """
CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    layer         TEXT NOT NULL,
    category      TEXT NOT NULL,
    key           TEXT NOT NULL,
    value         TEXT NOT NULL,
    confidence    REAL DEFAULT 1.0,
    source        TEXT NOT NULL,
    provenance    TEXT,
    project_id    INTEGER,
    persona       TEXT,
    tags          TEXT DEFAULT '[]',
    pinned        INTEGER DEFAULT 0,
    suppressed    INTEGER DEFAULT 0,
    access_count  INTEGER DEFAULT 0,
    last_accessed TEXT,
    reinforced_at TEXT,
    expires_at    TEXT,
    superseded_by INTEGER,
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);
"""

_CREATE_CONFLICTS = """
CREATE TABLE IF NOT EXISTS memory_conflicts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id_a   INTEGER NOT NULL,
    memory_id_b   INTEGER NOT NULL,
    conflict_type TEXT,
    resolved      INTEGER DEFAULT 0,
    resolution    TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_memories_layer     ON memories(layer);
CREATE INDEX IF NOT EXISTS idx_memories_key       ON memories(key);
CREATE INDEX IF NOT EXISTS idx_memories_project   ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_memories_layer_key ON memories(layer, key);
CREATE INDEX IF NOT EXISTS idx_memories_suppressed ON memories(suppressed);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    """
    Low-level SQLite access for memory records.
    All public methods are exception-safe and return sensible defaults on error.
    """

    # ── Initialization ────────────────────────────────────────────────────────

    @staticmethod
    def initialize() -> None:
        """
        Create the memories and memory_conflicts tables if they don't exist.
        Safe to call multiple times (idempotent).
        Called from storage.db.db_init().
        """
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.executescript(_CREATE_MEMORIES)
                conn.executescript(_CREATE_CONFLICTS)
                conn.executescript(_CREATE_INDEXES)
        except Exception as e:
            logger.error("[MemoryStore] initialize error: %s", e)

    # ── Write ─────────────────────────────────────────────────────────────────

    def write(self, record: MemoryRecord) -> int:
        """
        Insert a new memory record or update existing by key+layer.

        If a record with the same key and layer already exists:
        - If same value: reinforce (bump access count, update reinforced_at)
        - If different value: update value and confidence, record as updated

        Returns the memory ID (new or existing).
        """
        try:
            from storage.db import get_db
            now = _now_iso()
            with get_db() as conn:
                # Check for existing record with same key+layer
                existing = conn.execute(
                    "SELECT id, value, confidence, pinned FROM memories "
                    "WHERE key=? AND layer=? AND suppressed=0 "
                    "ORDER BY id DESC LIMIT 1",
                    (record.key, record.layer)
                ).fetchone()

                if existing:
                    ex_id = existing["id"]
                    if existing["value"] == record.value:
                        # Exact match — just reinforce
                        conn.execute(
                            "UPDATE memories SET access_count=access_count+1, "
                            "reinforced_at=?, updated_at=? WHERE id=?",
                            (now, now, ex_id)
                        )
                        return ex_id
                    else:
                        # Value changed — update
                        conn.execute(
                            "UPDATE memories SET value=?, confidence=?, source=?, "
                            "provenance=?, tags=?, updated_at=?, reinforced_at=? "
                            "WHERE id=?",
                            (
                                record.value,
                                record.confidence,
                                record.source,
                                record.provenance,
                                record.tags or "[]",
                                now, now,
                                ex_id
                            )
                        )
                        return ex_id

                # New record
                cur = conn.execute(
                    """INSERT INTO memories
                       (layer, category, key, value, confidence, source, provenance,
                        project_id, persona, tags, pinned, suppressed, access_count,
                        last_accessed, reinforced_at, expires_at, superseded_by,
                        created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        record.layer,
                        record.category,
                        record.key,
                        record.value,
                        record.confidence,
                        record.source,
                        record.provenance,
                        record.project_id,
                        record.persona,
                        record.tags or "[]",
                        record.pinned,
                        record.suppressed,
                        record.access_count,
                        record.last_accessed,
                        record.reinforced_at,
                        record.expires_at,
                        record.superseded_by,
                        now,
                        now,
                    )
                )
                return cur.lastrowid
        except Exception as e:
            logger.error("[MemoryStore] write error: %s", e)
            return -1

    # ── Read ──────────────────────────────────────────────────────────────────

    def read(self, record_id: int) -> Optional[MemoryRecord]:
        """Fetch a single memory record by ID. Returns None if not found."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                row = conn.execute(
                    "SELECT * FROM memories WHERE id=?", (record_id,)
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE memories SET access_count=access_count+1, "
                        "last_accessed=? WHERE id=?",
                        (_now_iso(), record_id)
                    )
                    return MemoryRecord.from_row(row)
                return None
        except Exception as e:
            logger.error("[MemoryStore] read error: %s", e)
            return None

    def query(
        self,
        layer: Optional[str] = None,
        category: Optional[str] = None,
        project_id: Optional[int] = None,
        persona: Optional[str] = None,
        tags: Optional[list[str]] = None,
        pinned_only: bool = False,
        include_suppressed: bool = False,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        """
        Flexible query against the memories table.
        All filter parameters are optional and ANDed together.
        Returns up to `limit` records ordered by updated_at DESC.
        """
        try:
            from storage.db import get_db
            clauses = []
            params: list = []

            if not include_suppressed:
                clauses.append("suppressed=0")

            if layer is not None:
                clauses.append("layer=?")
                params.append(layer)

            if category is not None:
                clauses.append("category=?")
                params.append(category)

            if project_id is not None:
                clauses.append("(project_id=? OR project_id IS NULL)")
                params.append(project_id)

            if persona is not None:
                clauses.append("(persona=? OR persona IS NULL)")
                params.append(persona)

            if pinned_only:
                clauses.append("pinned=1")

            # Filter out expired
            clauses.append("(expires_at IS NULL OR expires_at > datetime('now'))")

            # Filter out superseded
            clauses.append("superseded_by IS NULL")

            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"SELECT * FROM memories {where} ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            with get_db() as conn:
                rows = conn.execute(sql, params).fetchall()

            records = [MemoryRecord.from_row(r) for r in rows]

            # Post-filter by tags if requested (JSON array match)
            if tags:
                filtered = []
                for r in records:
                    r_tags = r.get_tags()
                    if any(t in r_tags for t in tags):
                        filtered.append(r)
                return filtered

            return records
        except Exception as e:
            logger.error("[MemoryStore] query error: %s", e)
            return []

    def search_by_key(
        self,
        key_pattern: str,
        layer: Optional[str] = None,
    ) -> list[MemoryRecord]:
        """
        Search memories by key pattern (SQL LIKE, % wildcards).
        E.g. search_by_key('user.%') finds all user-namespace keys.
        """
        try:
            from storage.db import get_db
            params: list = [key_pattern]
            sql = (
                "SELECT * FROM memories WHERE key LIKE ? AND suppressed=0 "
                "AND superseded_by IS NULL "
                "AND (expires_at IS NULL OR expires_at > datetime('now'))"
            )
            if layer:
                sql += " AND layer=?"
                params.append(layer)
            sql += " ORDER BY confidence DESC, updated_at DESC LIMIT 100"

            with get_db() as conn:
                rows = conn.execute(sql, params).fetchall()
            return [MemoryRecord.from_row(r) for r in rows]
        except Exception as e:
            logger.error("[MemoryStore] search_by_key error: %s", e)
            return []

    # ── Mutation helpers ──────────────────────────────────────────────────────

    def reinforce(self, record_id: int, confidence_delta: float = 0.05) -> None:
        """Increase a record's confidence and update reinforced_at."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "UPDATE memories SET "
                    "confidence=MIN(1.0, confidence+?), "
                    "reinforced_at=?, updated_at=?, "
                    "access_count=access_count+1 "
                    "WHERE id=?",
                    (confidence_delta, _now_iso(), _now_iso(), record_id)
                )
        except Exception as e:
            logger.error("[MemoryStore] reinforce error: %s", e)

    def supersede(self, old_id: int, new_id: int) -> None:
        """Mark old_id as superseded by new_id."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "UPDATE memories SET superseded_by=?, updated_at=? WHERE id=?",
                    (new_id, _now_iso(), old_id)
                )
        except Exception as e:
            logger.error("[MemoryStore] supersede error: %s", e)

    def pin(self, record_id: int) -> None:
        """Pin a memory record so it is never pruned."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "UPDATE memories SET pinned=1, updated_at=? WHERE id=?",
                    (_now_iso(), record_id)
                )
        except Exception as e:
            logger.error("[MemoryStore] pin error: %s", e)

    def unpin(self, record_id: int) -> None:
        """Unpin a memory record."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "UPDATE memories SET pinned=0, updated_at=? WHERE id=?",
                    (_now_iso(), record_id)
                )
        except Exception as e:
            logger.error("[MemoryStore] unpin error: %s", e)

    def suppress(self, record_id: int) -> None:
        """Soft-delete: mark suppressed=1. Pinned records cannot be suppressed."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "UPDATE memories SET suppressed=1, updated_at=? "
                    "WHERE id=? AND pinned=0",
                    (_now_iso(), record_id)
                )
        except Exception as e:
            logger.error("[MemoryStore] suppress error: %s", e)

    def unsuppress(self, record_id: int) -> None:
        """Un-delete a suppressed record."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "UPDATE memories SET suppressed=0, updated_at=? WHERE id=?",
                    (_now_iso(), record_id)
                )
        except Exception as e:
            logger.error("[MemoryStore] unsuppress error: %s", e)

    # ── Conflict tracking ─────────────────────────────────────────────────────

    def record_conflict(
        self,
        id_a: int,
        id_b: int,
        conflict_type: str = "contradictory_value",
    ) -> None:
        """Log a conflict between two memory records."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                # Check if conflict already logged
                existing = conn.execute(
                    "SELECT id FROM memory_conflicts "
                    "WHERE memory_id_a=? AND memory_id_b=? AND resolved=0",
                    (id_a, id_b)
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO memory_conflicts "
                        "(memory_id_a, memory_id_b, conflict_type) VALUES (?,?,?)",
                        (id_a, id_b, conflict_type)
                    )
        except Exception as e:
            logger.error("[MemoryStore] record_conflict error: %s", e)

    def get_conflicts(self, resolved: bool = False) -> list[ConflictRecord]:
        """Fetch conflict records."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT * FROM memory_conflicts WHERE resolved=? ORDER BY created_at DESC LIMIT 50",
                    (1 if resolved else 0,)
                ).fetchall()
            result = []
            for r in rows:
                result.append(ConflictRecord(
                    id=r["id"],
                    memory_id_a=r["memory_id_a"],
                    memory_id_b=r["memory_id_b"],
                    conflict_type=r["conflict_type"],
                    resolved=r["resolved"],
                    resolution=r["resolution"],
                    created_at=r["created_at"],
                ))
            return result
        except Exception as e:
            logger.error("[MemoryStore] get_conflicts error: %s", e)
            return []

    # ── Pruning ───────────────────────────────────────────────────────────────

    def prune_expired(self) -> int:
        """
        Delete all non-pinned memories where expires_at has passed.
        Returns count of deleted records.
        """
        try:
            from storage.db import get_db
            with get_db() as conn:
                cur = conn.execute(
                    "DELETE FROM memories WHERE pinned=0 AND expires_at IS NOT NULL "
                    "AND expires_at < datetime('now')"
                )
                return cur.rowcount
        except Exception as e:
            logger.error("[MemoryStore] prune_expired error: %s", e)
            return 0

    def prune_layer(self, layer: MemoryLayer, max_records: int) -> int:
        """
        If the layer has more than max_records unpinned records,
        delete the oldest (lowest access_count, oldest updated_at) down to max_records.
        Returns count of deleted records.
        """
        try:
            from storage.db import get_db
            with get_db() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE layer=? AND pinned=0 AND suppressed=0",
                    (layer.value,)
                ).fetchone()[0]

                if total <= max_records:
                    return 0

                excess = total - max_records
                # Delete the least-accessed, oldest records
                cur = conn.execute(
                    "DELETE FROM memories WHERE id IN ("
                    "  SELECT id FROM memories WHERE layer=? AND pinned=0 AND suppressed=0 "
                    "  ORDER BY access_count ASC, updated_at ASC "
                    "  LIMIT ?"
                    ")",
                    (layer.value, excess)
                )
                return cur.rowcount
        except Exception as e:
            logger.error("[MemoryStore] prune_layer error: %s", e)
            return 0

    def prune_superseded(self, days_old: int = 180) -> int:
        """
        Remove superseded, non-pinned records that haven't been accessed in days_old days.
        """
        try:
            from storage.db import get_db
            with get_db() as conn:
                cur = conn.execute(
                    "DELETE FROM memories WHERE pinned=0 AND superseded_by IS NOT NULL "
                    "AND (last_accessed IS NULL OR "
                    "     last_accessed < datetime('now', ?))",
                    (f"-{days_old} days",)
                )
                return cur.rowcount
        except Exception as e:
            logger.error("[MemoryStore] prune_superseded error: %s", e)
            return 0

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return memory table statistics per layer and totals."""
        stats: dict = {}
        try:
            from storage.db import get_db
            with get_db() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE suppressed=0"
                ).fetchone()[0]
                stats["total_active"] = total

                pinned = conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE pinned=1"
                ).fetchone()[0]
                stats["total_pinned"] = pinned

                conflicts = conn.execute(
                    "SELECT COUNT(*) FROM memory_conflicts WHERE resolved=0"
                ).fetchone()[0]
                stats["open_conflicts"] = conflicts

                for layer in MemoryLayer:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM memories WHERE layer=? AND suppressed=0",
                        (layer.value,)
                    ).fetchone()[0]
                    stats[f"layer.{layer.value}"] = count

        except Exception as e:
            logger.error("[MemoryStore] get_stats error: %s", e)
            stats["error"] = str(e)
        return stats
