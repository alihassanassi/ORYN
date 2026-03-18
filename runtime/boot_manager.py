"""
runtime/boot_manager.py — Autonomy stack startup sequence.

Called from main.py after the GUI splash completes.
Initializes the full 6-layer security model and optional recon loop.

Usage in main.py (after window = JARVIS()):
    from runtime.boot_manager import start_autonomy_stack
    start_autonomy_stack()
"""
import atexit
import pathlib
import subprocess
import sys
import config
import logging

logger = logging.getLogger(__name__)

# Module-level singletons — accessible to other modules via boot_manager
kill_switch    = None
watchdog       = None
audit          = None
judge          = None
router         = None
prefs          = None
finding_engine = None
recon_loop     = None

# Bridge server subprocess handle — kept so atexit can terminate it cleanly
_bridge_proc: "subprocess.Popen | None" = None


def _start_bridge() -> None:
    """
    Launch the FastAPI bridge server in a subprocess.

    Uses D:/jarvis_env/Scripts/python.exe when that virtualenv exists;
    falls back to sys.executable (the Python running JARVIS) if not.
    Port 5000 is checked first — if something is already listening there
    (e.g. a prior JARVIS instance) we skip launch rather than conflict.
    """
    global _bridge_proc

    # Port probe — skip launch if bridge is already up
    try:
        import socket as _sock
        with _sock.create_connection(("127.0.0.1", 5000), timeout=0.5):
            logger.info("[BootManager] bridge already running on :5000 — skipping launch")
            return
    except OSError:
        pass  # nothing listening — proceed

    # Prefer the project virtualenv; fall back to current interpreter
    _venv_py = pathlib.Path("D:/jarvis_env/Scripts/python.exe")
    _python  = str(_venv_py) if _venv_py.exists() else sys.executable

    # Project root so bridge.server is importable
    _root = pathlib.Path(__file__).parent.parent

    try:
        _bridge_proc = subprocess.Popen(
            [
                _python, "-m", "uvicorn",
                "bridge.server:app",
                "--host", "127.0.0.1",
                "--port", "5000",
                "--log-level", "warning",
            ],
            cwd=str(_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        atexit.register(_bridge_proc.terminate)
        logger.info("[BootManager] bridge server started (pid %d)", _bridge_proc.pid)
    except Exception as e:
        logger.error("[BootManager] bridge server failed to start (non-fatal): %s", e)


def start_autonomy_stack() -> None:
    """
    Full autonomy stack startup. Safe to call even if individual components fail.
    Each step is isolated — a failure in one doesn't prevent others from starting.
    """
    global kill_switch, watchdog, audit, judge, router, prefs, finding_engine, recon_loop

    # Step 0: Bridge server — must be up before the AI CORE WebView loads
    _start_bridge()

    # Step 1: Integrity baseline (first boot only — noop if already initialized)
    try:
        from runtime.integrity import initialize as integrity_init
        integrity_init()
        logger.info("[BootManager] integrity baseline OK")
    except Exception as e:
        logger.error("[BootManager] integrity init failed (non-fatal): %s", e)

    # Step 2: Kill switch — MUST be first autonomous component
    try:
        from runtime.kill_switch import KillSwitch
        kill_switch = KillSwitch()
        kill_switch.register_hotkey()
        logger.info("[BootManager] kill switch armed — Ctrl+Alt+Shift+K")
    except Exception as e:
        logger.error("[BootManager] kill switch init failed: %s", e)

    # Step 3: Watchdog
    try:
        from runtime.watchdog import Watchdog
        watchdog = Watchdog()
        watchdog.start()
        logger.info("[BootManager] watchdog started")
    except Exception as e:
        logger.error("[BootManager] watchdog init failed (non-fatal): %s", e)

    # Step 4: Audit log (singleton)
    try:
        from storage.audit_log import ImmutableAuditLog
        audit = ImmutableAuditLog()
        audit.append("jarvis_startup", "system")
        logger.info("[BootManager] audit log initialized")
    except Exception as e:
        logger.error("[BootManager] audit log init failed: %s", e)

    # Step 5: Intelligence layer
    try:
        from llm.local_judge import LocalJudge
        from llm.router import LLMRouter
        judge  = LocalJudge()
        router = LLMRouter()
        logger.info("[BootManager] LLM router initialized")
    except Exception as e:
        logger.error("[BootManager] LLM layer init failed (non-fatal): %s", e)

    # Step 5b: LLM pre-warm — touch both models so first user query is instant
    import config as _cfg
    if getattr(_cfg, 'LLM_PREWARM_ON_BOOT', True):
        def _prewarm():
            try:
                import requests as _req
                _req.post("http://127.0.0.1:11434/api/generate",
                    json={"model": _cfg.OLLAMA_MODEL, "prompt": ".", "stream": False,
                          "keep_alive": -1, "options": {"num_predict": 1}},
                    timeout=30)
                _req.post("http://127.0.0.1:11434/api/generate",
                    json={"model": getattr(_cfg, 'LOCAL_JUDGE_MODEL', 'phi4-mini'), "prompt": ".", "stream": False,
                          "keep_alive": -1, "options": {"num_predict": 1}},
                    timeout=15)
                logger.info("[BootManager] LLM pre-warm complete — both models hot")
            except Exception as _e:
                logger.debug(f"[BootManager] LLM pre-warm failed (non-fatal): {_e}")
        import threading as _threading
        _threading.Thread(target=_prewarm, daemon=True, name="LLMPrewarm").start()

    # Step 6: Preference engine
    try:
        from autonomy.preference_engine import PreferenceEngine
        prefs = PreferenceEngine()
        logger.info("[BootManager] preference engine initialized")
    except Exception as e:
        logger.error("[BootManager] preference engine init failed (non-fatal): %s", e)

    # Step 7: Finding engine
    try:
        from autonomy.finding_engine import FindingEngine
        finding_engine = FindingEngine()
        logger.info("[BootManager] finding engine initialized")
    except Exception as e:
        logger.error("[BootManager] finding engine init failed (non-fatal): %s", e)

    # Step 8: Recon loop — operator must explicitly enable via RECON_LOOP_ENABLED=True
    if getattr(config, "RECON_LOOP_ENABLED", False):
        try:
            from autonomy.recon_loop import ReconLoop
            recon_loop = ReconLoop()
            recon_loop.start()
            logger.info("[BootManager] autonomous recon loop ACTIVE")
            logger.info("[BootManager] daily job cap: %d", getattr(config, "RECON_MAX_DAILY_JOBS", 10))
            logger.info("[BootManager] quiet hours: %s", getattr(config, "RECON_QUIET_HOURS", []))
        except Exception as e:
            logger.error("[BootManager] recon loop init failed: %s", e)
    else:
        logger.info('[BootManager] autonomous recon loop STANDBY — say "Enable autonomous recon" to start')

    # Step 9: Job executor — processes pending recon jobs
    if getattr(config, "RECON_LOOP_ENABLED", False):
        try:
            from scheduler.job_executor import JobExecutor
            job_executor = JobExecutor()
            job_executor.start()
            logger.info("[BootManager] job executor started")
        except Exception as e:
            logger.error("[BootManager] job executor init failed (non-fatal): %s", e)

    # Step 10: Research intelligence periodic polling
    if getattr(config, "RESEARCH_ENGINE_ENABLED", False):
        try:
            import threading as _threading
            _poll_interval = getattr(config, "RESEARCH_POLL_INTERVAL", 3600)

            def _research_poll_loop():
                import time as _time
                _time.sleep(120)  # wait 2 min after boot before first poll
                while True:
                    try:
                        from runtime.kill_switch import KILL_FLAG
                        if KILL_FLAG.exists():
                            _time.sleep(60)
                            continue
                        from storage.db import get_db
                        with get_db() as _rc:
                            _rows = _rc.execute(
                                "SELECT DISTINCT target FROM scan_targets LIMIT 10"
                            ).fetchall()
                        _targets = [r[0] for r in _rows if r and r[0]]
                        from research.engine import ResearchEngine
                        _n = ResearchEngine().run(targets=_targets or None)
                        if _n > 0:
                            logger.info("[Research] %d new items fetched", _n)
                    except Exception as _re:
                        logger.debug("[Research] poll error: %s", _re)
                    _time.sleep(_poll_interval)

            _t = _threading.Thread(
                target=_research_poll_loop, daemon=True, name="research-poll"
            )
            _t.start()
            logger.info(
                "[BootManager] research poller started — interval: %ds", _poll_interval
            )
        except Exception as e:
            logger.error("[BootManager] research poller failed to start: %s", e)

    # Step 11: Self-healer — monitors internal JARVIS health
    try:
        from runtime.self_healer import SelfHealer
        _self_healer = SelfHealer()
        _self_healer.start()
        logger.info("[BootManager] self-healer started")
    except Exception as e:
        logger.error("[BootManager] self-healer init failed (non-fatal): %s", e)

    # Step 12: Threat intel correlator — cross-references CVEs against targets
    if getattr(config, "INTEL_CORRELATOR_ENABLED", False):
        try:
            from intelligence.correlator import ThreatIntelCorrelator
            _correlator = ThreatIntelCorrelator()
            _correlator.start()
            logger.info("[BootManager] threat intel correlator started")
        except Exception as e:
            logger.error("[BootManager] threat intel correlator failed (non-fatal): %s", e)
    else:
        logger.info("[BootManager] threat intel correlator STANDBY — set INTEL_CORRELATOR_ENABLED=True to activate")

    # Step 13: Hacktivity monitor — watches HackerOne public disclosures
    if getattr(config, "INTEL_HACKTIVITY_ENABLED", False):
        try:
            from intelligence.hacktivity_monitor import HacktivityMonitor
            _hacktivity = HacktivityMonitor()
            _hacktivity.start()
            logger.info("[BootManager] hacktivity monitor started")
        except Exception as e:
            logger.error("[BootManager] hacktivity monitor failed (non-fatal): %s", e)

    # Step 14: Hunt director — proposes next reconnaissance targets
    if getattr(config, "HUNT_DIRECTOR_ENABLED", False):
        try:
            from autonomy.hunt_director import HuntDirector
            _hunt_director = HuntDirector()
            _hunt_director.start()
            logger.info("[BootManager] hunt director started")
        except Exception as e:
            logger.error("[BootManager] hunt director failed (non-fatal): %s", e)
    else:
        logger.info("[BootManager] hunt director STANDBY — set HUNT_DIRECTOR_ENABLED=True to activate")

    # Step 15: Coaching engine — operator skill hints during pause windows
    if getattr(config, "COACHING_ENABLED", True):
        try:
            from intelligence.coaching_engine import CoachingEngine
            _coach = CoachingEngine()
            _coach.start()
            logger.info("[BootManager] coaching engine started")
        except Exception as e:
            logger.error("[BootManager] coaching engine failed (non-fatal): %s", e)

    # Step 16: Context predictor — preloads session context before operator sits down
    if getattr(config, "CONTEXT_PREDICTOR_ENABLED", False):
        try:
            from intelligence.context_predictor import get_context_predictor
            get_context_predictor().start()
            logger.info("[BootManager] context predictor started")
        except Exception as e:
            logger.error("[BootManager] context predictor failed (non-fatal): %s", e)

    # Summary
    try:
        stats = router.get_token_stats() if router else {}
        local_ratio = stats.get("local_ratio", 0.0) * 100
        cost        = stats.get("estimated_cost_month_usd", 0.0)
        logger.info("[AUTONOMY] Full autonomy stack online")
        logger.info("[AUTONOMY] Kill switch: Ctrl+Alt+Shift+K | flag: EMERGENCY_STOP.flag")
        logger.info("[AUTONOMY] Local LLM ratio: %.0f%% | est. monthly cost: $%.2f",
                    local_ratio, cost)
    except Exception:
        logger.info("[AUTONOMY] Full autonomy stack online")
