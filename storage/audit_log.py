"""
ImmutableAuditLog — append-only, hash-chained audit trail for all autonomous actions.

Why: When JARVIS autonomously scans a target, you need to be able to prove:
  - What it scanned (target, tool, timestamp)
  - Why it scanned it (which policy decision permitted it)
  - What it found (finding reference)
  - Who authorized it (operator implicit via config, or explicit approval)

Hash chaining: each row contains SHA256(previous_row_hash + current_row_data).
Any tampering breaks the chain and is detectable by verify_chain().
"""
import hashlib, json, logging, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from config import ROOT_DIR

logger = logging.getLogger(__name__)

AUDIT_DB = ROOT_DIR / "audit_log.db"  # Separate from main jarvis.db — intentional isolation


class ImmutableAuditLog:

    def __init__(self, db_path: str = AUDIT_DB):
        self._db = db_path
        self._init_db()

    def _init_db(self) -> None:
        # Path(":memory:").parent is Path(".") — mkdir is safe
        parent = Path(self._db).parent
        if str(parent) != ".":
            parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          TEXT    NOT NULL,
                    event_type  TEXT    NOT NULL,
                    actor       TEXT    NOT NULL,
                    target      TEXT,
                    tool        TEXT,
                    decision    TEXT,
                    reason      TEXT,
                    program_id  INTEGER,
                    extra       TEXT,
                    row_hash    TEXT NOT NULL
                )
            """)
            conn.commit()

    def _last_hash(self) -> str:
        with sqlite3.connect(self._db) as conn:
            row = conn.execute(
                "SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else "GENESIS"

    def append(
        self,
        event_type: str,
        actor: str,
        target: str = None,
        tool: str = None,
        decision: str = None,
        reason: str = None,
        program_id: int = None,
        **extra,
    ) -> int:
        """
        Appends an immutable audit record.
        Returns the new row ID.
        Thread-safe via SQLite write serialization.
        """
        ts = datetime.now(timezone.utc).isoformat()
        row_data = json.dumps({
            "ts": ts, "event_type": event_type, "actor": actor,
            "target": target, "tool": tool, "decision": decision,
            "reason": reason, "program_id": program_id, "extra": extra,
        }, sort_keys=True)
        prev_hash = self._last_hash()
        row_hash = hashlib.sha256(
            (prev_hash + row_data).encode()
        ).hexdigest()

        with sqlite3.connect(self._db) as conn:
            cur = conn.execute(
                """INSERT INTO audit_log
                   (ts, event_type, actor, target, tool, decision, reason, program_id, extra, row_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (ts, event_type, actor, target, tool, decision, reason,
                 program_id, json.dumps(extra) if extra else None, row_hash)
            )
            conn.commit()
            return cur.lastrowid

    def verify_chain(self) -> tuple[bool, str]:
        """
        Verifies the hash chain has not been tampered with.
        Returns (True, "chain intact") or (False, "tampered at row N").
        """
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                "SELECT id, ts, event_type, actor, target, tool, decision, reason, "
                "program_id, extra, row_hash FROM audit_log ORDER BY id"
            ).fetchall()

        prev_hash = "GENESIS"
        for row in rows:
            row_id = row[0]
            stored_hash = row[10]
            row_data = json.dumps({
                "ts": row[1], "event_type": row[2], "actor": row[3],
                "target": row[4], "tool": row[5], "decision": row[6],
                "reason": row[7], "program_id": row[8],
                "extra": json.loads(row[9]) if row[9] else {},
            }, sort_keys=True)
            expected_hash = hashlib.sha256((prev_hash + row_data).encode()).hexdigest()
            if stored_hash != expected_hash:
                return False, f"chain broken at row {row_id}"
            prev_hash = stored_hash

        return True, f"chain intact — {len(rows)} records verified"

    def export(self, since_hours: int = 24) -> list[dict]:
        """Returns audit records from the last N hours as dicts."""
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                """SELECT ts, event_type, actor, target, tool, decision, reason, program_id
                   FROM audit_log
                   WHERE ts > datetime('now', ?)
                   ORDER BY id""",
                (f"-{since_hours} hours",)
            ).fetchall()
        keys = ("ts", "event_type", "actor", "target", "tool", "decision", "reason", "program_id")
        return [dict(zip(keys, row)) for row in rows]
