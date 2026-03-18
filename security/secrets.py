"""
SecretManager — encrypted storage for API keys and credentials.

Threat: config.py is plaintext on disk, synced to OneDrive.
Any API key in config.py is exposed to OneDrive, cloud sync,
anyone with filesystem access.

Defense: Windows DPAPI via keyring. Secrets encrypted with the
current Windows user's credentials. Decrypted only into memory.
Never written to logs, reports, or the actions table.
"""
import logging
logger = logging.getLogger(__name__)

try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False
    logger.warning("[SecretManager] keyring not installed — secrets not encrypted")

SERVICE_NAME = "JARVIS_LAB"

_KNOWN_SECRETS = [
    "HACKERONE_API_KEY",
    "BUGCROWD_API_KEY",
    "SHODAN_API_KEY",
    "GITHUB_TOKEN",
    "JARVIS_TOKEN",       # bridge auth token
    "JARVIS_OPS_TOKEN",   # OPS backend auth token
    "ELEVENLABS_API_KEY", # ElevenLabs TTS
]


def store_secret(name: str, value: str) -> None:
    """
    Encrypts and stores a secret using DPAPI.
    Call this once when setting up credentials.
    Never call this with a value sourced from tool output or LLM.
    """
    if name not in _KNOWN_SECRETS:
        raise ValueError(f"Unknown secret name: {name}. Add to _KNOWN_SECRETS first.")
    if not _KEYRING_AVAILABLE:
        raise RuntimeError("keyring not installed — pip install keyring")
    keyring.set_password(SERVICE_NAME, name, value)
    logger.info("[SecretManager] stored secret: %s", name)


def load_secret(name: str, fallback: str = None) -> str | None:
    """
    Decrypts and returns a secret into memory only.
    Returns fallback if not found (for graceful degradation).
    NEVER logs the returned value.
    """
    if _KEYRING_AVAILABLE:
        val = keyring.get_password(SERVICE_NAME, name)
        if val:
            return val
    # Try environment variable as fallback (for CI/CD)
    import os
    env_val = os.environ.get(name)
    if env_val:
        return env_val
    if fallback is not None:
        return fallback
    logger.warning("[SecretManager] secret not found: %s", name)
    return None


def secret_is_configured(name: str) -> bool:
    """Check if a secret exists without loading its value."""
    return load_secret(name) is not None
