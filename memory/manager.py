"""
memory/manager.py — MemoryManager: the primary facade for the JARVIS memory subsystem.

All external code should call MemoryManager().remember(), recall(), forget() etc.
This class is a lightweight singleton (created per process, shared via module-level
instance). It delegates to MemoryStore, MemoryRetriever, and MemoryPromoter.

No LLM calls. No GUI imports. Works without Ollama running.
"""
from __future__ import annotations

import json
import logging
import time as _time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from memory.models import (
    MemoryRecord, MemoryLayer, MemoryCategory, MemorySource
)
from memory.store import MemoryStore
from memory.retrieval import MemoryRetriever
from memory.promoter import MemoryPromoter

logger = logging.getLogger(__name__)

# ── Ambient memory categories ─────────────────────────────────────────────────
# Keyword → category mapping used by extract_from_ambient().
MEMORY_CATEGORIES: dict[str, list[str]] = {
    # Personal life
    "health":        ["sick", "pain", "tired", "sleep", "headache", "doctor"],
    "family":        ["dad", "father", "mom", "brother", "sister", "family"],
    "finance":       ["money", "pay", "cost", "invest", "budget", "bank"],
    "goals":         ["want to", "plan to", "going to", "dream", "goal"],
    "education":     ["learn", "study", "read", "understand", "know"],
    "mood":          ["feel", "happy", "sad", "angry", "frustrated", "excited"],
    "ideas":         ["idea", "what if", "could", "maybe", "should we"],
    # Work/security
    "cybersecurity": ["hack", "exploit", "vuln", "CVE", "bug", "scan", "recon"],
    "program":       ["HackerOne", "Bugcrowd", "program", "scope", "target"],
    "finding":       ["found", "discovered", "noticed", "looks like", "seems"],
    # JARVIS-specific
    "preference":    ["jarvis", "i want", "i prefer", "i hate", "i love", "always"],
    "task":          ["remind me", "don't forget", "need to", "todo", "later"],
    "notes":         ["note", "remember", "write this down", "important"],
}

# ── Module-level singleton ────────────────────────────────────────────────────
# Created lazily on first import. Thread-safe for reads; writes use db locking.
_INSTANCE: Optional["MemoryManager"] = None
_SESSION_ID: Optional[str] = None


