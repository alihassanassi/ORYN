# JARVIS Memory Subsystem — Architecture Document

**Phase 2 implementation. Written 2026-03-17.**

---

## 1. Pre-Implementation Audit Findings

### What existed before this subsystem

| Component | What it stored | Where |
|-----------|---------------|-------|
| `storage/companion_db.py` | Skill level observations (domain→delta float), persona preferences (key/value per persona) | `companion_skills`, `companion_preferences` tables in `jarvis.db` |
| `storage/db.py` | Chat messages (`messages`), project notes (`projects.notes`), command log | `jarvis.db` |
| `storage/settings_store.py` | Mutable operator settings (audio, display, behaviour, window geometry) | `jarvis_settings.json` |
| `autonomy/preference_engine.py` | Tool approval counts (approved_count, rejected_count per tool name) | `jarvis_preferences` table |
| `agents/worker.py` | Per-turn prior_history (in-memory only, from GUI) | None — transient |

**Gap:** No structured, ranked, multi-layer long-term memory existed. Preferences were tool-approval ratios only. There was no recall/retrieval mechanism for facts the operator had stated across sessions.

**Overlap risk:** The new `memories` table is distinct from `companion_preferences`. `companion_preferences` stores per-persona settings tuned by companion_db. The memory subsystem stores semantic facts, preferences, project state, and episodic observations. There is intentional functional separation.

---

## 2. Memory Layer Definitions

### Layer 1 — Working (transient, per-session)

- **Purpose:** Buffers extracted facts from the current session before promotion.
- **Lifecycle:** Created during a session, promoted or pruned at session end.
- **Decay constant:** 0.1 days (very fast — nearly gone in 6 hours if not accessed)
- **Max records:** 100
- **Writer:** `MemoryPromoter.ingest_session_message()` (rule-based extraction)

### Layer 2 — Episodic ("what happened")

- **Purpose:** Time-stamped events and observations. Decays over weeks.
- **Lifecycle:** Written when something notable occurs; promoted to semantic if accessed ≥3 times with confidence ≥0.7.
- **Decay constant:** 7 days
- **Max records:** 500
- **Retention:** 30 days if access_count=0 and not pinned
- **Writer:** System, promoter, tool results

### Layer 3 — Semantic (stable world-facts)

- **Purpose:** High-confidence, stable facts about the user, projects, the world.
- **Lifecycle:** Written explicitly or promoted from episodic. Long retention.
- **Decay constant:** 180 days
- **Max records:** 1000
- **Retention:** Permanent unless superseded and not accessed for 180 days
- **Writer:** Operator explicit, LLM inferred (confidence ≥0.6), promoter

### Layer 4 — Preference (operator behavioral model)

- **Purpose:** What the operator prefers, how they like things done.
- **Lifecycle:** Written on explicit statement or inferred from patterns. Reinforceable.
- **Decay constant:** 90 days
- **Max records:** 200
- **Writer:** Operator explicit, `ingest_preference()`

### Layer 5 — Project (per-project state)

- **Purpose:** Goals, constraints, decisions, open threads for a specific project.
- **Lifecycle:** Written when project state changes. Linked to `projects.id` via FK.
- **Decay constant:** 30 days
- **Max records:** 500
- **Writer:** `ingest_project_fact()`, tool results, system observations

### Layer 6 — System (JARVIS operational state)

- **Purpose:** JARVIS mode history, calibration, operational decisions.
- **Lifecycle:** Written by JARVIS internals.
- **Decay constant:** 14 days
- **Max records:** 200
- **Writer:** System only

---

## 3. SQLite Schema

### `memories` table

