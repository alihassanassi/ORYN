"""
voice/clip_manager.py — Reference clip pipeline manager for Chatterbox zero-shot voice cloning.

Clips live in CHATTERBOX_REFERENCE_DIR (default: voice/reference_clips/).
Naming convention: {persona}_{description}.wav
Examples: jarvis_primary.wav, india_soft.wav, ct7567_battle.wav, morgan_deep.wav

No external dependencies — uses only stdlib: wave, shutil, pathlib, os.
"""
from __future__ import annotations

import os
import shutil
import wave
from pathlib import Path
from typing import Optional

import config as _cfg

# ── Constants ──────────────────────────────────────────────────────────────────
_MIN_DURATION_SECS: float = 5.0
_MAX_DURATION_SECS: float = 30.0
_MIN_SIZE_KB: float = 10.0


class ClipManager:
    """
    Manages reference WAV clips for Chatterbox zero-shot voice cloning.

    Clips are stored in CHATTERBOX_REFERENCE_DIR (default: voice/reference_clips/).
    Naming convention: {persona}_{description}.wav
    e.g.: jarvis_primary.wav, india_soft.wav, ct7567_battle.wav, morgan_deep.wav
    """

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _clip_dir(self) -> Path:
        """Return the resolved absolute clip directory, creating it if absent."""
        ref = _cfg.CHATTERBOX_REFERENCE_DIR
        p = Path(ref) if os.path.isabs(ref) else Path(_cfg.ROOT_DIR) / ref
        p = p.resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _read_wav_info(self, path: Path) -> dict:
        """
        Open a WAV file with the stdlib wave module and return metadata.
        Returns a dict with keys: duration_secs, sample_rate, channels, error.
        Never raises — errors are captured in the 'error' key.
        """
        try:
            with wave.open(str(path), "rb") as wf:
                frames = wf.getnframes()
                sample_rate = wf.getframerate()
                channels = wf.getnchannels()
                duration = frames / sample_rate if sample_rate > 0 else 0.0
            return {
                "duration_secs": round(duration, 3),
                "sample_rate": sample_rate,
                "channels": channels,
                "error": None,
            }
        except Exception as exc:
            return {
                "duration_secs": 0.0,
                "sample_rate": 0,
                "channels": 0,
                "error": str(exc),
            }

    def _is_valid(self, path: Path, wav_info: dict) -> bool:
        """Return True when the clip meets all acceptance criteria."""
        if wav_info["error"]:
            return False
        if not path.exists():
            return False
        size_kb = path.stat().st_size / 1024
        if size_kb < _MIN_SIZE_KB:
            return False
        dur = wav_info["duration_secs"]
        return _MIN_DURATION_SECS <= dur <= _MAX_DURATION_SECS

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_clip_dir(self) -> Path:
        """
        Return the resolved absolute path of CHATTERBOX_REFERENCE_DIR.
        Creates the directory if it does not exist.
        """
        return self._clip_dir()

    def list_clips(self, persona: Optional[str] = None) -> list[dict]:
        """
        Scan CHATTERBOX_REFERENCE_DIR for *.wav files.

        If persona is given, only files matching {persona}_*.wav are returned.
        Each entry contains:
            name, path, persona, description, size_kb, duration_secs, valid
        """
        try:
            clip_dir = self._clip_dir()
            pattern = f"{persona}_*.wav" if persona else "*.wav"
            wav_files = sorted(clip_dir.glob(pattern))

            results: list[dict] = []
            for wav_path in wav_files:
                stem = wav_path.stem  # e.g. "jarvis_primary"
                parts = stem.split("_", 1)
                clip_persona = parts[0] if len(parts) >= 1 else ""
                clip_desc = parts[1] if len(parts) == 2 else ""
                size_kb = round(wav_path.stat().st_size / 1024, 2)
                wav_info = self._read_wav_info(wav_path)
                valid = self._is_valid(wav_path, wav_info)
                results.append({
                    "name": wav_path.name,
                    "path": str(wav_path),
                    "persona": clip_persona,
                    "description": clip_desc,
                    "size_kb": size_kb,
                    "duration_secs": wav_info["duration_secs"],
                    "valid": valid,
                })
            return results
        except Exception as exc:
            return [{"error": str(exc)}]

    def get_best_clip(self, persona: str) -> Optional[Path]:
        """
        Return the path to the first valid clip for the given persona (alphabetical).
        Returns None if no valid clips exist for that persona.
        """
        try:
            clips = self.list_clips(persona=persona)
            for clip in clips:
                if clip.get("valid"):
                    return Path(clip["path"])
            return None
        except Exception:
            return None

    def validate_clip(self, path) -> dict:
        """
        Validate a WAV clip file.

        Returns:
            {valid, duration_secs, sample_rate, channels, size_kb, error}
        """
        try:
            p = Path(path).resolve()
            if not p.exists():
                return {
                    "valid": False,
                    "duration_secs": 0.0,
                    "sample_rate": 0,
                    "channels": 0,
                    "size_kb": 0.0,
                    "error": f"File not found: {p}",
                }
            size_kb = round(p.stat().st_size / 1024, 2)
            wav_info = self._read_wav_info(p)
            valid = self._is_valid(p, wav_info)

            error: Optional[str] = wav_info["error"]
            if not error and size_kb < _MIN_SIZE_KB:
                error = f"File too small ({size_kb:.1f} KB, minimum {_MIN_SIZE_KB} KB)"
            elif not error and not (_MIN_DURATION_SECS <= wav_info["duration_secs"] <= _MAX_DURATION_SECS):
                error = (
                    f"Duration {wav_info['duration_secs']:.1f}s out of accepted range "
                    f"({_MIN_DURATION_SECS}–{_MAX_DURATION_SECS}s)"
                )

            return {
                "valid": valid,
                "duration_secs": wav_info["duration_secs"],
                "sample_rate": wav_info["sample_rate"],
                "channels": wav_info["channels"],
                "size_kb": size_kb,
                "error": error,
            }
        except Exception as exc:
            return {
                "valid": False,
                "duration_secs": 0.0,
                "sample_rate": 0,
                "channels": 0,
                "size_kb": 0.0,
                "error": str(exc),
            }

    def add_clip(self, src_path, persona: str, description: str) -> dict:
        """
        Copy a WAV file into CHATTERBOX_REFERENCE_DIR as {persona}_{description}.wav.

        Validates duration (5–30 s) and size (>10 KB) before accepting.
        Returns: {ok, path, error}
        """
        try:
            src = Path(src_path).resolve()
            if not src.exists():
                return {"ok": False, "path": "", "error": f"Source file not found: {src}"}
            if not src.suffix.lower() == ".wav":
                return {"ok": False, "path": "", "error": "Source file must be a .wav file"}

            # Validate before copying
            validation = self.validate_clip(src)
            if not validation["valid"]:
                return {
                    "ok": False,
                    "path": "",
                    "error": validation["error"] or "Clip did not pass validation",
                }

            # Sanitise persona and description to safe filename components
            safe_persona = "".join(c for c in persona if c.isalnum() or c == "_").lower()
            safe_desc = "".join(c for c in description if c.isalnum() or c == "_").lower()
            if not safe_persona:
                return {"ok": False, "path": "", "error": "Persona name is empty or invalid"}
            if not safe_desc:
                return {"ok": False, "path": "", "error": "Description is empty or invalid"}

            dest_name = f"{safe_persona}_{safe_desc}.wav"
            clip_dir = self._clip_dir()
            dest = clip_dir / dest_name

            shutil.copy2(str(src), str(dest))

            return {"ok": True, "path": str(dest), "error": None}
        except Exception as exc:
            return {"ok": False, "path": "", "error": str(exc)}

    def remove_clip(self, name: str) -> dict:
        """
        Delete CHATTERBOX_REFERENCE_DIR/{name}.

        Safety checks:
        - name must end in .wav
        - resolved path must be inside CHATTERBOX_REFERENCE_DIR (no path traversal)
        Returns: {ok, error}
        """
        try:
            if not name.lower().endswith(".wav"):
                return {"ok": False, "error": "Only .wav files may be removed"}

            clip_dir = self._clip_dir()
            target = (clip_dir / name).resolve()

            # Path traversal guard — resolved path must start with the clip directory
            try:
                target.relative_to(clip_dir)
            except ValueError:
                return {"ok": False, "error": "Path traversal detected — operation refused"}

            if not target.exists():
                return {"ok": False, "error": f"Clip not found: {name}"}

            if not target.is_file():
                return {"ok": False, "error": f"Not a regular file: {name}"}

            target.unlink()
            return {"ok": True, "error": None}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# ── Module-level singleton ─────────────────────────────────────────────────────

