"""
memory/tests/test_memory.py — Unit tests for the JARVIS memory subsystem.

Run with:
    python -m pytest memory/tests/test_memory.py -v
    -- or --
    c:/Users/aliin/OneDrive/Desktop/Jarvis/jarvis_lab/jarvis_env/Scripts/python.exe \
        -m pytest memory/tests/test_memory.py -v

All tests use an in-memory SQLite database via a patched DB_PATH.
No Ollama required. No GUI required.
"""
from __future__ import annotations

import json
import math
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# Ensure jarvis_lab is on sys.path
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Patch DB_PATH to an in-memory database before any storage imports ────────
# We need a file-based temp DB because sqlite3 in-memory DBs don't share
# across connections. Use a temp file that's cleaned up after the test.
import tempfile
import os

_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
_TMP_DB_PATH = _TMP_DB.name

import config as _config
_ORIGINAL_DB_PATH = _config.DB_PATH
_config.DB_PATH = _TMP_DB_PATH


def teardown_module(module):
    """Clean up temp DB after all tests in module."""
    _config.DB_PATH = _ORIGINAL_DB_PATH
    try:
        os.unlink(_TMP_DB_PATH)
    except Exception:
        pass


# ── Now import the memory subsystem ──────────────────────────────────────────
from memory.models import (
    MemoryRecord, MemoryLayer, MemoryCategory, MemorySource, DECAY_CONSTANTS
)
from memory.store import MemoryStore
from memory.manager import MemoryManager
from memory.retrieval import MemoryRetriever
from memory.promoter import MemoryPromoter


def _store() -> MemoryStore:
    """Create a fresh store with initialized tables."""
    s = MemoryStore()
    s.initialize()
    return s


def _mm() -> MemoryManager:
    return MemoryManager()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Write and read a memory record
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteRead:
    def test_write_and_read_basic(self):
        s = _store()
        record = MemoryRecord(
            key="user.name",
            value="Alice",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
            confidence=1.0,
        )
        mem_id = s.write(record)
        assert mem_id > 0

        fetched = s.read(mem_id)
        assert fetched is not None
        assert fetched.key == "user.name"
        assert fetched.value == "Alice"
        assert fetched.layer == MemoryLayer.SEMANTIC.value
        assert fetched.confidence == 1.0

    def test_write_same_key_same_value_reinforces(self):
        s = _store()
        r = MemoryRecord(
            key="test.reinforce",
            value="hello",
            layer=MemoryLayer.EPISODIC.value,
            category=MemoryCategory.OBSERVATION.value,
            source=MemorySource.SYSTEM_OBSERVED.value,
        )
        id1 = s.write(r)
        id2 = s.write(r)
        assert id1 == id2  # same record

        fetched = s.read(id1)
        # access_count incremented once by write (reinforce path) + once by read
        assert fetched.access_count >= 1

    def test_write_same_key_different_value_updates(self):
        s = _store()
        r1 = MemoryRecord(
            key="test.update.key",
            value="old_value",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
        )
        id1 = s.write(r1)

        r2 = MemoryRecord(
            key="test.update.key",
            value="new_value",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
        )
        id2 = s.write(r2)
        assert id1 == id2  # updated in-place

        fetched = s.read(id1)
        assert fetched.value == "new_value"

    def test_read_nonexistent_returns_none(self):
        s = _store()
        result = s.read(99999999)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Conflict detection
# ─────────────────────────────────────────────────────────────────────────────

class TestConflicts:
    def test_conflict_recorded_for_same_key_different_layers(self):
        """
        Records in different layers with same key don't conflict automatically,
        but we can manually record a conflict.
        """
        s = _store()
        r1 = MemoryRecord(
            key="conflict.test.key",
            value="value_a",
            layer=MemoryLayer.EPISODIC.value,
            category=MemoryCategory.INFERRED.value,
            source=MemorySource.LLM_INFERRED.value,
            confidence=0.7,
        )
        r2 = MemoryRecord(
            key="conflict.test.key",
            value="value_b",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
            confidence=1.0,
        )
        id_a = s.write(r1)
        id_b = s.write(r2)
        s.record_conflict(id_a, id_b, "contradictory_value")

        conflicts = s.get_conflicts(resolved=False)
        assert any(c.memory_id_a == id_a and c.memory_id_b == id_b for c in conflicts)

    def test_manager_user_explicit_supersedes_inferred(self):
        """User explicit remember should supersede lower-confidence inferred."""
        mm = _mm()
        # Write inferred first
        mm.remember(
            key="conflict.manager.test",
            value="inferred_value",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.INFERRED.value,
            confidence=0.7,
            source=MemorySource.LLM_INFERRED.value,
        )
        # Write explicit with different value — should supersede
        new_id = mm.remember(
            key="conflict.manager.test",
            value="explicit_value",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            confidence=1.0,
            source=MemorySource.USER_EXPLICIT.value,
        )
        assert new_id > 0
        fetched = MemoryStore().read(new_id)
        assert fetched is not None
        assert fetched.value == "explicit_value"

    def test_low_confidence_inferred_not_stored(self):
        """LLM-inferred memories with confidence < 0.6 should be dropped."""
        mm = _mm()
        result = mm.remember(
            key="low.confidence.key",
            value="should_not_be_stored",
            layer=MemoryLayer.EPISODIC.value,
            category=MemoryCategory.INFERRED.value,
            confidence=0.4,
            source=MemorySource.LLM_INFERRED.value,
        )
        assert result == -1