def _get_session_id() -> str:
    global _SESSION_ID
    if _SESSION_ID is None:
        _SESSION_ID = str(uuid.uuid4())
    return _SESSION_ID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryManager:
    """
    Primary interface to the JARVIS memory subsystem.

    Usage:
        from memory.manager import MemoryManager
        mm = MemoryManager()
        mm.remember("user.name", "Alice", layer="semantic", category="user_fact")
        ctx = mm.recall("what is the user's name?")
    """

    def __init__(self):
        self._store     = MemoryStore()
        self._retriever = MemoryRetriever()
        self._promoter  = MemoryPromoter()

    # ── Core write API ────────────────────────────────────────────────────────

    def remember(
        self,
        key:          str,
        value:        str,
        layer:        str = MemoryLayer.SEMANTIC.value,
        category:     str = MemoryCategory.USER_FACT.value,
        confidence:   float = 1.0,
        source:       str = MemorySource.USER_EXPLICIT.value,
        project_id:   Optional[int] = None,
        persona:      Optional[str] = None,
        tags:         Optional[list[str]] = None,
        pinned:       bool = False,
        expires_days: Optional[int] = None,
    ) -> int:
        """
        Main write entry point.

        Validates inputs, checks for conflicts, handles supersession logic,
        and writes to the store. Returns the memory ID.

        Conflict rule:
        - Same key + same layer → if confidence >= existing: supersede old
        - User explicit always wins over inferred
        - If conflict is irresolvable: write new, record conflict

        Returns -1 on error.
        """
        if not key or not value:
            return -1

        # Enforce minimum confidence for LLM-inferred memories
        if source == MemorySource.LLM_INFERRED.value and confidence < 0.6:
            logger.debug("[MemoryManager] dropped low-confidence inferred memory: %s", key)
            return -1

        # Compute expires_at
        expires_at = None
        if expires_days is not None:
            exp = datetime.now(timezone.utc) + timedelta(days=expires_days)
            expires_at = exp.isoformat()

        provenance = json.dumps({
            "session_id": _get_session_id(),
            "timestamp":  _now_iso(),
            "source":     source,
        })

        record = MemoryRecord(
            key=key[:200],
            value=value[:2000],
            layer=layer,
            category=category,
            source=source,
            confidence=max(0.0, min(1.0, confidence)),
            provenance=provenance,
            project_id=project_id,
            persona=persona,
            tags=json.dumps(tags or []),
            pinned=1 if pinned else 0,
            expires_at=expires_at,
        )

        try:
            new_id = self._store.write(record)

            # Check for existing records with same key to handle conflicts
            existing = self._store.search_by_key(key, layer=layer)
            # Exclude the record we just wrote
            existing = [r for r in existing if r.id != new_id and r.superseded_by is None]

            for old_r in existing:
                if old_r.value == value:
                    # Same value — reinforce, no conflict
                    self._store.reinforce(old_r.id)
                elif source == MemorySource.USER_EXPLICIT.value:
                    # User explicitly corrected — supersede the old one
                    self._store.supersede(old_r.id, new_id)
                elif confidence > float(old_r.confidence or 0.0):
                    # Higher confidence — supersede
                    self._store.supersede(old_r.id, new_id)
                else:
                    # Contradictory with no clear winner — record conflict
                    self._store.record_conflict(old_r.id, new_id, "contradictory_value")

            return new_id

        except Exception as e:
            logger.error("[MemoryManager] remember error: %s", e)
            return -1

    # ── Core recall API ───────────────────────────────────────────────────────

    def recall(
        self,
        query:      str,
        project_id: Optional[int] = None,
        persona:    Optional[str] = None,
        max_tokens: int = 800,
    ) -> str:
        """
        Returns a formatted [MEMORY CONTEXT] block for LLM system prompt injection.
        Returns empty string if no relevant memories exist.
        """
        try:
            return self._retriever.get_context(
                query=query,
                project_id=project_id,
                persona=persona,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error("[MemoryManager] recall error: %s", e)
            return ""

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def forget(self, record_id: int) -> None:
        """
        Soft-delete a memory (mark suppressed=1).
        Pinned memories cannot be forgotten — this is a no-op for them.
        """
        try:
            self._store.suppress(record_id)
        except Exception as e:
            logger.error("[MemoryManager] forget error: %s", e)

    def pin(self, record_id: int) -> None:
        """Pin a memory so it is never pruned or forgotten."""
        try:
            self._store.pin(record_id)
        except Exception as e:
            logger.error("[MemoryManager] pin error: %s", e)

    def unpin(self, record_id: int) -> None:
        """Unpin a memory."""
        try:
            self._store.unpin(record_id)
        except Exception as e:
            logger.error("[MemoryManager] unpin error: %s", e)

    # ── Inspection ────────────────────────────────────────────────────────────

    def inspect(
        self,
        layer:      Optional[str] = None,
        project_id: Optional[int] = None,
        limit:      int = 20,
    ) -> list[dict]:
        """
        Returns a human-readable list of memory records for the inspect_memory tool.
        Each entry is a plain dict.
        """
        try:
            records = self._store.query(
                layer=layer,
                project_id=project_id,
                limit=limit,
            )
            result = []
            for r in records:
                result.append({
                    "id":         r.id,
                    "layer":      r.layer,
                    "category":   r.category,
                    "key":        r.key,
                    "value":      r.value[:200],
                    "confidence": r.confidence,
                    "source":     r.source,
                    "pinned":     bool(r.pinned),
                    "access_count": r.access_count,
                    "expires_at": r.expires_at,
                    "created_at": r.created_at,
                })
            return result
        except Exception as e:
            logger.error("[MemoryManager] inspect error: %s", e)
            return []

    # ── Convenience write wrappers ────────────────────────────────────────────

    def ingest_preference(
        self,
        key:        str,
        value:      str,
        confidence: float = 0.9,
        persona:    Optional[str] = None,
    ) -> int:
        """Write a preference-layer record. Convenience wrapper."""
        return self.remember(
            key=key,
            value=value,
            layer=MemoryLayer.PREFERENCE.value,
            category=MemoryCategory.USER_PREFERENCE.value,
            confidence=confidence,
            source=MemorySource.USER_EXPLICIT.value,
            persona=persona,
        )

    def ingest_project_fact(
        self,
        key:        str,
        value:      str,
        project_id: int,
        confidence: float = 1.0,
    ) -> int:
        """Write a project-layer fact. Convenience wrapper."""
        return self.remember(
            key=key,
            value=value,
            layer=MemoryLayer.PROJECT.value,
            category=MemoryCategory.PROJECT_FACT.value,
            confidence=confidence,
            source=MemorySource.SYSTEM_OBSERVED.value,
            project_id=project_id,
        )

    def ingest_from_message(
        self,
        role:       str,
        content:    str,
        project_id: Optional[int] = None,
    ) -> list[int]:
        """
        Extract and store memories from a conversation message.
        Thin wrapper around MemoryPromoter.ingest_session_message().
        """
        try:
            return self._promoter.ingest_session_message(
                role=role,
                content=content,
                project_id=project_id,
                session_id=self.get_session_id(),
            )
        except Exception as e:
            logger.error("[MemoryManager] ingest_from_message error: %s", e)
            return []

    # ── Stats and hygiene ─────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return memory subsystem statistics."""
        try:
            return self._store.get_stats()
        except Exception as e:
            logger.error("[MemoryManager] get_stats error: %s", e)
            return {"error": str(e)}

    def run_hygiene(self) -> dict:
        """Run full maintenance cycle. Returns stats dict."""
        try:
            return self._promoter.run_hygiene()
        except Exception as e:
            logger.error("[MemoryManager] run_hygiene error: %s", e)
            return {"error": str(e)}

    def get_session_id(self) -> str:
        """Returns the stable session UUID for the current process."""
        return _get_session_id()

    # ── Ambient audio memory extraction ───────────────────────────────────────

    def extract_from_ambient(self, text: str, project_id: Optional[int] = None) -> list:
        """
        Analyze an ambient transcript and extract relevant memories.

        Iterates MEMORY_CATEGORIES; for every category whose keywords appear in
        the text a memory is written to the episodic layer.  If no category
        matches but the utterance is substantial (>8 words) it is stored as an
        uncategorized working-layer note.

        Returns the list of memory keys that were created.
        """
        text_lower = text.lower()
        created: list[str] = []

        for category, keywords in MEMORY_CATEGORIES.items():
            if any(kw in text_lower for kw in keywords):
                key = f"ambient_{category}_{int(_time.time())}"
                try:
                    self.remember(
                        key=key,
                        value=text,
                        layer=MemoryLayer.EPISODIC.value,
                        confidence=0.6,
                        project_id=project_id,
                        tags=[category, "ambient"],
                    )
                except TypeError:
                    # remember() signature mismatch — try minimal call
                    try:
                        self.remember(key=key, value=text)
                    except Exception:
                        pass
                created.append(key)

        # If no category matched but the utterance is substantial, store anyway
        if not created and len(text.split()) > 8:
            key = f"ambient_note_{int(_time.time())}"
            try:
                self.remember(
                    key=key,
                    value=text,
                    layer=MemoryLayer.WORKING.value,
                    confidence=0.4,
                    project_id=project_id,
                    tags=["ambient", "uncategorized"],
                )
            except TypeError:
                try:
                    self.remember(key=key, value=text)
                except Exception:
                    pass
            created.append(key)

        return created
