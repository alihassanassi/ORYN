"""research/sources/shodan.py — Shodan exposure monitoring.

Requires SHODAN_API_KEY in .env.
Without a key: returns empty list silently (non-fatal).
Free tier: limited search credits — queries active program domains only.
"""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.parse

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.shodan.io/shodan/host/search"


class ShodanSource:
    """Queries Shodan for exposed services on active program domains."""

    def __init__(self):
        self._seen: set[str] = set()

    def _get_api_key(self) -> str:
        import os
        return os.environ.get("SHODAN_API_KEY", "")

    def _get_active_domains(self) -> list[str]:
        """Returns scope domains from the active program, capped at 3."""
        try:
            from storage.db import get_db
            import json as _json
            with get_db() as conn:
                row = conn.execute(
                    "SELECT scope_domains FROM programs WHERE status='active' LIMIT 1"
                ).fetchone()
            if row:
                domains = _json.loads(row[0] or "[]")
                return [d.lstrip("*.") for d in domains if d][:3]
        except Exception:
            pass
        return []

    def fetch(self) -> list[dict]:
        api_key = self._get_api_key()
        if not api_key:
            return []  # silent skip — no key, no query

        domains = self._get_active_domains()
        if not domains:
            return []

        items: list[dict] = []
        for domain in domains:
            try:
                query = f"hostname:{domain}"
                params = urllib.parse.urlencode({
                    "query": query,
                    "key":   api_key,
                    "page":  1,
                })
                req = urllib.request.Request(
                    f"{_BASE_URL}?{params}",
                    headers={"User-Agent": "JARVIS-Research/1.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read().decode("utf-8"))
            except Exception as exc:
                logger.debug("[Shodan] fetch error for %s: %s", domain, exc)
                continue

            for match in data.get("matches", [])[:5]:
                ip      = match.get("ip_str", "")
                port    = match.get("port", "")
                product = match.get("product", "")
                key_id  = f"{ip}:{port}"
                if key_id in self._seen:
                    continue
                self._seen.add(key_id)
                title = f"Shodan: {domain} — {ip}:{port} {product}".strip()
                items.append({
                    "type":            "exposure",
                    "title":           title[:300],
                    "severity":        "info",
                    "details":         f"Exposed service on {domain}: port {port} ({product})",
                    "url":             f"https://www.shodan.io/host/{ip}",
                    "affects_targets": True,
                    "raw":             {"ip": ip, "port": port, "domain": domain,
                                        "product": product},
                })
        return items