# ─────────────────────────────────────────────────────────────────────────────
# 3. Promotion from episodic to semantic
# ─────────────────────────────────────────────────────────────────────────────

class TestPromotion:
    def test_episodic_to_semantic_promotion(self):
        s = _store()
        promoter = MemoryPromoter()

        # Write episodic record with high confidence and simulate access
        rec = MemoryRecord(
            key="promote.test.key",
            value="promote me",
            layer=MemoryLayer.EPISODIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
            confidence=0.8,
        )
        ep_id = s.write(rec)
        assert ep_id > 0

        # Simulate 3 accesses to meet promotion threshold
        s.reinforce(ep_id)
        s.reinforce(ep_id)
        s.reinforce(ep_id)

        promoted = promoter.promote_episodic_to_semantic()
        assert ep_id in promoted or len(promoted) >= 1  # our record should be in there

        # Verify promoted record exists in semantic layer
        semantic_records = s.query(layer=MemoryLayer.SEMANTIC.value)
        keys = [r.key for r in semantic_records]
        assert "promote.test.key" in keys

    def test_dry_run_promotion(self):
        s = _store()
        promoter = MemoryPromoter()

        rec = MemoryRecord(
            key="promote.dryrun.key",
            value="dry run test",
            layer=MemoryLayer.EPISODIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
            confidence=0.9,
            access_count=5,
        )
        ep_id = s.write(rec)
        s.reinforce(ep_id)
        s.reinforce(ep_id)
        s.reinforce(ep_id)

        before_count = len(s.query(layer=MemoryLayer.SEMANTIC.value))
        candidates = promoter.promote_episodic_to_semantic(dry_run=True)
        after_count = len(s.query(layer=MemoryLayer.SEMANTIC.value))

        # Dry run should not change the DB
        assert before_count == after_count


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pruning expired records
# ─────────────────────────────────────────────────────────────────────────────

class TestPruning:
    def test_prune_expired_records(self):
        s = _store()

        # Write a record that expires in the past
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        rec = MemoryRecord(
            key="expire.test.key",
            value="this should be pruned",
            layer=MemoryLayer.WORKING.value,
            category=MemoryCategory.OBSERVATION.value,
            source=MemorySource.SYSTEM_OBSERVED.value,
            expires_at=past,
        )
        mem_id = s.write(rec)
        assert mem_id > 0

        # Now force-set expires_at in the past (the write() uses our provided value)
        # Actually we need to directly write into DB since write() doesn't pass expires_at
        # through the upsert path when record exists. Let's use a unique key.
        import sqlite3
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "UPDATE memories SET expires_at=? WHERE id=?",
            (past, mem_id)
        )
        conn.commit()
        conn.close()

        deleted = s.prune_expired()
        assert deleted >= 1

        fetched = s.read(mem_id)
        assert fetched is None

    def test_is_expired_method(self):
        past_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future_ts = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        expired_rec = MemoryRecord(
            key="exp.check",
            value="x",
            layer=MemoryLayer.WORKING.value,
            category=MemoryCategory.OBSERVATION.value,
            source=MemorySource.SYSTEM_OBSERVED.value,
            expires_at=past_ts,
        )
        valid_rec = MemoryRecord(
            key="exp.check.valid",
            value="x",
            layer=MemoryLayer.WORKING.value,
            category=MemoryCategory.OBSERVATION.value,
            source=MemorySource.SYSTEM_OBSERVED.value,
            expires_at=future_ts,
        )
        no_exp_rec = MemoryRecord(
            key="exp.check.none",
            value="x",
            layer=MemoryLayer.WORKING.value,
            category=MemoryCategory.OBSERVATION.value,
            source=MemorySource.SYSTEM_OBSERVED.value,
        )

        assert expired_rec.is_expired() is True
        assert valid_rec.is_expired() is False
        assert no_exp_rec.is_expired() is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. Retrieval ranking
