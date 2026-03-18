"""
main.py — JARVIS entry point.

Launch sequence:
  1. Create QApplication
  2. Show JarvisSplash (animated boot screen)
  3. Background-initialise JARVIS main window while splash plays
  4. On boot_complete signal → show main window, close splash
"""
from __future__ import annotations

import logging
import sys
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── Logging setup ──────────────────────────────────────────────────────────────
# Use a SafeStreamHandler that catches BrokenPipeError / closed-stream errors
# instead of letting Python print "--- Logging error ---" to stderr.  This
# happens on Windows when PySide6 detaches sys.stderr during shutdown.
class _SafeStreamHandler(logging.StreamHandler):
    """StreamHandler that silently swallows errors from a closed/broken stream."""
    def emit(self, record):
        try:
            super().emit(record)
        except Exception:
            pass  # never let a logging handler exception surface

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_console = _SafeStreamHandler(sys.stderr)
_console.setFormatter(_fmt)
logging.root.setLevel(logging.INFO)
logging.root.addHandler(_console)
# Silence the default lastResort handler so it doesn't double-print errors.
logging.lastResort = None

log = logging.getLogger("jarvis.main")

# ── File handler for crash logs ─────────────────────────────────────────────
import pathlib as _pathlib
_log_dir = _pathlib.Path("logs")
_log_dir.mkdir(exist_ok=True)
_fh = logging.FileHandler(_log_dir / "jarvis.log", encoding="utf-8")
_fh.setLevel(logging.WARNING)
_fh.setFormatter(_fmt)
logging.getLogger().addHandler(_fh)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def _probe_fonts() -> None:
    """Update config MONO_CSS / DISPLAY_CSS to use fonts that are actually installed."""
    try:
        from PySide6.QtGui import QFontDatabase
        import config as _cfg
        avail = set(QFontDatabase.families())
        mono_pref = ["JetBrains Mono", "Share Tech Mono", "Consolas", "Courier New"]
        disp_pref = ["Rajdhani", "Segoe UI", "Arial"]
        mono = next((f for f in mono_pref if f in avail), "Consolas")
        disp = next((f for f in disp_pref if f in avail), "Segoe UI")
        _cfg.MONO     = mono
        _cfg.MONO_CSS    = f"'{mono}', monospace"
        _cfg.DISPLAY_CSS = f"'{disp}', sans-serif"
        log.info("Fonts → mono=%s  display=%s", mono, disp)
    except Exception as exc:
        log.warning("Font probe failed (non-fatal): %s", exc)


if __name__ == "__main__":
    import os as _os
    # DPI scaling — must be set before QApplication is created
    _os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    _os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING",   "1")

    app = QApplication(sys.argv)
    app.setApplicationName("JARVIS")
    app.setOrganizationName("JARVIS-OPS")
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)

    # ── Boot splash ───────────────────────────────────────────────────────
    from gui.splash import JarvisSplash
    splash = JarvisSplash(total_ms=3200)
    splash.show()
    app.processEvents()

    # ── Font probe (runs while splash animates) ───────────────────────────
    _probe_fonts()

    # ── Build main window (hidden) ────────────────────────────────────────
    try:
        from gui.main_window import JARVIS
        window = JARVIS()
    except Exception as exc:
        log.critical("Failed to create main window: %s", exc)
        splash.close()
        sys.exit(1)

    # ── Start autonomy stack (security onion + optional recon) ────────────
    try:
        from runtime.boot_manager import start_autonomy_stack
        start_autonomy_stack()
    except Exception as exc:
        log.warning("Autonomy stack init failed (non-fatal): %s", exc)

    # ── Wire splash → window ──────────────────────────────────────────────
    def _on_boot_complete() -> None:
        window.show()
        log.info("Main window shown — boot complete.")

    splash.boot_complete.connect(_on_boot_complete)

    # Guard: if splash already closed before connection was made, show now
    if not splash.isVisible():
        window.show()

    _app_exit = app.exec()

    # Exit code 42 = kill switch was activated (guardian will NOT restart)
    import pathlib as _pl
    _kill_flag = _pl.Path("EMERGENCY_STOP.flag")
    _exit_code = 42 if _kill_flag.exists() else _app_exit
    sys.exit(_exit_code)
