"""
storage/db.py — All SQLite persistence for J.A.R.V.I.S.

One connection per call, one lock for thread safety.
Public API: db_init, project helpers, message helpers, command log.
"""
from __future__ import annotations
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from config import DB_PATH

_db_lock = threading.RLock()   # RLock allows reentrant acquisition


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _db(sql: str, params=(), *, fetch=None):
    with _db_lock, _conn() as c:
        cur = c.execute(sql, params)
        if fetch == "one":  return cur.fetchone()
        if fetch == "all":  return cur.fetchall()
        return cur.lastrowid


@contextmanager
def get_db():
    """
    Context manager yielding a raw sqlite3.Connection.
    Commits on clean exit, rolls back on exception, always closes.
    Used by the autonomy stack and new-style queries.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-65536")   # 64MB in-memory page cache
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=33554432")  # 32MB memory-mapped I/O
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_local = threading.local()

def get_db_cached():
    """
    Thread-local cached connection for background daemons (hot read paths).
    Falls back to get_db() on any error. Has all WAL PRAGMAs pre-applied.
    """
    try:
        if not hasattr(_local, 'conn') or _local.conn is None:
            _local.conn = sqlite3.connect(
                DB_PATH, check_same_thread=False, timeout=10
            )
            _local.conn.row_factory = sqlite3.Row
            _local.conn.execute("PRAGMA journal_mode=WAL")
            _local.conn.execute("PRAGMA cache_size=-65536")
            _local.conn.execute("PRAGMA synchronous=NORMAL")
            _local.conn.execute("PRAGMA temp_store=MEMORY")
            _local.conn.execute("PRAGMA mmap_size=33554432")
        return _local.conn
    except Exception:
        pass  # Fall through to context manager fallback


def db_init():
    with _db_lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT UNIQUE NOT NULL,
            active     INTEGER DEFAULT 0,
            notes      TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            project    TEXT,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            ts         TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS commands (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            project    TEXT,
            command    TEXT NOT NULL,
            result     TEXT,
            ts         TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scan_targets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            project    TEXT,
            target     TEXT NOT NULL,
            notes      TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS findings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            project    TEXT,
            target     TEXT,
            title      TEXT NOT NULL,
            detail     TEXT DEFAULT '',
            severity   TEXT DEFAULT 'info',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS programs (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            name                   TEXT UNIQUE NOT NULL,
            status                 TEXT DEFAULT 'active',
            scope_domains          TEXT DEFAULT '[]',
            wildcard_auto_approved INTEGER DEFAULT 0,
            platform               TEXT DEFAULT 'hackerone',
            created_at             TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS actions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT NOT NULL,
            program_id  INTEGER,
            tool        TEXT,
            target      TEXT,
            status      TEXT DEFAULT 'completed',
            created_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id  INTEGER,
            domain      TEXT,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS findings_canonical (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id       INTEGER,
            title            TEXT NOT NULL,
            severity         TEXT DEFAULT 'info',
            host             TEXT,
            template_id      TEXT,
            matched_at       TEXT,
            raw_output       TEXT DEFAULT '',
            status           TEXT DEFAULT 'unverified',
            bounty_potential TEXT DEFAULT 'low',
            priority_score   REAL DEFAULT 0.0,
            payout_usd       REAL DEFAULT 0.0,
            verified         INTEGER DEFAULT 0,
            created_at       TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jarvis_preferences (
            tool_name      TEXT UNIQUE NOT NULL,
            approved_count INTEGER DEFAULT 0,
            rejected_count INTEGER DEFAULT 0,
            modified_count INTEGER DEFAULT 0,
            last_seen      TEXT,
            created_at     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS denied_actions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            action     TEXT NOT NULL,
            args       TEXT DEFAULT '',
            reason     TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ambient_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript  TEXT NOT NULL,
            mode        TEXT,
            responded   INTEGER DEFAULT 0,
            priority    TEXT DEFAULT 'low',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ambient_created ON ambient_log(created_at);
        CREATE TABLE IF NOT EXISTS companion_skills (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            domain      TEXT NOT NULL,
            evidence    TEXT,
            level_delta REAL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS companion_preferences (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            persona     TEXT NOT NULL,
            key         TEXT NOT NULL,
            value       TEXT,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(persona, key)
        );
        CREATE TABLE IF NOT EXISTS research_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source          TEXT NOT NULL,
            item_type       TEXT,
            title           TEXT,
            severity        TEXT DEFAULT 'info',
            url             TEXT,
            affects_targets INTEGER DEFAULT 0,
            actioned        INTEGER DEFAULT 0,
            raw_data        TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_research_severity ON research_items(severity, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_research_title ON research_items(source, title, created_at);
        CREATE TABLE IF NOT EXISTS tool_effectiveness (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name           TEXT NOT NULL,
            tech_stack          TEXT NOT NULL,
            finding_rate        REAL DEFAULT 0.0,
            false_positive_rate REAL DEFAULT 0.0,
            avg_duration_secs   REAL DEFAULT 0.0,
            sample_count        INTEGER DEFAULT 0,
            last_updated        TEXT NOT NULL,
            UNIQUE(tool_name, tech_stack)
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_findings_program ON findings_canonical(program_id, severity);
        CREATE INDEX IF NOT EXISTS idx_messages_project ON messages(project, ts);
        CREATE TABLE IF NOT EXISTS known_faces (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            embedding   TEXT NOT NULL,
            notes       TEXT DEFAULT '',
            first_seen  TEXT DEFAULT (datetime('now')),
            last_seen   TEXT DEFAULT (datetime('now')),
            visit_count INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_known_faces_name ON known_faces(name);
        """)
        # Schema migrations — safe to re-run; silently ignored if already applied
        _migrations = [
            "ALTER TABLE findings_canonical ADD COLUMN payout_usd REAL DEFAULT 0.0",
            "ALTER TABLE scan_targets ADD COLUMN notes TEXT DEFAULT ''",
            "ALTER TABLE scan_targets ADD COLUMN created_at TEXT DEFAULT ''",
        ]
        for _m in _migrations:
            try:
                c.execute(_m)
            except sqlite3.OperationalError:
                pass  # column already exists

        c.execute(
            "INSERT OR IGNORE INTO projects(name, active, created_at) VALUES(?,1,?)",
            ("Home Lab", datetime.now().isoformat())
        )

        # Performance indexes — added for WAL mode optimization
        for _idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_messages_project_ts ON messages(project, ts DESC)",
            "CREATE INDEX IF NOT EXISTS idx_findings_canonical_status ON findings_canonical(status, priority_score DESC)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_research_items_actioned ON research_items(actioned, severity)",
            "CREATE INDEX IF NOT EXISTS idx_ambient_log_responded ON ambient_log(responded, priority DESC)",
        ]:
            try:
                c.execute(_idx_sql)
            except Exception:
                pass

    # Initialize memory subsystem tables (separate connection, no lock contention)
    try:
        from memory.store import MemoryStore
        MemoryStore.initialize()
    except Exception:
        pass  # memory subsystem is optional — never block db_init()


