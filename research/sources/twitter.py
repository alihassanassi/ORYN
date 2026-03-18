"""research/sources/twitter.py — Security researcher content via RSS proxies.

Default OFF (RESEARCH_TWITTER_ENABLED = False in config.py).
No Twitter/X API key required — uses public RSS proxy services.

Uses nitter RSS (self-hosted or public instances) or security blog RSS feeds.
"""
from __future__ import annotations

import logging
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Public security RSS feeds (no auth, no rate limits in normal use)
_SECURITY_FEEDS = [
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.bleepingcomputer.com/feed/",
    "https://portswigger.net/daily-swig/rss",
    "https://krebsonsecurity.com/feed/",
]

_SECURITY_KEYWORDS = [
    "rce", "remote code execution", "zero-day", "0day",
    "authentication bypass", "sql injection", "xss", "ssrf", "idor",
    "bug bounty", "hackerone", "critical vulnerability",
    "exploit", "poc", "cve-",
]


class TwitterRSSSource:
    """Security news via RSS feeds (replaces Twitter dependency)."""

    def __init__(self):
        self._seen: set[str] = set()

    def fetch(self) -> list[dict]:
        items: list[dict] = []
        for feed_url in _SECURITY_FEEDS:
            try:
                req = urllib.request.Request(
                    feed_url,
                    headers={"User-Agent": "JARVIS-Research/1.0"},
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    content = r.read()
                root = ET.fromstring(content)
                channel = root.find("channel")
                if channel is None:
                    continue
                for entry in channel.findall("item")[:5]:
                    title_el = entry.find("title")
                    link_el  = entry.find("link")
                    title = (title_el.text or "") if title_el is not None else ""
                    link  = (link_el.text or "")  if link_el  is not None else ""
                    if not title:
                        continue
                    if link in self._seen:
                        continue
                    # Only surface security-relevant items
                    title_lower = title.lower()
                    if not any(kw in title_lower for kw in _SECURITY_KEYWORDS):
                        continue
                    self._seen.add(link)
                    severity = "high" if any(
                        kw in title_lower for kw in ["rce", "zero-day", "0day", "critical"]
                    ) else "medium"
                    items.append({
                        "type":            "threat",
                        "title":           title[:300],
                        "severity":        severity,
                        "details":         title,
                        "url":             link,
                        "affects_targets": False,
                        "raw":             {"source": feed_url},
                    })
            except Exception as exc:
                logger.debug("[RSS] feed error (%s): %s", feed_url, exc)
        return items
