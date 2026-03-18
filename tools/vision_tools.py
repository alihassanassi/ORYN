"""
tools/vision_tools.py — JARVIS camera vision tool implementations.

All face data is stored locally in jarvis.db (known_faces table).
No images are stored — only numerical embeddings.
Vision is disabled by default (VISION_ENABLED = False in config.py).
"""
from __future__ import annotations


def _vision_status() -> dict:
    try:
        from runtime.boot_manager import get_boot_manager
        bm = get_boot_manager()
        scanner = getattr(bm, '_room_scanner', None)
        if scanner:
            return {
                "enabled": True,
                "present": scanner.get_present(),
                "known": scanner.get_known_count(),
            }
    except Exception:
        pass
    import config as _cfg
    return {
        "enabled": getattr(_cfg, 'VISION_ENABLED', False),
        "present": [],
        "known": 0,
    }


def _vision_list_known_people() -> dict:
    try:
        from storage.db import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT name, notes, first_seen, visit_count "
                "FROM known_faces ORDER BY visit_count DESC"
            ).fetchall()
        return {
            "people": [
                {
                    "name": r[0],
                    "notes": r[1],
                    "first_seen": r[2],
                    "visits": r[3],
                }
                for r in rows
            ]
        }
    except Exception as e:
        return {"error": str(e)}


def _vision_rename_person(old_name: str, new_name: str) -> dict:
    try:
        from runtime.boot_manager import get_boot_manager
        bm = get_boot_manager()
        scanner = getattr(bm, '_room_scanner', None)
        if scanner:
            ok = scanner.rename_person(old_name, new_name)
            return {"success": ok, "renamed": f"{old_name} → {new_name}"}
    except Exception:
        pass
    # Scanner not running — update DB directly
    try:
        from storage.db import get_db
        with get_db() as conn:
            conn.execute(
                "UPDATE known_faces SET name=? WHERE name=?",
                (new_name, old_name)
            )
        return {"success": True, "renamed": f"{old_name} → {new_name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _vision_delete_all_faces() -> dict:
    try:
        from runtime.boot_manager import get_boot_manager
        bm = get_boot_manager()
        scanner = getattr(bm, '_room_scanner', None)
        if scanner:
            scanner.delete_all_faces()
            return {"success": True, "message": "All face data deleted"}
    except Exception:
        pass
    # Scanner not running — wipe DB directly
    try:
        from storage.db import get_db
        with get_db() as conn:
            conn.execute("DELETE FROM known_faces")
        return {"success": True, "message": "All face data deleted"}
    except Exception as e:
        return {"success": False, "error": str(e)}