# ── Project helpers ───────────────────────────────────────────────────────────

def get_active_project() -> str:
    r = _db("SELECT name FROM projects WHERE active=1 LIMIT 1", fetch="one")
    return r["name"] if r else "Home Lab"


def set_active_project(name: str):
    _db("UPDATE projects SET active=0")
    _db("INSERT OR IGNORE INTO projects(name, active, created_at) VALUES(?,1,?)",
        (name, datetime.now().isoformat()))
    _db("UPDATE projects SET active=1 WHERE name=?", (name,))


def list_projects() -> list[dict]:
    rows = _db("SELECT name, active FROM projects ORDER BY id DESC", fetch="all")
    return [dict(r) for r in rows]


def create_project(name: str):
    _db("INSERT OR IGNORE INTO projects(name, active, created_at) VALUES(?,0,?)",
        (name, datetime.now().isoformat()))


def append_note(project: str, text: str):
    existing = _db("SELECT notes FROM projects WHERE name=?", (project,), fetch="one")
    old = existing["notes"] if existing else ""
    ts = datetime.now().strftime("%H:%M")
    _db("UPDATE projects SET notes=? WHERE name=?",
        (f"{old}\n[{ts}] {text}".strip(), project))


def get_notes(project: str) -> str:
    r = _db("SELECT notes FROM projects WHERE name=?", (project,), fetch="one")
    return r["notes"] if r else ""


# ── Message helpers ───────────────────────────────────────────────────────────

def save_message(role: str, content: str, project: str):
    _db("INSERT INTO messages(project,role,content,ts) VALUES(?,?,?,?)",
        (project, role, content, datetime.now().isoformat()))


def get_history(project: str, limit: int = 20) -> list[dict]:
    rows = _db(
        "SELECT role, content FROM messages WHERE project=? ORDER BY id DESC LIMIT ?",
        (project, limit), fetch="all"
    )
    return [dict(r) for r in reversed(rows)]


# ── Command log ───────────────────────────────────────────────────────────────