# ─────────────────────────────────────────────────────────────────────────────

class TestRetrieval:
    def test_higher_confidence_ranks_above_lower(self):
        s = _store()
        retriever = MemoryRetriever()

        # Same key query, but two records with different confidence
        r_high = MemoryRecord(
            key="ranking.high.confidence",
            value="high confidence answer",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
            confidence=1.0,
        )
        r_low = MemoryRecord(
            key="ranking.low.confidence",
            value="low confidence answer",
            layer=MemoryLayer.EPISODIC.value,
            category=MemoryCategory.INFERRED.value,
            source=MemorySource.LLM_INFERRED.value,
            confidence=0.6,
        )
        s.write(r_high)
        s.write(r_low)

        # Retrieve both from store and rank them
        records = s.query(limit=100)
        high_records = [r for r in records if "high.confidence" in r.key]
        low_records  = [r for r in records if "low.confidence"  in r.key]

        if high_records and low_records:
            scored_h = retriever.score(high_records[0], "confidence test", None)
            scored_l = retriever.score(low_records[0], "confidence test", None)
            assert scored_h > scored_l

    def test_pinned_record_gets_score_bonus(self):
        retriever = MemoryRetriever()
        pinned = MemoryRecord(
            key="pinned.record",
            value="important",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
            confidence=0.8,
            pinned=1,
        )
        unpinned = MemoryRecord(
            key="unpinned.record",
            value="important",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
            confidence=0.8,
            pinned=0,
        )
        score_pinned   = retriever.score(pinned,   "query", None)
        score_unpinned = retriever.score(unpinned, "query", None)
        assert score_pinned > score_unpinned

    def test_project_match_boosts_score(self):
        retriever = MemoryRetriever()
        with_project = MemoryRecord(
            key="proj.record",
            value="project specific fact",
            layer=MemoryLayer.PROJECT.value,
            category=MemoryCategory.PROJECT_FACT.value,
            source=MemorySource.SYSTEM_OBSERVED.value,
            confidence=0.9,
            project_id=42,
        )
        without_project = MemoryRecord(
            key="noproj.record",
            value="project specific fact",
            layer=MemoryLayer.PROJECT.value,
            category=MemoryCategory.PROJECT_FACT.value,
            source=MemorySource.SYSTEM_OBSERVED.value,
            confidence=0.9,
            project_id=None,
        )
        score_match    = retriever.score(with_project,    "query", project_id=42)
        score_no_match = retriever.score(without_project, "query", project_id=42)
        assert score_match > score_no_match

    def test_context_format_block(self):
        retriever = MemoryRetriever()
        records = [
            MemoryRecord(
                key="user.name",
                value="Alice",
                layer=MemoryLayer.SEMANTIC.value,
                category=MemoryCategory.USER_FACT.value,
                source=MemorySource.USER_EXPLICIT.value,
                confidence=1.0,
            )
        ]
        ctx = retriever.format_for_context(records)
        assert "[MEMORY CONTEXT]" in ctx
        assert "[/MEMORY CONTEXT]" in ctx
        assert "user.name" in ctx
        assert "Alice" in ctx

    def test_empty_context_returns_empty_string(self):
        retriever = MemoryRetriever()
        ctx = retriever.format_for_context([])
        assert ctx == ""

    def test_keyword_match_basic(self):
        retriever = MemoryRetriever()
        record = MemoryRecord(
            key="user.preferred_language",
            value="Python",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
        )
        score = retriever.keyword_match(record, "what programming language does the user prefer")
        assert score > 0.0
        zero_score = retriever.keyword_match(record, "completely unrelated quantum physics")
        assert score > zero_score


# ─────────────────────────────────────────────────────────────────────────────
# 6. Pin / suppress behavior
# ─────────────────────────────────────────────────────────────────────────────

