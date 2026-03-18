from __future__ import annotations
import json
import time
import urllib.request
import urllib.parse

_NVD_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_HEADERS  = {"User-Agent": "JARVIS-Research/1.0"}
_PAGE_SZ  = 20
_MAX_PAGES = 3


def _severity_from_metrics(metrics: dict) -> str:
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key, [])
        if entries:
            data = entries[0].get("cvssData", {})
            base = data.get("baseSeverity", "").upper()
            if base in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
                return base.lower()
            score = data.get("baseScore")
            if score is not None:
                s = float(score)
                if s >= 9.0:   return "critical"
                if s >= 7.0:   return "high"
                if s >= 4.0:   return "medium"
                return "low"
    return "info"


def _parse_vulnerabilities(vulns: list) -> list[dict]:
    results = []
    for v in vulns:
        cve = v.get("cve", {})
        cve_id = cve.get("id", "")
        descs = cve.get("descriptions", [])
        title = next((d["value"] for d in descs if d.get("lang") == "en"), cve_id)
        metrics  = cve.get("metrics", {})
        severity = _severity_from_metrics(metrics)
        refs     = cve.get("references", [])
        url      = refs[0]["url"] if refs else f"https://nvd.nist.gov/vuln/detail/{cve_id}"
        results.append({
            "id":       cve_id,
            "title":    title[:400],
            "severity": severity,
            "url":      url,
            "raw":      json.dumps(cve, separators=(",", ":")),
        })
    return results


def fetch_cves(keywords: list[str], api_key: str = "") -> list[dict]:
    if not keywords:
        return []
    all_results: list[dict] = []
    keyword_str = " ".join(keywords[:5])
    for page in range(_MAX_PAGES):
        params: dict = {
            "keywordSearch":  keyword_str,
            "resultsPerPage": _PAGE_SZ,
            "startIndex":     page * _PAGE_SZ,
        }
        if api_key:
            params["apiKey"] = api_key
        url = f"{_NVD_BASE}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            break
        vulns = data.get("vulnerabilities", [])
        if not vulns:
            break
        all_results.extend(_parse_vulnerabilities(vulns))
        total = data.get("totalResults", 0)
        if (page + 1) * _PAGE_SZ >= total:
            break
        if not api_key:
            time.sleep(1)
    return all_results
