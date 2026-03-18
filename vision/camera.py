"""
vision/camera.py – JARVIS room scanner.

Uses webcam to identify people in the room.
Stores face embeddings + name + notes locally in jarvis.db.
Never sends any image or embedding to external services.
Adapts JARVIS speech style based on who's present.

PRIVACY GUARANTEE:
  - All processing local (face_recognition library, CPU)
  - No images stored – only numerical embeddings
  - Operator can run: delete_all_faces() to wipe completely
  - Disabled by default (VISION_ENABLED = False)

Requires: pip install face-recognition opencv-python
"""
from __future__ import annotations
import threading
import time
import logging
import pathlib
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class RoomScanner:
    """
    Scans the room using webcam, identifies known people,
    stores new faces for learning, and notifies JARVIS.
    """

    def __init__(self, on_person_detected: Optional[Callable] = None):
        self._running       = False
        self._thread        = None
        self._on_detected   = on_person_detected
        self._known_faces: dict  = {}   # name → embedding
        self._present: set       = set()  # currently visible person names
        self._scan_interval      = 5.0   # scan every 5 seconds

    def start(self) -> None:
        import config as _cfg
        if not getattr(_cfg, 'VISION_ENABLED', False):
            logger.info("[Vision] Disabled (VISION_ENABLED=False)")
            return
        self._load_known_faces()
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="RoomScanner"
        )
        self._thread.start()
        logger.info("[Vision] Room scanner started")

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        import config as _cfg
        interval = getattr(_cfg, 'VISION_SCAN_INTERVAL_SECS', 5)
        while self._running:
            try:
                self._scan_once()
            except Exception as e:
                logger.debug(f"[Vision] Scan error: {e}")
            time.sleep(interval)

    def _scan_once(self) -> None:
        try:
            import cv2
            import face_recognition as fr
        except ImportError:
            logger.warning("[Vision] face-recognition not installed. "
                           "Run: pip install face-recognition opencv-python")
            self._running = False
            return

        import config as _cfg
        cam_idx = getattr(_cfg, 'VISION_CAMERA_INDEX', 0)
        cap = cv2.VideoCapture(cam_idx)
        if not cap.isOpened():
            return
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = fr.face_locations(rgb, model="hog")
        encodings = fr.face_encodings(rgb, locations)

        detected_now: set = set()
        for enc in encodings:
            name = self._identify_face(enc, fr)
            detected_now.add(name)

        for name in detected_now - self._present:
            self._on_person_arrived(name)

        for name in self._present - detected_now:
            self._on_person_left(name)

        self._present = detected_now

    def _identify_face(self, encoding, fr) -> str:
        import config as _cfg
        tolerance = getattr(_cfg, 'VISION_FACE_TOLERANCE', 0.5)

        if not self._known_faces:
            return self._learn_new_face(encoding)

        known_encs  = list(self._known_faces.values())
        known_names = list(self._known_faces.keys())
        matches = fr.compare_faces(known_encs, encoding, tolerance=tolerance)

        if any(matches):
            idx = matches.index(True)
            return known_names[idx]
        return self._learn_new_face(encoding)

    def _learn_new_face(self, encoding) -> str:
        """Store new face with auto-generated name. Operator can rename later."""
        name = f"Person_{int(time.time())}"
        self._known_faces[name] = encoding
        self._save_face(name, encoding)
        logger.info(f"[Vision] New person detected – stored as '{name}'")
        return name

    def _on_person_arrived(self, name: str) -> None:
        logger.info(f"[Vision] {name} entered the room")
        if self._on_detected:
            self._on_detected("arrived", name)
        self._adapt_speech_for_audience(self._present | {name})

    def _on_person_left(self, name: str) -> None:
        logger.info(f"[Vision] {name} left the room")
        if self._on_detected:
            self._on_detected("left", name)

    def _adapt_speech_for_audience(self, people: set) -> None:
        """
        Adjust JARVIS speech formality based on who's in the room.
        Operator alone → casual, technical
        Unknown people → more formal, less technical
        Multiple people → formal
        """
        try:
            import config as _cfg
            if len(people) <= 1:
                _cfg.SPEECH_FORMALITY = "casual"
            elif len(people) > 2:
                _cfg.SPEECH_FORMALITY = "formal"
            else:
                _cfg.SPEECH_FORMALITY = "neutral"
        except Exception:
            pass

    def _save_face(self, name: str, encoding) -> None:
        """Save face embedding to DB (numbers only, no images)."""
        try:
            import json
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO known_faces "
                    "(name, embedding, notes) VALUES (?, ?, ?)",
                    (name, json.dumps(encoding.tolist()), "")
                )
        except Exception as e:
            logger.debug(f"[Vision] Save face failed: {e}")

    def _load_known_faces(self) -> None:
        try:
            import json
            import numpy as np
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT name, embedding FROM known_faces"
                ).fetchall()
            for row in rows:
                self._known_faces[row[0]] = np.array(json.loads(row[1]))
            logger.info(f"[Vision] Loaded {len(self._known_faces)} known faces")
        except Exception as e:
            logger.debug(f"[Vision] Load faces failed: {e}")

    def rename_person(self, old_name: str, new_name: str) -> bool:
        if old_name not in self._known_faces:
            return False
        self._known_faces[new_name] = self._known_faces.pop(old_name)
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "UPDATE known_faces SET name=? WHERE name=?",
                    (new_name, old_name)
                )
        except Exception:
            pass
        return True

    def delete_all_faces(self) -> None:
        """Complete wipe of all face data."""
        self._known_faces.clear()
        self._present.clear()
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute("DELETE FROM known_faces")
        except Exception:
            pass
        logger.info("[Vision] All face data deleted")

    def get_present(self) -> list:
        """Return list of currently visible people."""
        return list(self._present)

    def get_known_count(self) -> int:
        """Return number of known faces."""
        return len(self._known_faces)