_manager: Optional[ClipManager] = None


def get_clip_manager() -> ClipManager:
    """Return the module-level ClipManager singleton, creating it on first call."""
    global _manager
    if _manager is None:
        _manager = ClipManager()
    return _manager


# ── Tool functions for registry dispatch ──────────────────────────────────────

def tool_list_clips(persona: Optional[str] = None) -> dict:
    """List reference WAV clips, optionally filtered by persona."""
    try:
        clips = get_clip_manager().list_clips(persona=persona)
        if not clips or (len(clips) == 1 and "error" in clips[0]):
            err = clips[0].get("error", "") if clips else ""
            return {"output": f"No clips found.{(' Error: ' + err) if err else ''}"}
        lines = []
        for c in clips:
            status = "VALID" if c.get("valid") else "INVALID"
            lines.append(
                f"[{status}] {c['name']}  |  {c['duration_secs']:.1f}s  |  {c['size_kb']:.1f} KB"
                f"  |  persona={c['persona']}  description={c['description']}"
            )
        header = f"Reference clips ({len(clips)} found"
        if persona:
            header += f" for persona '{persona}'"
        header += "):"
        return {"output": header + "\n" + "\n".join(lines)}
    except Exception as exc:
        return {"output": f"Error listing clips: {exc}"}


