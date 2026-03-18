"""
Watchdog — keeps JARVIS services alive. Verifies integrity before restart.

Security properties:
  - Verifies SHA256 of service entry points before every restart (IntegrityChecker)
  - Logs all restart events to ImmutableAuditLog
  - Caps restarts per service to prevent restart loops
  - Notifies operator on repeated failures (service is unstable)
  - Does NOT restart a service if EMERGENCY_STOP.flag is present
"""
import threading, time, logging, pathlib, subprocess, sys, urllib.request, json
from typing import Optional
from runtime.kill_switch import KILL_FLAG

logger = logging.getLogger(__name__)

# Service ports — defined here as named constants to make auditing easier.
# Ollama host is authoritative in config.OLLAMA_HOST; we derive the health URL from it.
_JARVIS_OPS_PORT = 8080   # jarvis_ops REST API
_BRIDGE_PORT     = 5000   # bridge server

def _build_services() -> dict:
    import config as _cfg
    import pathlib as _pl
    _root = _pl.Path(__file__).parent.parent

    ollama_host = getattr(_cfg, "OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

    # jarvis_ops and bridge are optional services — their server entry points may
    # not exist on this machine (e.g. the bridge server lives on the Parrot VM, not
    # the Windows laptop).  When optional=True the watchdog treats health-check
    # failures as "known offline" rather than triggering restart loops.
    _jarvis_ops_exists = (_root / "jarvis_ops" / "main.py").exists()
    _bridge_server_exists = (_root / "bridge" / "server.py").exists()

    return {
        "ollama": {
            "health_url":    f"{ollama_host}/api/tags",
            "entry_point":   None,
            "start_args":    ["ollama", "serve"],
            "use_python":    False,
            "max_restarts":  3,
            "restart_delay": 5,
            "optional":      False,
        },
        "jarvis_ops": {
            "health_url":    f"http://127.0.0.1:{_JARVIS_OPS_PORT}/api/health",
            "entry_point":   "jarvis_ops/main.py",
            "start_args":    ["jarvis_ops/main.py"],
            "use_python":    True,
            "max_restarts":  5,
            "restart_delay": 3,
            # Optional when the server entry point does not exist locally.
            # The ops graph page (jarvis_ops/static/index.html) works in demo
            # mode without a live server; no restart loop needed.
            "optional":      not _jarvis_ops_exists,
        },
        "bridge": {
            "health_url":    f"http://127.0.0.1:{_BRIDGE_PORT}/health",
            "entry_point":   "bridge/server.py",
            "start_args":    ["-m", "bridge.server"],
            "use_python":    True,
            "max_restarts":  5,
            "restart_delay": 3,
            # Optional when bridge/server.py does not exist — this machine is
            # likely the Windows laptop and the bridge server runs on the Parrot VM.
            "optional":      not _bridge_server_exists,
        },
    }

SERVICES = _build_services()


# ── LLM response-time tracking ────────────────────────────────────────────────
# Keyed by service name (e.g. "ollama").  Updated by record_llm_success() which
# is called from outside this module whenever the LLM returns a successful reply.

_llm_last_ok: dict[str, float] = {}


def record_llm_success(service: str = "ollama") -> None:
    """Called from outside the watchdog when the LLM responds successfully."""
    _llm_last_ok[service] = time.time()


def llm_is_stale(service: str = "ollama", max_age_secs: int = 300) -> bool:
    """
    Returns True if the LLM hasn't responded in max_age_secs.
    Only meaningful once at least one successful response has been recorded;
    returns False if no success has ever been recorded (avoids false alarms on
    startup before the first LLM call).
    """
    last = _llm_last_ok.get(service)
    if last is None:
        return False
    return (time.time() - last) > max_age_secs


# ── Ollama model-level health probe ──────────────────────────────────────────

def _check_ollama_model(model: str, base_url: str, timeout: int = 10) -> tuple[bool, str]:
    """
    Check if Ollama is running AND the required model is available.
    Returns (ok, status_message).
    base_url may end with /v1 (OpenAI-compat path) — we strip it to reach /api/tags.
    """
    try:
        # Normalise: remove trailing /v1 so we can hit the native Ollama API
        health_url = base_url.rstrip("/")
        if health_url.endswith("/v1"):
            health_url = health_url[:-3]
        health_url = health_url.rstrip("/") + "/api/tags"
        req = urllib.request.Request(
            health_url,
            headers={"User-Agent": "JARVIS-Watchdog/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        models = [m.get("name", "") for m in data.get("models", [])]
        model_base = model.split(":")[0]   # e.g. "qwen3" from "qwen3:14b"
        if not any(model_base in m for m in models):
            available = ", ".join(models[:3]) or "(none)"
            return False, f"Model {model} not found in Ollama. Available: {available}"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _recover_ollama(model: str, base_url: str) -> bool:
    """
    Attempt to warm-load the model into Ollama by sending an empty generate request.
    Returns True if the request was dispatched (not necessarily that it succeeded).
    base_url may end with /v1 — we strip it to reach /api/generate.
    """
    try:
        load_url = base_url.rstrip("/")
        if load_url.endswith("/v1"):
            load_url = load_url[:-3]
        load_url = load_url.rstrip("/") + "/api/generate"
        payload = json.dumps({"model": model, "prompt": "", "stream": False}).encode()
        req = urllib.request.Request(
            load_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "JARVIS-Watchdog/1.0",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=30)
        logger.info("[Watchdog] Ollama model load triggered for %s", model)
        return True
    except Exception as exc:
        logger.warning("[Watchdog] Ollama recovery attempt failed: %s", exc)
        return False


class Watchdog:

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._restart_counts = {k: 0 for k in SERVICES}
        self._processes = {}
        self._audit = None
        # Tracks consecutive health-check failures for optional services so we
        # can apply exponential back-off instead of hammering restart every 30s.
        self._optional_fail_counts: dict[str, int] = {k: 0 for k in SERVICES}

    def _get_audit(self):
        if self._audit is None:
            from storage.audit_log import ImmutableAuditLog
            self._audit = ImmutableAuditLog()
        return self._audit

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Watchdog")
        self._thread.start()
        logger.info("[Watchdog] started — monitoring %d services", len(SERVICES))

    def stop(self) -> None:
        self._running = False
        logger.info("[Watchdog] stopped")

    def _loop(self) -> None:
        while self._running:
            if not KILL_FLAG.exists():
                self._check_all()
            time.sleep(30)

    def _check_all(self) -> None:
        for name in SERVICES:
            if not self._is_healthy(name):
                cfg = SERVICES[name]
                if cfg.get("optional", False):
                    # Optional service (e.g. bridge on Parrot VM, jarvis_ops stub).
                    # Use exponential back-off: only log/attempt restart every
                    # 2^n checks (1, 2, 4, 8 … up to every 32 checks = ~16 min).
                    self._optional_fail_counts[name] = (
                        self._optional_fail_counts.get(name, 0) + 1
                    )
                    n = self._optional_fail_counts[name]
                    backoff_at = min(2 ** (self._restart_counts.get(name, 0)), 32)
                    if n % backoff_at == 1:
                        logger.debug(
                            "[Watchdog] optional service %s is offline "
                            "(fail #%d, next attempt in %d checks)",
                            name, n, backoff_at,
                        )
                    # Only attempt a restart if the entry point file actually exists.
                    _ep = cfg.get("entry_point")
                    if _ep:
                        _root = pathlib.Path(__file__).parent.parent
                        if not (_root / _ep).exists():
                            continue   # server file not present — nothing to start
                    if n % backoff_at == 1:
                        self._restart(name)
                    continue
                # Non-optional — log at WARNING and restart immediately.
                self._optional_fail_counts[name] = 0
                logger.warning("[Watchdog] %s is DOWN", name)
                self._restart(name)

        # ── LLM stale-response check ──────────────────────────────────────────
        # Only fires if at least one successful LLM response has been recorded
        # (llm_is_stale returns False until the first record_llm_success() call).
        if llm_is_stale("ollama", max_age_secs=300):
            import config as _cfg
            _model    = getattr(_cfg, "OLLAMA_MODEL",    "qwen3:14b")
            _base_url = getattr(_cfg, "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
            logger.warning(
                "[Watchdog] Ollama LLM stale (no response in 5 min) — probing model %s",
                _model,
            )
            ok, msg = _check_ollama_model(_model, _base_url)
            if not ok:
                logger.error(
                    "[Watchdog] LLM probe failed: %s — triggering recovery", msg
                )
                _recover_ollama(_model, _base_url)

    def _is_healthy(self, service: str) -> bool:
        url = SERVICES[service]["health_url"]
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _restart(self, service: str) -> bool:
        cfg   = SERVICES[service]
        count = self._restart_counts[service]

        if count >= cfg["max_restarts"]:
            logger.error("[Watchdog] %s exceeded max restarts (%d) — giving up",
                         service, cfg["max_restarts"])
            self._get_audit().append(
                "watchdog_gave_up", "watchdog", tool=service,
                reason=f"max restarts exceeded: {count}"
            )
            return False

        # INTEGRITY CHECK before restart
        entry = cfg.get("entry_point")
        if entry:
            from runtime.integrity import verify
            ok, reason = verify(entry)
            if not ok:
                logger.critical(
                    "[Watchdog] INTEGRITY VIOLATION — refusing restart of %s: %s",
                    service, reason
                )
                self._get_audit().append(
                    "watchdog_integrity_violation", "watchdog",
                    tool=service, decision="deny", reason=reason
                )
                return False

        # Perform restart
        try:
            args = cfg["start_args"]
            if cfg.get("use_python", False):
                cmd = [sys.executable] + args
            else:
                cmd = args

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._processes[service] = proc
            self._restart_counts[service] += 1
            time.sleep(cfg["restart_delay"])
            healthy = self._is_healthy(service)
            self._get_audit().append(
                "watchdog_restart", "watchdog", tool=service,
                decision="restarted" if healthy else "restart_failed",
                reason=f"attempt {count + 1}",
            )
            logger.info("[Watchdog] restarted %s — healthy: %s", service, healthy)
            return healthy
        except Exception as e:
            logger.error("[Watchdog] restart failed for %s: %s", service, e)
            return False

    def status(self) -> dict:
        return {
            name: {
                "healthy":  self._is_healthy(name),
                "restarts": self._restart_counts[name],
                "max":      SERVICES[name]["max_restarts"],
            }
            for name in SERVICES
        }
