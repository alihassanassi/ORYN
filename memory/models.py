"""
memory/models.py — Pure dataclasses for the JARVIS memory subsystem.

No ORM, no GUI imports, no LLM calls. Just data shapes and helpers.
All external code should import from memory.manager, not directly from here.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ── Enumerations ─────────────────────────────────────────────────────────────

class MemoryLayer(str, Enum):
    """Which tier in the memory hierarchy this record lives in."""
    WORKING    = "working"    # transient, per-session — lost on exit unless promoted
    EPISODIC   = "episodic"   # what happened — time-stamped events, decay over days
    SEMANTIC   = "semantic"   # stable world-facts — high confidence, long retention
    PREFERENCE = "preference" # operator behavioral preferences — reinforceable
    PROJECT    = "project"    # per-project state, goals, open threads
    SYSTEM     = "system"     # JARVIS operational state, calibration, mode history


class MemoryCategory(str, Enum):
    """Semantic category for grouping and retrieval."""
    USER_FACT        = "user_fact"        # stable facts about the user/operator
    USER_PREFERENCE  = "user_preference"  # user's stated or inferred preferences
    PROJECT_FACT     = "project_fact"     # facts about a specific project
    TASK_STATE       = "task_state"       # current state of an ongoing task
    RUNTIME          = "runtime"          # JARVIS system state
    INFERRED         = "inferred"         # LLM-inferred, lower trust
    OBSERVATION      = "observation"      # something observed during a session
    CORRECTION       = "correction"       # operator correcting JARVIS


class MemorySource(str, Enum):
    """Who or what created this memory."""
    USER_EXPLICIT    = "user_explicit"    # operator stated it directly (conf=1.0)
    LLM_INFERRED     = "llm_inferred"     # LLM extracted it from conversation
    SYSTEM_OBSERVED  = "system_observed"  # system detected it (tool result, event)
    TOOL_RESULT      = "tool_result"      # output from a tool execution
    PROMOTED         = "promoted"         # promoted from a lower layer


# ── Decay constants by layer (days) ──────────────────────────────────────────
# Lower value = faster decay (shorter memory half-life)
DECAY_CONSTANTS: dict[str, float] = {
    MemoryLayer.WORKING.value:    0.1,
    MemoryLayer.EPISODIC.value:   7.0,
    MemoryLayer.SEMANTIC.value:   180.0,
    MemoryLayer.PREFERENCE.value: 90.0,
    MemoryLayer.PROJECT.value:    30.0,
    MemoryLayer.SYSTEM.value:     14.0,
}


# ── Core dataclasses ─────────────────────────────────────────────────────────

@dataclass
class MemoryRecord:
    """
    Canonical memory record matching the memories table schema.
    All fields are optional at construction except key/value/layer/category/source.
    """
    key:          str
    value:        str
    layer:        str      # MemoryLayer value
    category:     str      # MemoryCategory value
    source:       str      # MemorySource value

    id:            Optional[int]   = None
    confidence:    float           = 1.0
    provenance:    Optional[str]   = None    # JSON: {session_id, message_id, ...}
    project_id:    Optional[int]   = None
    persona:       Optional[str]   = None
    tags:          str             = "[]"    # JSON array of strings
    pinned:        int             = 0
    suppressed:    int             = 0
    access_count:  int             = 0
    last_accessed: Optional[str]   = None
    reinforced_at: Optional[str]   = None
    expires_at:    Optional[str]   = None
    superseded_by: Optional[int]   = None
    created_at:    Optional[str]   = None
    updated_at:    Optional[str]   = None

    # ── Helpers ──────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize to plain dict for storage or JSON output."""
        return {
            "id":            self.id,
            "layer":         self.layer,
            "category":      self.category,
            "key":           self.key,
            "value":         self.value,
            "confidence":    self.confidence,
            "source":        self.source,
            "provenance":    self.provenance,
            "project_id":    self.project_id,
            "persona":       self.persona,
            "tags":          self.tags,
            "pinned":        self.pinned,
            "suppressed":    self.suppressed,
            "access_count":  self.access_count,
            "last_accessed": self.last_accessed,
            "reinforced_at": self.reinforced_at,
            "expires_at":    self.expires_at,
            "superseded_by": self.superseded_by,
            "created_at":    self.created_at,
            "updated_at":    self.updated_at,
        }

    @classmethod
    def from_row(cls, row) -> "MemoryRecord":
        """
        Build a MemoryRecord from a sqlite3.Row or tuple.
        Assumes column order matches the SELECT in store.py.
        """
        d = dict(row)
        return cls(
            id=d.get("id"),
            layer=d.get("layer", MemoryLayer.EPISODIC.value),
            category=d.get("category", MemoryCategory.INFERRED.value),
            key=d.get("key", ""),
            value=d.get("value", ""),
            confidence=float(d.get("confidence") or 1.0),
            source=d.get("source", MemorySource.SYSTEM_OBSERVED.value),
            provenance=d.get("provenance"),
            project_id=d.get("project_id"),
            persona=d.get("persona"),
            tags=d.get("tags") or "[]",
            pinned=int(d.get("pinned") or 0),
            suppressed=int(d.get("suppressed") or 0),
            access_count=int(d.get("access_count") or 0),
            last_accessed=d.get("last_accessed"),
            reinforced_at=d.get("reinforced_at"),
            expires_at=d.get("expires_at"),
            superseded_by=d.get("superseded_by"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )

    def is_expired(self) -> bool:
        """Returns True if expires_at is set and has passed."""
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            now = datetime.now(timezone.utc)
            # Make exp timezone-aware if it isn't
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            return now > exp
        except Exception:
            return False

    def decay_score(self) -> float:
        """
        Returns a recency score in [0.0, 1.0] based on days since last access.
        Uses layer-specific decay constant: score = exp(-days / decay_constant).
        If never accessed, falls back to created_at.
        """
        decay_constant = DECAY_CONSTANTS.get(self.layer, 7.0)
        ref_ts = self.last_accessed or self.created_at
        if not ref_ts:
            return 0.5  # no reference time — neutral score
        try:
            ref = datetime.fromisoformat(ref_ts)
            if ref.tzinfo is None:
                ref = ref.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            days = max(0.0, (now - ref).total_seconds() / 86400.0)
            return math.exp(-days / decay_constant)
        except Exception:
            return 0.5

    def get_tags(self) -> list[str]:
        """Parse tags JSON array into a Python list."""
        try:
            return json.loads(self.tags or "[]")
        except Exception:
            return []

    def has_tag(self, tag: str) -> bool:
        return tag in self.get_tags()


@dataclass
class ConflictRecord:
    """
    Records a conflict between two memory records with the same key.
    Persisted in the memory_conflicts table.
    """
    memory_id_a:   int
    memory_id_b:   int
    conflict_type: str = "contradictory_value"   # or 'duplicate', 'version'
    resolved:      int = 0
    resolution:    Optional[str] = None
    id:            Optional[int] = None
    created_at:    Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "memory_id_a":   self.memory_id_a,
            "memory_id_b":   self.memory_id_b,
            "conflict_type": self.conflict_type,
            "resolved":      self.resolved,
            "resolution":    self.resolution,
            "created_at":    self.created_at,
        }
