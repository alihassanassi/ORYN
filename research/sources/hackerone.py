"""research/sources/hackerone.py — HackerOne disclosed reports feed.

Uses HackerOne's public hacktivity JSON endpoint.
No API key required for public disclosed reports.
"""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.parse

logger = logging.getLogger(__name__)

_BASE_URL = "https://hackerone.com/hacktivity.json"
_HEADERS  = {"User-Agent": "JARVIS-Research/1.0", "Accept": "application/json"}


class HackerOneSource:
    """Fetches recent HackerOne publicly disclosed reports."""

    def __init__(self):
        self._seen: set[str] = set()

    def fetch(self) -> list[dict]:
        try:
            params = urllib.parse.urlencode({
                "querystring":  "",
                "only_undisclosed": 0,
                "order_direction": "DESC",
                "order_field":     "latest_disclosable_activity_at",
                "followed_only":   False,
                "collaboration":   False,
                "hacker_published": False,
                "page": 1,
            })
            req = urllib.request.Request(
                f"{_BASE_URL}?{params}", headers=_HEADERS
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            logger.debug("[HackerOne] fetch error: %s", exc)
            return []

        items: list[dict] = []
        reports = raw.get("results", []) if isinstance(raw, dict) else []
        for rep in reports[:20]:
            rid = str(rep.get("id", ""))
            if rid in self._seen:
                continue
            self._seen.add(rid)
            severity = (rep.get("severity_rating") or "info").lower()
            if severity not in ("critical", "high", "medium", "low", "none", "info"):
                severity = "info"
            if severity == "none":
                severity = "info"
            title = rep.get("title") or "Untitled report"
            url = f"https://hackerone.com/reports/{rid}" if rid else ""
            items.append({
                "type":            "bounty_finding",
                "title":           title[:300],
                "severity":        severity,
                "details":         title,
                "url":             url,
                "affects_targets": False,
                "raw":             {"id": rid, "program": rep.get("team", {}).get("handle", "")},
            })
        return items
