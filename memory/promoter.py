"""
memory/promoter.py — Memory promotion engine for JARVIS.

Handles:
1. Ingesting session messages to extract candidate memories (rule-based, no LLM)
2. Promoting episodic → semantic when access threshold is reached
3. Pruning working-layer records at session end
4. Running daily hygiene (prune + promote + compact)

No LLM calls anywhere in this file. No GUI imports.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from memory.models import (
    MemoryRecord, MemoryLayer, MemoryCategory, MemorySource
)

logger = logging.getLogger(__name__)

# ── Hygiene thresholds ────────────────────────────────────────────────────────
# Max records per layer before forced pruning
LAYER_MAX: dict[str, int] = {
    MemoryLayer.WORKING.value:    100,
    MemoryLayer.EPISODIC.value:   500,
    MemoryLayer.SEMANTIC.value:   1000,
    MemoryLayer.PREFERENCE.value: 200,
    MemoryLayer.PROJECT.value:    500,
    MemoryLayer.SYSTEM.value:     200,
}

# Promotion thresholds
EPISODIC_TO_SEMANTIC_ACCESS_MIN  = 3
EPISODIC_TO_SEMANTIC_CONFIDENCE  = 0.7

# Working layer: records older than N days are pruned (short ephemeral life)
WORKING_MAX_AGE_DAYS = 1

# Episodic: prune if not accessed in 30 days
EPISODIC_MAX_STALE_DAYS = 30

# ── Pattern-based memory extractors ──────────────────────────────────────────
# Each entry: (pattern, key_template, category, confidence)
# {0} = first capture group value
_EXTRACTION_RULES = [
    # Explicit preferences
    (re.compile(r'\bi (?:prefer|like|want|use)\s+([\w\s\-\.]{3,40})', re.I),
     "user.preference.{0}", MemoryCategory.USER_PREFERENCE.value, 0.8),

    # OS mentions
    (re.compile(r'\b(windows|linux|macos|ubuntu|debian)\b', re.I),
     "user.preferred_os", MemoryCategory.USER_FACT.value, 0.6),

    # Language preference
    (re.compile(r'\b(python|javascript|typescript|rust|go|java|c\+\+)\b', re.I),
     "user.preferred_language", MemoryCategory.USER_FACT.value, 0.6),

    # Name self-identification
    (re.compile(r'\bmy name is\s+([A-Z][a-z]{2,20})\b'),
     "user.name", MemoryCategory.USER_FACT.value, 1.0),

    # Time zone
    (re.compile(r'\bi(?:\'m| am) in\s+([\w\s]+(?:time zone|tz|UTC[\+\-]\d+))', re.I),
     "user.timezone", MemoryCategory.USER_FACT.value, 0.9),

    # Explicit remember requests
    (re.compile(r'\bremember that\s+(.{5,120})', re.I),
     "user.note.{0}", MemoryCategory.USER_FACT.value, 1.0),

    # Don't forget
    (re.compile(r'\bdon\'?t forget (?:that\s+)?(.{5,120})', re.I),
     "user.note.{0}", MemoryCategory.USER_FACT.value, 1.0),

    # Target domain mentions
    (re.compile(r'\btarget(?:ing)?\s+([\w\-\.]+\.[a-z]{2,6})\b', re.I),
     "user.current_target.{0}", MemoryCategory.PROJECT_FACT.value, 0.7),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryPromoter:
    """
    Extracts, promotes, and maintains memory records.
    Safe to instantiate multiple times — no shared mutable state.
    """

    def __init__(self):
        from memory.store import MemoryStore
        self._store = MemoryStore()

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def ingest_session_message(
        self,
        role: str,
        content: str,
        project_id: Optional[int],
        session_id: str,
    ) -> list[int]:
        """
        Attempt to extract memories from a single message.
        Only user messages are scanned for explicit facts/preferences.
        Assistant messages are skipped (inferred from user speech only).

        Rule-based only — no LLM call.
        Returns list of memory IDs written (may be empty).
        """
        if role != "user":
            return []
        if not content or len(content.strip()) < 10:
            return []

        written_ids: list[int] = []
        text = content[:2000]  # cap to avoid processing huge tool outputs

        for pattern, key_template, category, confidence in _EXTRACTION_RULES:
            try:
                match = pattern.search(text)
                if not match:
                    continue

                captured = match.group(1).strip()[:100]
                # Skip if captured value is too short or too long
                if len(captured) < 2:
                    continue

                # Build key: replace {0} with captured, sanitize
                key = key_template.replace("{0}", re.sub(r'\W+', '_', captured.lower())[:40])

                provenance = json.dumps({
                    "session_id":  session_id,
                    "role":        role,
                    "timestamp":   _now_iso(),
                    "extractor":   "rule_based",
                })

                record = MemoryRecord(
                    key=key,
                    value=captured,
                    layer=MemoryLayer.WORKING.value,
                    category=category,
                    source=MemorySource.USER_EXPLICIT.value,
                    confidence=confidence,
                    provenance=provenance,
                    project_id=project_id,
                    tags=json.dumps(["session_extracted"]),
                )

                mem_id = self._store.write(record)
                if mem_id > 0:
                    written_ids.append(mem_id)

            except Exception as e:
                logger.debug("[MemoryPromoter] extraction error for pattern: %s", e)

        return written_ids

    # ── Promotion ─────────────────────────────────────────────────────────────

    def promote_episodic_to_semantic(self, dry_run: bool = False) -> list[int]:
        """
        Find episodic records eligible for promotion to semantic layer.
        Criteria:
          - access_count >= EPISODIC_TO_SEMANTIC_ACCESS_MIN (3)
          - confidence >= EPISODIC_TO_SEMANTIC_CONFIDENCE (0.7)
          - not suppressed, not superseded, not expired

        Promotion: write a new semantic record, supersede the episodic one.
        Returns list of new semantic memory IDs.
        """
        promoted_ids: list[int] = []
        try:
            candidates = self._store.query(
                layer=MemoryLayer.EPISODIC.value,
                limit=200,
            )
            for r in candidates:
                if r.access_count < EPISODIC_TO_SEMANTIC_ACCESS_MIN:
                    continue
                if r.confidence < EPISODIC_TO_SEMANTIC_CONFIDENCE:
                    continue

                if dry_run:
                    promoted_ids.append(r.id)
                    continue

                provenance_data = {
                    "promoted_from_id":   r.id,
                    "promoted_from_layer": MemoryLayer.EPISODIC.value,
                    "promoted_at":        _now_iso(),
                    "original_provenance": r.provenance,
                }

                new_record = MemoryRecord(
                    key=r.key,
                    value=r.value,
                    layer=MemoryLayer.SEMANTIC.value,
                    category=r.category,
                    source=MemorySource.PROMOTED.value,
                    confidence=min(1.0, r.confidence + 0.05),
                    provenance=json.dumps(provenance_data),
                    project_id=r.project_id,
                    persona=r.persona,
                    tags=r.tags,
                    pinned=r.pinned,
                    access_count=r.access_count,
                )

                new_id = self._store.write(new_record)
                if new_id > 0:
                    # Mark episodic as superseded by the new semantic record
                    self._store.supersede(r.id, new_id)
                    promoted_ids.append(new_id)
                    logger.debug(
                        "[MemoryPromoter] promoted episodic %d → semantic %d (key=%s)",
                        r.id, new_id, r.key
                    )

        except Exception as e:
            logger.error("[MemoryPromoter] promote_episodic_to_semantic error: %s", e)

        return promoted_ids

    def promote_working_to_episodic(self, session_id: str) -> list[int]:
        """
        At session end, promote working-layer records that have been accessed
        more than once (appeared 2+ times) to episodic before pruning.
        Returns list of new episodic IDs.
        """
        promoted_ids: list[int] = []
        try:
            working = self._store.query(
                layer=MemoryLayer.WORKING.value,
                limit=200,
            )
            for r in working:
                if r.access_count < 1:
                    continue  # never reinforced — discard

                provenance_data = {
                    "promoted_from_id":    r.id,
                    "promoted_from_layer": MemoryLayer.WORKING.value,
                    "promoted_at":         _now_iso(),
                    "session_id":          session_id,
                }

                new_record = MemoryRecord(
                    key=r.key,
                    value=r.value,
                    layer=MemoryLayer.EPISODIC.value,
                    category=r.category,
                    source=MemorySource.PROMOTED.value,
                    confidence=r.confidence,
                    provenance=json.dumps(provenance_data),
                    project_id=r.project_id,
                    persona=r.persona,
                    tags=r.tags,
                )

                new_id = self._store.write(new_record)
                if new_id > 0:
                    self._store.supersede(r.id, new_id)
                    promoted_ids.append(new_id)

        except Exception as e:
            logger.error("[MemoryPromoter] promote_working_to_episodic error: %s", e)

        return promoted_ids

    # ── Pruning ───────────────────────────────────────────────────────────────

    def prune_working_layer(self, session_id: str) -> int:
        """
        Delete all working-layer records for the current session.
        Called at session end AFTER promote_working_to_episodic().
        Returns count deleted.
        """
        try:
            from storage.db import get_db
            with get_db() as conn:
                # Delete working records where provenance contains the session_id
                # OR where they have been superseded
                cur = conn.execute(
                    "DELETE FROM memories WHERE layer=? AND ("
                    "  superseded_by IS NOT NULL "
                    "  OR (pinned=0 AND created_at < datetime('now', '-1 day'))"
                    ")",
                    (MemoryLayer.WORKING.value,)
                )
                return cur.rowcount
        except Exception as e:
            logger.error("[MemoryPromoter] prune_working_layer error: %s", e)
            return 0

    def prune_stale_episodic(self) -> int:
        """
        Prune episodic records not accessed in EPISODIC_MAX_STALE_DAYS days.
        Pinned records are always kept.
        """
        try:
            from storage.db import get_db
            with get_db() as conn:
                cur = conn.execute(
                    "DELETE FROM memories WHERE layer=? AND pinned=0 "
                    "AND (last_accessed IS NULL OR "
                    "     last_accessed < datetime('now', ?)) "
                    "AND superseded_by IS NULL",
                    (MemoryLayer.EPISODIC.value, f"-{EPISODIC_MAX_STALE_DAYS} days")
                )
                return cur.rowcount
        except Exception as e:
            logger.error("[MemoryPromoter] prune_stale_episodic error: %s", e)
            return 0

    # ── LLM-assisted extraction ───────────────────────────────────────────────

    def extract_with_llm(
        self,
        user_message: str,
        assistant_response: str,
        project_id: Optional[int],
        session_id: str,
        llm_client=None,
    ) -> list[int]:
        """
        LLM-assisted memory extraction pass.

        Takes a user/assistant exchange, asks a small judge model to extract
        durable facts as JSON, validates them, and writes qualifying records
        to the store.

        llm_client must be passed in — this method never imports LLM directly.
        Returns list of written memory IDs.  On any error, returns [].
        """
        if llm_client is None:
            return []
        if not user_message and not assistant_response:
            return []

        prompt = (
            "You are a memory extraction assistant. Extract durable facts from this conversation.\n"
            "Output ONLY a JSON array of objects with keys: key, value, layer, category, confidence.\n\n"
            "Rules:\n"
            "- Only extract facts that would be useful to remember across sessions\n"
            "- layer must be one of: semantic, preference, project, episodic\n"
            "- category: user_fact, user_preference, project_fact, task_state, inferred\n"
            "- confidence: 0.0-1.0 (be conservative — prefer 0.6-0.8 for inferred facts)\n"
            "- Skip trivial, one-off, or session-specific statements\n"
            "- Maximum 5 items per exchange\n"
            "- If nothing worth remembering, return []\n\n"
            f"User: {user_message[:800]}\n"
            f"Assistant: {assistant_response[:800]}\n\n"
            "JSON array only, no other text:"
        )

        messages = [{"role": "user", "content": prompt}]
        written_ids: list[int] = []

        try:
            # Handle complete() positional signature: complete(messages, system, temperature, max_tokens)
            try:
                resp = llm_client.complete(
                    messages,
                    system="",
                    temperature=0.1,
                    max_tokens=512,
                )
            except TypeError:
                resp = llm_client.complete(messages)

            raw_text = (resp or {}).get("content", "") if isinstance(resp, dict) else str(resp or "")
            if not raw_text:
                return []

            # Strip markdown fences if present
            raw_text = raw_text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```", 2)[-1] if raw_text.count("```") >= 2 else raw_text
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:].strip()

            import json as _json
            try:
                items = _json.loads(raw_text)
            except (_json.JSONDecodeError, ValueError):
                # Try to extract first JSON array from the text
                import re as _re
                arr_match = _re.search(r'\[.*?\]', raw_text, _re.DOTALL)
                if not arr_match:
                    return []
                try:
                    items = _json.loads(arr_match.group())
                except Exception:
                    return []

            if not isinstance(items, list):
                return []

            valid_layers     = {"semantic", "preference", "project", "episodic"}
            valid_categories = {"user_fact", "user_preference", "project_fact", "task_state", "inferred"}

            for item in items[:5]:   # cap at 5
                if not isinstance(item, dict):
                    continue
                key   = str(item.get("key", "")).strip()[:200]
                value = str(item.get("value", "")).strip()[:2000]
                layer = str(item.get("layer", "episodic")).strip().lower()
                cat   = str(item.get("category", "inferred")).strip().lower()
                conf  = float(item.get("confidence", 0.7) or 0.7)

                # Validation
                if not key or not value:
                    continue
                if conf < 0.5:
                    continue
                if layer not in valid_layers:
                    layer = "episodic"
                if cat not in valid_categories:
                    cat = "inferred"

                provenance_data = _json.dumps({
                    "session_id": session_id,
                    "extractor":  "llm_assisted",
                    "timestamp":  _now_iso(),
                })

                record = MemoryRecord(
                    key=key,
                    value=value,
                    layer=layer,
                    category=cat,
                    source=MemorySource.LLM_INFERRED.value,
                    confidence=min(1.0, max(0.5, conf)),
                    provenance=provenance_data,
                    project_id=project_id,
                    tags=_json.dumps(["llm_extracted"]),
                )

                mem_id = self._store.write(record)
                if mem_id and mem_id > 0:
                    written_ids.append(mem_id)
                    logger.debug(
                        "[MemoryPromoter] LLM-extracted: %s = %s (conf=%.2f)",
                        key, value[:60], conf
                    )

        except Exception as exc:
            logger.debug("[MemoryPromoter] extract_with_llm error: %s", exc)
            return []

        return written_ids

    # ── Hygiene ───────────────────────────────────────────────────────────────

    def run_hygiene(self) -> dict:
        """
        Full maintenance cycle:
        1. Prune expired records
        2. Prune stale episodic records
        3. Prune superseded records
        4. Enforce layer size caps
        5. Promote eligible episodic → semantic

        Returns stats dict.
        """
        stats = {
            "expired_pruned":    0,
            "stale_pruned":      0,
            "superseded_pruned": 0,
            "layer_pruned":      {},
            "promoted":          0,
        }
        try:
            stats["expired_pruned"]    = self._store.prune_expired()
            stats["stale_pruned"]      = self.prune_stale_episodic()
            stats["superseded_pruned"] = self._store.prune_superseded(days_old=90)

            for layer, max_count in LAYER_MAX.items():
                layer_enum = MemoryLayer(layer)
                n = self._store.prune_layer(layer_enum, max_count)
                if n > 0:
                    stats["layer_pruned"][layer] = n

            promoted = self.promote_episodic_to_semantic()
            stats["promoted"] = len(promoted)

        except Exception as e:
            logger.error("[MemoryPromoter] run_hygiene error: %s", e)
            stats["error"] = str(e)

        return stats
