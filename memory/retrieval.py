"""
memory/retrieval.py — Memory retrieval and ranking for JARVIS.

Fetches relevant memories from the store, scores them by recency/confidence/
project-match/access, and formats them as a compact context block for LLM injection.

No LLM calls. No GUI imports. Works without Ollama running.

EMBEDDING HOOK: keyword_match() uses simple word-overlap scoring. When embeddings
are available in a future phase, replace keyword_match() with a vector similarity
call — the rest of the pipeline does not need to change.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from memory.models import MemoryRecord, MemoryLayer

logger = logging.getLogger(__name__)

# ── Scoring weights ──────────────────────────────────────────────────────────
_W_RECENCY     = 0.4   # recency_score × this
_W_CONFIDENCE  = 0.3   # confidence × this
_W_ACCESS      = 0.1   # normalized access_count × this
_W_PINNED      = 0.5   # flat bonus for pinned records
_W_PROJECT     = 0.2   # bonus when project_id matches
_W_KEYWORD     = 0.3   # keyword overlap bonus

# Max access count used for normalization
_ACCESS_NORM_CAP = 50


class MemoryRetriever:
    """
    Retrieves and ranks memory records for LLM context injection.
    Instantiate fresh per request — no shared state.
    """

    def __init__(self):
        from memory.store import MemoryStore
        self._store = MemoryStore()

    def get_context(
        self,
        query: str,
        project_id: Optional[int] = None,
        persona: Optional[str] = None,
        max_tokens: int = 800,
    ) -> str:
        """
        Primary entry point.
        Returns a formatted [MEMORY CONTEXT]...[/MEMORY CONTEXT] block
        ready for injection into the LLM system prompt.
        Returns empty string if no relevant memories exist.
        """
        try:
            records = self._store.query(
                project_id=project_id,
                persona=persona,
                limit=200,  # fetch generously, then rank and trim
            )
            if not records:
                return ""

            ranked = self.rank(records, query, project_id)
            if not ranked:
                return ""

            # Trim to token budget (rough: 1 token ≈ 4 chars)
            char_budget = max_tokens * 4
            selected = []
            used = 0
            for r in ranked:
                entry = self._format_one(r)
                if used + len(entry) > char_budget:
                    break
                selected.append(r)
                used += len(entry)

            if not selected:
                return ""

            return self.format_for_context(selected)
        except Exception as e:
            logger.error("[MemoryRetriever] get_context error: %s", e)
            return ""

    def rank(
        self,
        records: list[MemoryRecord],
        query: str,
        project_id: Optional[int] = None,
    ) -> list[MemoryRecord]:
        """
        Score and sort records. Higher score = more relevant to this query.
        Suppressed records are excluded. Expired records are excluded.
        """
        scored: list[tuple[float, MemoryRecord]] = []
        for r in records:
            if r.suppressed:
                continue
            if r.is_expired():
                continue
            s = self.score(r, query, project_id)
            scored.append((s, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored]

    def score(
        self,
        record: MemoryRecord,
        query: str,
        project_id: Optional[int] = None,
    ) -> float:
        """
        Full scoring formula:
        score = (recency × W_RECENCY)
              + (confidence × W_CONFIDENCE)
              + (access_normalized × W_ACCESS)
              + (pinned_bonus)
              + (project_match × W_PROJECT)
              + (keyword_overlap × W_KEYWORD)
        """
        recency_score = record.decay_score()
        confidence    = float(record.confidence or 0.0)

        access_normalized = min(
            float(record.access_count or 0) / _ACCESS_NORM_CAP,
            1.0
        )

        pinned_bonus = _W_PINNED if record.pinned else 0.0

        project_bonus = 0.0
        if project_id is not None and record.project_id == project_id:
            project_bonus = _W_PROJECT

        keyword_bonus = 0.0
        if query:
            keyword_bonus = self.keyword_match(record, query) * _W_KEYWORD

        total = (
            (recency_score * _W_RECENCY)
            + (confidence  * _W_CONFIDENCE)
            + (access_normalized * _W_ACCESS)
            + pinned_bonus
            + project_bonus
            + keyword_bonus
        )
        return total

    def keyword_match(self, record: MemoryRecord, query: str) -> float:
        """
        Simple keyword overlap between query and record key+value.
        Returns 0.0–1.0.

        EMBEDDING HOOK: Replace this method with vector cosine similarity
        when embeddings are available. The signature and return type stay the same.
        """
        if not query:
            return 0.0
        try:
            # Tokenize: lowercase words, strip punctuation
            def tokenize(text: str) -> set[str]:
                tokens = re.findall(r'\b[a-z0-9_\.]+\b', text.lower())
                # Filter out very short tokens
                return {t for t in tokens if len(t) > 2}

            query_tokens   = tokenize(query)
            record_tokens  = tokenize(f"{record.key} {record.value}")

            if not query_tokens or not record_tokens:
                return 0.0

            overlap = len(query_tokens & record_tokens)
            score   = overlap / max(len(query_tokens), 1)
            return min(score, 1.0)
        except Exception:
            return 0.0

    def _format_one(self, record: MemoryRecord) -> str:
        """Format a single record as a compact one-line string."""
        layer_label = record.layer.ljust(10)
        conf_str = f"conf={record.confidence:.1f}"
        extras = []
        if record.pinned:
            extras.append("pinned")
        if record.project_id is not None:
            extras.append(f"proj={record.project_id}")
        extra_str = (", " + ", ".join(extras)) if extras else ""
        return f"{layer_label} | {record.key} = {record.value} ({conf_str}{extra_str})"

    def format_for_context(self, records: list[MemoryRecord]) -> str:
        """
        Format a list of ranked records as the [MEMORY CONTEXT] block.

        Example output:
            [MEMORY CONTEXT]
            preference  | user.tts_persona = "ct7567" (conf=0.9, pinned)
            project     | tesla.status = "active, scope defined" (conf=1.0, proj=3)
            semantic    | user.preferred_os = "windows" (conf=1.0)
            [/MEMORY CONTEXT]
        """
        if not records:
            return ""
        lines = ["[MEMORY CONTEXT]"]
        for r in records:
            lines.append(self._format_one(r))
        lines.append("[/MEMORY CONTEXT]")
        return "\n".join(lines)