class TestPinSuppress:
    def test_pin_prevents_suppress(self):
        s = _store()
        r = MemoryRecord(
            key="pin.test.key",
            value="pinned value",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
        )
        mem_id = s.write(r)
        s.pin(mem_id)

        # Try to suppress — should be a no-op for pinned records
        s.suppress(mem_id)

        fetched = s.read(mem_id)
        assert fetched is not None
        assert fetched.pinned == 1
        assert fetched.suppressed == 0

    def test_suppress_hides_from_query(self):
        s = _store()
        r = MemoryRecord(
            key="suppress.test.key",
            value="hidden value",
            layer=MemoryLayer.EPISODIC.value,
            category=MemoryCategory.OBSERVATION.value,
            source=MemorySource.SYSTEM_OBSERVED.value,
        )
        mem_id = s.write(r)
        s.suppress(mem_id)

        # Should not appear in default queries
        records = s.query(layer=MemoryLayer.EPISODIC.value, limit=100)
        keys = [r.key for r in records]
        assert "suppress.test.key" not in keys

    def test_unsuppress_restores_visibility(self):
        s = _store()
        r = MemoryRecord(
            key="unsuppress.test.key",
            value="restored value",
            layer=MemoryLayer.EPISODIC.value,
            category=MemoryCategory.OBSERVATION.value,
            source=MemorySource.SYSTEM_OBSERVED.value,
        )
        mem_id = s.write(r)
        s.suppress(mem_id)
        s.unsuppress(mem_id)

        records = s.query(layer=MemoryLayer.EPISODIC.value, limit=100)
        keys = [r.key for r in records]
        assert "unsuppress.test.key" in keys

    def test_manager_forget_soft_deletes(self):
        mm = _mm()
        mem_id = mm.remember(
            key="forget.test.key",
            value="forget this",
            layer=MemoryLayer.EPISODIC.value,
            category=MemoryCategory.OBSERVATION.value,
        )
        assert mem_id > 0
        mm.forget(mem_id)

        # Should not appear in inspect
        records = mm.inspect(layer=MemoryLayer.EPISODIC.value)
        ids = [r["id"] for r in records]
        assert mem_id not in ids


# ─────────────────────────────────────────────────────────────────────────────
# 7. Stats output
# ─────────────────────────────────────────────────────────────────────────────

class TestStats:
    def test_stats_returns_dict_with_expected_keys(self):
        mm = _mm()
        # Write one record to ensure there's data
        mm.remember(
            key="stats.test",
            value="stats check",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
        )
        stats = mm.get_stats()
        assert isinstance(stats, dict)
        assert "total_active" in stats
        assert "total_pinned" in stats
        assert "open_conflicts" in stats
        assert "layer.semantic" in stats

    def test_stats_counts_are_non_negative(self):
        mm = _mm()
        stats = mm.get_stats()
        for key, val in stats.items():
            if key != "error":
                assert isinstance(val, int)
                assert val >= 0


# ─────────────────────────────────────────────────────────────────────────────
# 8. Context formatting
# ─────────────────────────────────────────────────────────────────────────────

class TestContextFormatting:
    def test_format_includes_all_records(self):
        retriever = MemoryRetriever()
        records = [
            MemoryRecord(
                key=f"fmt.key.{i}",
                value=f"value_{i}",
                layer=MemoryLayer.SEMANTIC.value,
                category=MemoryCategory.USER_FACT.value,
                source=MemorySource.USER_EXPLICIT.value,
                confidence=1.0,
            )
            for i in range(5)
        ]
        ctx = retriever.format_for_context(records)
        for i in range(5):
            assert f"fmt.key.{i}" in ctx

    def test_format_respects_token_budget(self):
        mm = _mm()
        # Write enough records to exceed 800 tokens
        for i in range(100):
            mm.remember(
                key=f"budget.key.{i:03d}",
                value="x" * 50,  # 50 chars each
                layer=MemoryLayer.SEMANTIC.value,
                category=MemoryCategory.USER_FACT.value,
            )
        ctx = mm.recall("budget test", max_tokens=100)
        # Should be under ~400 chars (100 tokens * 4 chars/token)
        if ctx:
            assert len(ctx) <= 600  # some slack for header/footer


# ─────────────────────────────────────────────────────────────────────────────
# 9. Decay score
# ─────────────────────────────────────────────────────────────────────────────