def tool_add_clip(src_path: str, persona: str, description: str) -> dict:
    """Add a reference WAV clip for a persona. Validates duration before copying."""
    try:
        result = get_clip_manager().add_clip(src_path, persona, description)
        if result["ok"]:
            return {"output": f"Clip added: {result['path']}"}
        return {"output": f"Failed to add clip: {result['error']}"}
    except Exception as exc:
        return {"output": f"Error adding clip: {exc}"}


def tool_remove_clip(name: str) -> dict:
    """Remove a reference WAV clip by filename."""
    try:
        result = get_clip_manager().remove_clip(name)
        if result["ok"]:
            return {"output": f"Clip removed: {name}"}
        return {"output": f"Failed to remove clip: {result['error']}"}
    except Exception as exc:
        return {"output": f"Error removing clip: {exc}"}


def tool_validate_clip(path: str) -> dict:
    """Validate a WAV clip file: duration, sample rate, channels, size."""
    try:
        v = get_clip_manager().validate_clip(path)
        status = "VALID" if v["valid"] else "INVALID"
        lines = [
            f"Clip validation: {status}",
            f"  Duration:    {v['duration_secs']:.3f}s (accepted: {_MIN_DURATION_SECS}–{_MAX_DURATION_SECS}s)",
            f"  Sample rate: {v['sample_rate']} Hz",
            f"  Channels:    {v['channels']}",
            f"  Size:        {v['size_kb']:.2f} KB (minimum: {_MIN_SIZE_KB} KB)",
        ]
        if v["error"]:
            lines.append(f"  Error:       {v['error']}")
        return {"output": "\n".join(lines)}
    except Exception as exc:
        return {"output": f"Error validating clip: {exc}"}