```sql
CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    layer         TEXT NOT NULL,          -- MemoryLayer values
    category      TEXT NOT NULL,          -- MemoryCategory values
    key           TEXT NOT NULL,          -- semantic label, dot-namespaced
    value         TEXT NOT NULL,          -- content (plain text or JSON)
    confidence    REAL DEFAULT 1.0,       -- 0.0–1.0
    source        TEXT NOT NULL,          -- MemorySource values
    provenance    TEXT,                   -- JSON: {session_id, timestamp, ...}
    project_id    INTEGER,                -- FK to projects (nullable)
    persona       TEXT,                   -- null = global; name = persona-specific
    tags          TEXT DEFAULT '[]',      -- JSON string array
    pinned        INTEGER DEFAULT 0,      -- 1 = never pruned
    suppressed    INTEGER DEFAULT 0,      -- 1 = soft-deleted
    access_count  INTEGER DEFAULT 0,      -- reinforcement signal
    last_accessed TEXT,                   -- ISO timestamp
    reinforced_at TEXT,                   -- last time confirmed/strengthened
    expires_at    TEXT,                   -- NULL = permanent; ISO = auto-expire
    superseded_by INTEGER,                -- FK to newer memory record
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);
```

### `memory_conflicts` table

```sql
CREATE TABLE IF NOT EXISTS memory_conflicts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id_a   INTEGER NOT NULL,
    memory_id_b   INTEGER NOT NULL,
    conflict_type TEXT,          -- 'contradictory_value' | 'duplicate' | 'version'
    resolved      INTEGER DEFAULT 0,
    resolution    TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);
```

### Indexes

```sql
CREATE INDEX idx_memories_layer      ON memories(layer);
CREATE INDEX idx_memories_key        ON memories(key);
CREATE INDEX idx_memories_project    ON memories(project_id);
CREATE INDEX idx_memories_layer_key  ON memories(layer, key);
CREATE INDEX idx_memories_suppressed ON memories(suppressed);
```

---

## 4. Retention Policies

| Layer      | Max Records | Stale TTL           | Pinned Override |
|------------|-------------|---------------------|-----------------|
| working    | 100         | 1 day               | Exempt from prune |
| episodic   | 500         | 30 days no-access   | Exempt |
| semantic   | 1000        | 180 days superseded | Exempt |
| preference | 200         | Never (only by hygiene cap) | Exempt |
| project    | 500         | Hygiene cap only    | Exempt |
| system     | 200         | Hygiene cap only    | Exempt |

Total hard limit: 10,000 records triggers forced compaction (not implemented in Phase 2 — at 2,700 max across all layers this is not a risk yet).

---

## 5. Promotion Rules

```
Working → Episodic:
  - access_count >= 1 (accessed at least once during session)
  - Called: MemoryPromoter.promote_working_to_episodic(session_id)
  - Trigger: session end

Episodic → Semantic:
  - access_count >= 3 (EPISODIC_TO_SEMANTIC_ACCESS_MIN)
  - confidence >= 0.7 (EPISODIC_TO_SEMANTIC_CONFIDENCE)
  - not suppressed, not superseded, not expired
  - Called: MemoryPromoter.promote_episodic_to_semantic()
  - Trigger: hygiene cycle (daily)

Any layer → Preference:
  - Use MemoryManager.ingest_preference() directly
  - Trigger: operator explicit statement

Promotion mechanics:
  - New record written in target layer
  - Old record marked superseded_by = new_id
  - Confidence slightly boosted (+0.05) on promotion
```

---

## 6. Retrieval Ranking Formula

```
score(r, query, project_id) =
    (decay_score(r) × 0.4)
  + (confidence(r) × 0.3)
  + (min(access_count/50, 1.0) × 0.1)
  + (0.5 if pinned else 0.0)
  + (0.2 if project_id matches r.project_id else 0.0)
  + (keyword_overlap(r, query) × 0.3)

decay_score(r) = exp(-days_since_access / decay_constant[r.layer])

Decay constants (days):
  working=0.1, episodic=7, semantic=180, preference=90, project=30, system=14
```

**Embedding hook:** `MemoryRetriever.keyword_match()` uses simple word-overlap scoring. Replace this method with vector cosine similarity when embeddings are available — the scoring pipeline is unchanged.

---

## 7. Conflict Resolution Rules

| Situation | Resolution |
|-----------|-----------|
| Same key + same layer + same value | Reinforce (bump access_count, no duplicate) |
| Same key + same layer + different value + user_explicit wins | Supersede old record |
| Same key + same layer + higher confidence wins | Supersede old record |
| Same key + same layer + contradictory, no clear winner | Write both, record in `memory_conflicts` |
| LLM inferred, confidence < 0.6 | Dropped silently at MemoryManager.remember() |
| User explicit always | Wins against any inferred record |

