"""
security/rate_limiter.py — Per-tool outbound rate limiting.

Prevents hammering targets and getting banned from bug bounty programs.
All limits are conservative by default — operator must explicitly raise them.

Usage:
    from security.rate_limiter import rate_limiter
    if not rate_limiter.check('subfinder', domain):
        return {"ok": False, "output": "Rate limit reached. Try again in an hour.", "error": "RATE_LIMITED", "artifacts": [], "meta": {}}
    rate_limiter.record('subfinder', domain)
"""
from __future__ import annotations

import time
import threading
from collections import defaultdict

# Conservative defaults. Operator can raise via config.
DEFAULT_LIMITS: dict[str, dict] = {
    'subfinder':       {'calls': 10,  'window_secs': 3600},
    'httpx':           {'calls': 50,  'window_secs': 3600},
    'nuclei':          {'calls': 5,   'window_secs': 3600},
    'dns_lookup':      {'calls': 100, 'window_secs': 3600},
    'whois':           {'calls': 20,  'window_secs': 3600},
    'gau':             {'calls': 10,  'window_secs': 3600},
    'katana':          {'calls': 10,  'window_secs': 3600},
    'research_nvd':    {'calls': 10,  'window_secs': 3600},
    'research_h1':     {'calls': 10,  'window_secs': 3600},
    'research_github': {'calls': 20,  'window_secs': 3600},
}

_DEFAULT_FALLBACK = {'calls': 20, 'window_secs': 3600}


class RateLimiter:
    """Thread-safe per-tool sliding window rate limiter."""

    def __init__(self):
        self._lock  = threading.Lock()
        self._calls: dict[str, list[float]] = defaultdict(list)

    def _key(self, tool: str, target: str = '') -> str:
        return f"{tool}:{target}" if target else tool

    def check(self, tool: str, target: str = '') -> bool:
        """Return True if this call is within limits, False if rate-limited."""
        key    = self._key(tool, target)
        limit  = DEFAULT_LIMITS.get(tool, _DEFAULT_FALLBACK)
        now    = time.time()
        window = limit['window_secs']
        max_c  = limit['calls']
        with self._lock:
            self._calls[key] = [t for t in self._calls[key] if now - t < window]
            return len(self._calls[key]) < max_c

    def record(self, tool: str, target: str = '') -> None:
        """Record that a call was made (call AFTER check returns True)."""
        key = self._key(tool, target)
        with self._lock:
            self._calls[key].append(time.time())

    def status(self, tool: str, target: str = '') -> dict:
        """Return current usage stats for a tool."""
        key    = self._key(tool, target)
        limit  = DEFAULT_LIMITS.get(tool, _DEFAULT_FALLBACK)
        now    = time.time()
        window = limit['window_secs']
        with self._lock:
            recent = [t for t in self._calls[key] if now - t < window]
        return {
            'tool':        tool,
            'used':        len(recent),
            'limit':       limit['calls'],
            'window_secs': window,
            'remaining':   limit['calls'] - len(recent),
        }

    def all_status(self) -> list[dict]:
        """Return status for all tools that have been used."""
        now = time.time()
        result = []
        with self._lock:
            seen_tools = set()
            for key in self._calls:
                tool = key.split(':')[0]
                if tool not in seen_tools:
                    seen_tools.add(tool)
                    limit  = DEFAULT_LIMITS.get(tool, _DEFAULT_FALLBACK)
                    window = limit['window_secs']
                    recent = [t for t in self._calls[key] if now - t < window]
                    result.append({
                        'tool':      tool,
                        'used':      len(recent),
                        'limit':     limit['calls'],
                        'remaining': limit['calls'] - len(recent),
                    })
        return result


# Module-level singleton
rate_limiter = RateLimiter()
