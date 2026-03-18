from __future__ import annotations
import sqlite3
import time

from storage.db import get_db


class ResearchEngine:

    def run(self, targets: list[str] | None = None) -> int:
        try:
            import config as _cfg
            api_key  = getattr(_cfg, "NVD_API_KEY", "")
            max_kw   = getattr(_cfg, "RESEARCH_MAX_KEYWORDS", 5)
        except Exception:
            api_key  = ""
            max_kw   = 5

        keywords = self._build_keywords(targets, max_kw)
        if not keywords:
            keywords = ["remote code execution", "authentication bypass"]

        try:
            cves = self._fetch_nvd(keywords, api_key=api_key)
        except Exception:
            return 0

        if not cves:
            return 0

        target_list = targets or []
        stored = 0
        for item in cves:
            try:
                affects = self._check_affects_targets(item, target_list)
                self._store_item(
                    source="nvd",
                    item_type="cve",
                    title=item.get("title", "")[:400],
                    severity=item.get("severity", "info"),
                    url=item.get("url", ""),
                    affects_targets=1 if affects else 0,
                    raw_data=item.get("raw", ""),
                )
                stored += 1
            except sqlite3.IntegrityError:
                pass
            except Exception:
                pass
        return stored

    def _build_keywords(self, targets: list[str] | None, max_kw: int) -> list[str]:
        kw = []
        if targets:
            for t in targets[:max_kw]:
                if t:
                    kw.append(t.strip())
        return kw[:max_kw]

    def _fetch_nvd(self, keywords: list[str], api_key: str = "") -> list[dict]:
        from research.sources.nvd import fetch_cves
        results = []
        for kw in keywords:
            try:
                batch = fetch_cves([kw], api_key=api_key)
                results.extend(batch)
            except Exception:
                pass
            if not api_key:
                time.sleep(1)
        return results

    def _check_affects_targets(self, item: dict, targets: list[str]) -> bool:
        if not targets:
            return False
        title = (item.get("title") or "").lower()
        url   = (item.get("url")   or "").lower()
        raw   = (item.get("raw")   or "").lower()
        for t in targets:
            if not t:
                continue
            tl = t.lower()
            if tl in title or tl in url or tl in raw:
                return True
        return False

    def _store_item(self, source: str, item_type: str, title: str,
                    severity: str, url: str, affects_targets: int,
                    raw_data: str) -> None:
        with get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO research_items "
                "(source, item_type, title, severity, url, affects_targets, raw_data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source, item_type, title, severity, url, affects_targets, raw_data),
            )

    def get_unactioned(self, limit: int = 10) -> list[dict]:
        try:
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT id, source, item_type, title, severity, url, "
                    "affects_targets, actioned, created_at "
                    "FROM research_items WHERE actioned=0 "
                    "ORDER BY "
                    "  CASE severity "
                    "    WHEN 'critical' THEN 4 "
                    "    WHEN 'high'     THEN 3 "
                    "    WHEN 'medium'   THEN 2 "
                    "    WHEN 'low'      THEN 1 "
                    "    ELSE 0 END DESC, "
                    "created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def mark_actioned(self, item_id: int) -> None:
        try:
            with get_db() as conn:
                conn.execute(
                    "UPDATE research_items SET actioned=1 WHERE id=?",
                    (item_id,),
                )
        except Exception:
            pass