---

## 8. Hygiene Rules

Triggered by `MemoryManager.run_hygiene()` (called by `tool_memory_hygiene`).

1. `prune_expired()` — delete records where `expires_at < now()` and `pinned=0`
2. `prune_stale_episodic()` — delete episodic records not accessed in 30 days, not pinned
3. `prune_superseded(days_old=90)` — remove superseded records not accessed in 90 days
4. `prune_layer()` per layer — enforce max record caps
5. `promote_episodic_to_semantic()` — promote eligible episodic records

Recommended: run hygiene once per day via a scheduled task or on JARVIS startup.

---

## 9. Tool Interface Summary

| Tool | Description |
|------|-------------|
| `remember(key, value, layer, category, confidence, project_id, pinned, expires_days)` | Write a memory record explicitly |
| `recall(query, project_id)` | Retrieve relevant memories as formatted context |
| `forget(memory_id)` | Soft-delete a memory (suppressed=1); pinned memories immune |
| `pin_memory(memory_id)` | Pin a memory so it's never pruned |
| `inspect_memory(layer, project_id, limit)` | List memory records, optionally filtered |
| `memory_stats()` | Show record counts per layer, pinned count, open conflicts |
| `memory_hygiene()` | Run full maintenance cycle |

All tools are registered in `tools/registry.py` and guarded by `_MEMORY_AVAILABLE` flag so the system degrades gracefully if the memory package fails to import.

---

## 10. Integration Points

### `agents/worker.py` — `_run_inner()`

**Before LLM call:**
```python
# Memory context injection
from memory.manager import MemoryManager
mm = MemoryManager()
mem_ctx = mm.recall(query=safe_input, project_id=_project_id, persona=_persona, max_tokens=800)
if mem_ctx:
    system_content = system_content + f"\n\n{mem_ctx}"
```

**After user message built (ingest extraction):**
```python
mm.ingest_from_message("user", safe_input, project_id=_project_id)
```

The injection is wrapped in `try/except` and **never blocks the agent loop**. If memory fails (Ollama down, DB locked), the agent continues without memory context.

### `storage/db.py` — `db_init()`

```python
# At end of db_init():
from memory.store import MemoryStore
MemoryStore.initialize()
```

This ensures the `memories` and `memory_conflicts` tables are created alongside all other JARVIS tables on first boot.

---

## 11. Known Risks and Follow-Up Items

| Risk | Mitigation |
|------|-----------|
| Memory injection increases system prompt token count | max_tokens=800 hard cap; context trimmed to budget |
| Rule-based extraction produces noisy working-layer records | They decay fast (0.1 day constant); only promoted if reinforced |
| companion_preferences and memories overlap for persona prefs | By convention: companion_preferences = TTS/voice prefs; memories = semantic facts. Not enforced by code. |
| No cross-session access count tracking for promoter | access_count increments on every read — single session can trigger promotion if used heavily |
| No vector search | Keyword overlap is a placeholder. Future phase: embed keys+values with sentence-transformers at write time, cosine score at retrieval time. Hook is `MemoryRetriever.keyword_match()`. |
| DB contention on busy sessions | get_db() opens/closes per call; MemoryStore operations are independent transactions |
| No UI for memory inspection | Use `inspect_memory` tool or direct DB query. GUI panel is a future phase item. |

---

## 12. File Index

| File | Role |
|------|------|
| `memory/__init__.py` | Re-exports MemoryManager |
| `memory/models.py` | Dataclasses: MemoryRecord, ConflictRecord, enums, decay helpers |
| `memory/store.py` | SQLite CRUD layer |
| `memory/retrieval.py` | Ranking and context formatting |
| `memory/promoter.py` | Promotion, ingestion, hygiene |
| `memory/manager.py` | Public facade (singleton) |
| `memory/tools.py` | Tool implementations for registry |
| `memory/tests/test_memory.py` | Unit tests (no Ollama required) |
| `storage/db.py` | Added `MemoryStore.initialize()` call in `db_init()` |
| `tools/registry.py` | Added 7 memory tool schemas + dispatch cases + REGISTRY entries |
| `agents/worker.py` | Added memory context injection + message ingestion |