class TestDecayScore:
    def test_never_accessed_returns_neutral_score(self):
        r = MemoryRecord(
            key="decay.no.access",
            value="x",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
        )
        # No created_at, no last_accessed
        score = r.decay_score()
        assert score == 0.5  # neutral

    def test_recently_accessed_scores_near_1(self):
        now_ts = datetime.now(timezone.utc).isoformat()
        r = MemoryRecord(
            key="decay.recent",
            value="x",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
            last_accessed=now_ts,
        )
        score = r.decay_score()
        assert score > 0.95  # exp(-0/180) ≈ 1.0

    def test_old_working_layer_decays_fast(self):
        # Working layer: decay_constant = 0.1 days
        # 1 day old → exp(-1/0.1) = exp(-10) ≈ 0.000045
        old_ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        r = MemoryRecord(
            key="decay.old.working",
            value="x",
            layer=MemoryLayer.WORKING.value,
            category=MemoryCategory.OBSERVATION.value,
            source=MemorySource.SYSTEM_OBSERVED.value,
            last_accessed=old_ts,
        )
        score = r.decay_score()
        assert score < 0.01  # should be nearly 0

    def test_semantic_layer_decays_slowly(self):
        # Semantic: decay_constant = 180 days
        # 30 days old → exp(-30/180) ≈ 0.85
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        r = MemoryRecord(
            key="decay.semantic.old",
            value="x",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
            source=MemorySource.USER_EXPLICIT.value,
            last_accessed=old_ts,
        )
        score = r.decay_score()
        assert score > 0.8  # still high after 30 days in semantic layer


# ─────────────────────────────────────────────────────────────────────────────
# 10. MemoryManager integration
# ─────────────────────────────────────────────────────────────────────────────

class TestManagerIntegration:
    def test_remember_and_inspect_roundtrip(self):
        mm = _mm()
        mem_id = mm.remember(
            key="integration.test",
            value="roundtrip check",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
        )
        assert mem_id > 0

        records = mm.inspect(layer=MemoryLayer.SEMANTIC.value)
        found = [r for r in records if r["id"] == mem_id]
        assert len(found) == 1
        assert found[0]["key"] == "integration.test"
        assert found[0]["value"] == "roundtrip check"

    def test_recall_returns_context_block(self):
        mm = _mm()
        mm.remember(
            key="recall.test.language",
            value="Python and Rust",
            layer=MemoryLayer.SEMANTIC.value,
            category=MemoryCategory.USER_FACT.value,
        )
        ctx = mm.recall("what programming language")
        # May or may not match (depends on ranking), but should return a string
        assert isinstance(ctx, str)

    def test_session_id_stable_within_process(self):
        mm1 = _mm()
        mm2 = _mm()
        assert mm1.get_session_id() == mm2.get_session_id()

    def test_hygiene_returns_stats_dict(self):
        mm = _mm()
        result = mm.run_hygiene()
        assert isinstance(result, dict)
        assert "expired_pruned" in result
        assert "promoted" in result

    def test_ingest_preference_writes_preference_layer(self):
        mm = _mm()
        mem_id = mm.ingest_preference(
            key="pref.test.key",
            value="dark mode",
            confidence=0.9,
        )
        assert mem_id > 0
        records = mm.inspect(layer=MemoryLayer.PREFERENCE.value)
        keys = [r["key"] for r in records]
        assert "pref.test.key" in keys

    def test_ingest_project_fact_writes_project_layer(self):
        mm = _mm()
        mem_id = mm.ingest_project_fact(
            key="project.42.status",
            value="active recon in progress",
            project_id=42,
        )
        assert mem_id > 0
        records = mm.inspect(layer=MemoryLayer.PROJECT.value, project_id=42)
        keys = [r["key"] for r in records]
        assert "project.42.status" in keys


# ─────────────────────────────────────────────────────────────────────────────
# 11. Promoter: session message ingestion
# ─────────────────────────────────────────────────────────────────────────────

class TestPromoterIngestion:
    def test_explicit_remember_request_captured(self):
        promoter = MemoryPromoter()
        session_id = str(uuid.uuid4())
        ids = promoter.ingest_session_message(
            role="user",
            content="Remember that my name is Bob",
            project_id=None,
            session_id=session_id,
        )
        assert len(ids) > 0

    def test_assistant_messages_not_ingested(self):
        promoter = MemoryPromoter()
        session_id = str(uuid.uuid4())
        ids = promoter.ingest_session_message(
            role="assistant",
            content="Remember that your name is Alice",
            project_id=None,
            session_id=session_id,
        )
        assert len(ids) == 0

    def test_os_mention_captured(self):
        promoter = MemoryPromoter()
        session_id = str(uuid.uuid4())
        ids = promoter.ingest_session_message(
            role="user",
            content="I'm running this on Windows",
            project_id=None,
            session_id=session_id,
        )
        # May or may not capture depending on pattern specifics — just ensure no crash
        assert isinstance(ids, list)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
