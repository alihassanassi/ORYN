"""research/sources/github.py — GitHub Security Advisory Database feed.

Uses the GitHub public advisory API (no auth needed, 60 req/hr unauthenticated).
Set GITHUB_TOKEN in .env for 5000 req/hr.
"""
from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.github.com/advisories"
_HEADERS  = {
    "User-Agent": "JARVIS-Research/1.0",
    "Accept":     "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

_SEV_MAP = {
    "CRITICAL": "critical",
    "HIGH":     "high",
    "MODERATE": "medium",
    "LOW":      "low",
}


class GitHubSource:
    """Fetches recent GitHub Security Advisories (GHSA)."""

    def __init__(self):
        self._seen: set[str] = set()

    def fetch(self) -> list[dict]:
        try:
            import os
            token = os.environ.get("GITHUB_TOKEN", "")
            headers = dict(_HEADERS)
            if token:
                headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(
                f"{_BASE_URL}?per_page=20&type=reviewed",
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                advisories = json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            logger.debug("[GitHub] fetch error: %s", exc)
            return []

        items: list[dict] = []
        for adv in (advisories if isinstance(advisories, list) else []):
            ghsa_id = adv.get("ghsa_id", "")
            if ghsa_id in self._seen:
                continue
            self._seen.add(ghsa_id)
            severity = _SEV_MAP.get(
                (adv.get("severity") or "LOW").upper(), "low"
            )
            title   = adv.get("summary") or ghsa_id
            cve_id  = adv.get("cve_id") or ""
            url     = adv.get("html_url") or f"https://github.com/advisories/{ghsa_id}"
            items.append({
                "type":            "cve" if cve_id else "advisory",
                "title":           (cve_id or ghsa_id) + ": " + title[:200],
                "severity":        severity,
                "details":         title[:300],
                "url":             url,
                "affects_targets": False,
                "raw":             {"ghsa_id": ghsa_id, "cve_id": cve_id,
                                    "ecosystems": [v.get("package", {}).get("ecosystem", "")
                                                   for v in adv.get("vulnerabilities", [])]},
            })
        return items
