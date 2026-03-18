"""
IntegrityChecker — verifies service entry points haven't been tampered with.

Threat: An attacker who can write to the project directory replaces
jarvis_ops/main.py with malicious code. The watchdog restarts the service,
now running attacker code with JARVIS permissions.

Defense: Hash all service entry points at first boot. Store hashes in
integrity.json. Verify before every watchdog restart.
"""
import hashlib, json, logging
from pathlib import Path
from config import ROOT_DIR

logger = logging.getLogger(__name__)

INTEGRITY_FILE = ROOT_DIR / "integrity.json"

SERVICE_ENTRY_POINTS = [
    "jarvis_ops/main.py",
    "bridge/server.py",
    "main.py",
    "autonomy/recon_loop.py",
    "policy/autonomy_policy.py",
    "security/sanitizer.py",
    "storage/audit_log.py",
]


def _hash_file(path: str) -> str:
    """SHA256 of file contents."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def initialize() -> None:
    """
    Computes and stores hashes for all service entry points.
    Called ONCE at first boot. If integrity.json already exists, skips.
    """
    ifile = Path(INTEGRITY_FILE)
    if ifile.exists():
        logger.info("[Integrity] hashes already initialized")
        return
    hashes = {}
    for fp in SERVICE_ENTRY_POINTS:
        if Path(fp).exists():
            hashes[fp] = _hash_file(fp)
            logger.info("[Integrity] hashed %s → %s", fp, hashes[fp][:12])
        else:
            logger.warning("[Integrity] entry point not found: %s", fp)
    ifile.write_text(json.dumps(hashes, indent=2))
    logger.info("[Integrity] stored %d hashes", len(hashes))


def verify(path: str) -> tuple[bool, str]:
    """
    Verifies a file matches its stored hash.
    Returns (True, "ok") or (False, "reason").

    Called by watchdog before every service restart.
    """
    ifile = Path(INTEGRITY_FILE)
    if not ifile.exists():
        return True, "no integrity file — first run, skipping"
    stored = json.loads(ifile.read_text())
    if path not in stored:
        return True, f"{path} not in integrity baseline — skipping"
    if not Path(path).exists():
        return False, f"INTEGRITY ERROR: {path} does not exist"
    current = _hash_file(path)
    if current == stored[path]:
        return True, "ok"
    return False, f"INTEGRITY VIOLATION: {path} has been modified since baseline"


def update(path: str) -> None:
    """
    Updates the stored hash for a file after a legitimate update.
    Must be called manually by operator after intentional code changes.
    Cannot be called by autonomous code — operator-only action.
    """
    ifile = Path(INTEGRITY_FILE)
    stored = json.loads(ifile.read_text()) if ifile.exists() else {}
    stored[path] = _hash_file(path)
    ifile.write_text(json.dumps(stored, indent=2))
    logger.info("[Integrity] updated hash for %s", path)
