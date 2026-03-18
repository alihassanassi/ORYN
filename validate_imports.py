"""
validate_imports.py — Phase 4 import sanity check.
Run: python validate_imports.py  (no GUI launched)
"""
import sys, os
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.*=false"

results = []

def check(label, fn):
    try:
        fn()
        results.append(f"  OK   {label}")
    except Exception as e:
        results.append(f"  FAIL {label}: {e}")

# ── non-GUI modules (safe to import without QApplication) ─────────────────────
check("config",           lambda: __import__("config"))
check("storage.db",       lambda: __import__("storage.db", fromlist=[""]))
check("llm.client",       lambda: __import__("llm.client", fromlist=[""]))
check("llm.prompts",      lambda: __import__("llm.prompts", fromlist=[""]))
check("tools.system_tools",  lambda: __import__("tools.system_tools",  fromlist=[""]))
check("tools.shell_tools",   lambda: __import__("tools.shell_tools",   fromlist=[""]))
check("tools.project_tools", lambda: __import__("tools.project_tools", fromlist=[""]))
check("tools.voice_tools",   lambda: __import__("tools.voice_tools",   fromlist=[""]))
check("tools.registry",      lambda: __import__("tools.registry",      fromlist=[""]))
check("voice.tts",        lambda: __import__("voice.tts",  fromlist=[""]))
check("voice.stt",        lambda: __import__("voice.stt",  fromlist=[""]))
check("evolution.engine", lambda: __import__("evolution.engine", fromlist=[""]))
check("agents.worker",    lambda: __import__("agents.worker",    fromlist=[""]))
check("agents.autonomous",lambda: __import__("agents.autonomous",fromlist=[""]))
check("agents.monitor",   lambda: __import__("agents.monitor",   fromlist=[""]))

# ── GUI modules (require QApplication) ────────────────────────────────────────
try:
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    check("gui.widgets",     lambda: __import__("gui.widgets",     fromlist=[""]))
    check("gui.main_window", lambda: __import__("gui.main_window", fromlist=[""]))
except Exception as e:
    results.append(f"  SKIP gui.* (PySide6 unavailable: {e})")

print("\nPhase 4 Import Validation")
print("=" * 40)
for r in results:
    print(r)
fails = [r for r in results if "FAIL" in r]
print("=" * 40)
print(f"{'ALL OK' if not fails else f'{len(fails)} FAILURE(S)'}")