def log_command(project: str, cmd: str, result: str):
    _db("INSERT INTO commands(project,command,result,ts) VALUES(?,?,?,?)",
        (project, cmd, result[:1000], datetime.now().isoformat()))


def get_recent_commands(project: str, n: int = 5) -> list[str]:
    rows = _db(
        "SELECT command FROM commands WHERE project=? ORDER BY id DESC LIMIT ?",
        (project, n), fetch="all"
    )
    return [r["command"] for r in rows]


# ── Scan targets (recon) ──────────────────────────────────────────────────────

def save_target(project: str, target: str, notes: str = "") -> int:
    return _db(
        "INSERT INTO scan_targets(project,target,notes,created_at) VALUES(?,?,?,?)",
        (project, target, notes, datetime.now().isoformat())
    )


def list_targets(project: str) -> list[dict]:
    rows = _db(
        "SELECT id, target, notes, created_at FROM scan_targets WHERE project=? ORDER BY id DESC",
        (project,), fetch="all"
    )
    return [dict(r) for r in rows]


# ── Findings ──────────────────────────────────────────────────────────────────

def save_finding(project: str, target: str, title: str, detail: str = "",
                 severity: str = "info") -> int:
    return _db(
        "INSERT INTO findings(project,target,title,detail,severity,created_at) VALUES(?,?,?,?,?,?)",
        (project, target, title, detail, severity, datetime.now().isoformat())
    )


def list_findings(project: str) -> list[dict]:
    rows = _db(
        "SELECT id, target, title, severity, created_at FROM findings WHERE project=? ORDER BY id DESC",
        (project,), fetch="all"
    )
    return [dict(r) for r in rows]


# ── Denied actions log (Phase 17) ─────────────────────────────────────────────

def log_denied_action(action: str, args: str = "", reason: str = "") -> None:
    """Logs a policy-denied action for audit purposes."""
    _db(
        "INSERT INTO denied_actions(action,args,reason,created_at) VALUES(?,?,?,?)",
        (action, args[:500], reason[:500], datetime.now().isoformat())
    )


# ── Programs (autonomy) ───────────────────────────────────────────────────────

def create_program(name: str, scope_domains: list = None, platform: str = "hackerone") -> int:
    import json as _json
    return _db(
        "INSERT OR IGNORE INTO programs(name,status,scope_domains,platform,created_at) VALUES(?,?,?,?,?)",
        (name, "active", _json.dumps(scope_domains or []), platform, datetime.now().isoformat())
    )


def list_programs() -> list[dict]:
    rows = _db("SELECT id,name,status,scope_domains,platform FROM programs ORDER BY id", fetch="all")
    return [dict(r) for r in rows]


def get_program(program_id: int) -> dict | None:
    row = _db("SELECT id,name,status,scope_domains,platform FROM programs WHERE id=?",
              (program_id,), fetch="one")
    return dict(row) if row else None


def get_active_program() -> dict | None:
    """Return the first program with status='active', or None.

    Used by the research engine and autonomy stack to determine which bug
    bounty program is currently being worked. Returns a dict with keys:
    id, name, status, scope_domains, platform.
    """
    row = _db(
        "SELECT id,name,status,scope_domains,platform FROM programs "
        "WHERE status='active' ORDER BY id LIMIT 1",
        fetch="one"
    )
    return dict(row) if row else None


# ── Database maintenance ───────────────────────────────────────────────────────

def db_stats() -> dict:
    """Return database statistics: table row counts and file size."""
    stats = {}
    try:
        with get_db() as conn:
            for table in ["projects", "messages", "commands", "scan_targets",
                          "ambient_log", "companion_skills", "companion_preferences",
                          "research_items", "findings"]:
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    stats[table] = row[0] if row else 0
                except Exception:
                    pass  # table may not exist
    except Exception as e:
        stats["error"] = str(e)
    try:
        import config as _c
        path = _c.DB_PATH
        import os
        stats["file_size_kb"] = round(os.path.getsize(path) / 1024, 1)
    except Exception:
        pass
    return stats


def db_vacuum() -> str:
    """Run VACUUM to defragment and shrink the database. Returns status string."""
    try:
        with get_db() as conn:
            conn.execute("VACUUM")
        return "Database vacuum complete."
    except Exception as e:
        return f"Vacuum failed: {e}"


def db_prune_old_messages(days: int = 90) -> int:
    """Delete messages older than `days` days. Returns count deleted."""
    try:
        with get_db() as conn:
            cur = conn.execute(
                "DELETE FROM messages WHERE ts < datetime('now', ?)",
                (f"-{days} days",)
            )
            return cur.rowcount
    except Exception:
        return 0
