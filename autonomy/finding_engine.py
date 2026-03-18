"""
Finding Engine — from raw nuclei output to report-ready finding.

Security properties:
  - All raw tool output sanitized before LLM ingestion (prompt injection defense)
  - Verification is READ-ONLY only — no payload sending in autonomous mode
  - Reports encrypted at rest via Fernet (AES-128-CBC) when cryptography is installed
  - Secrets stripped from report evidence via SecuritySanitizer.sanitize_for_report()
  - All findings logged to ImmutableAuditLog for responsible disclosure provenance
  - Quiet hours respected for notifications
"""
import hashlib, json, logging, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from config import ROOT_DIR

logger = logging.getLogger(__name__)

REPORTS_DIR = ROOT_DIR / "reports_encrypted"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Active-exploit template markers — verification of these requires operator
_ACTIVE_ONLY_MARKERS = {
    "rce", "sqli-active", "xss-reflected", "ssti", "xxe-active",
    "ssrf-active", "log4j", "jndi", "deserialization", "intrusive",
}


class FindingEngine:

    def __init__(self):
        self._audit = None
        self._judge = None

    def _get_audit(self):
        if self._audit is None:
            from storage.audit_log import ImmutableAuditLog
            self._audit = ImmutableAuditLog()
        return self._audit

    def _get_judge(self):
        if self._judge is None:
            from llm.local_judge import LocalJudge
            self._judge = LocalJudge()
        return self._judge

    def process_raw_finding(self, raw: dict, program: dict) -> dict:
        """
        Full pipeline for one nuclei output line.
        Returns enriched finding with status, report_path, notification_time.
        """
        program_id = program.get("id") or program.get("program_id")

        from security.sanitizer import sanitize_for_report
        safe_raw = {k: sanitize_for_report(str(v)) for k, v in raw.items()}

        # 1. Deduplication
        if self.deduplicate(safe_raw, program_id):
            self._get_audit().append(
                "finding_duplicate", "finding_engine",
                target=safe_raw.get("host"),
                tool=safe_raw.get("template_id"),
                decision="skipped",
            )
            return {"status": "duplicate", "finding": safe_raw}

        # 2. Score with LocalJudge
        score = self._get_judge().score_finding(safe_raw)

        # 3. Verify (read-only)
        verification = self.verify_finding(safe_raw)

        # 4. Store in DB
        finding_id = self._store_finding(safe_raw, program_id, score, verification)

        # 5. Draft report
        report_path = self.draft_report(safe_raw, program, finding_id)

        # 6. Schedule notification
        notif_time = self.schedule_notification(safe_raw, score, program_id)

        # 7. Audit log
        self._get_audit().append(
            "finding_processed", "finding_engine",
            target=safe_raw.get("host"),
            tool=safe_raw.get("template_id"),
            decision="processed",
            program_id=program_id,
        )

        return {
            "status":            "processed",
            "finding_id":        finding_id,
            "score":             score,
            "verified":          verification.get("verified"),
            "report_path":       report_path,
            "notification_time": notif_time,
        }

    def deduplicate(self, finding: dict, program_id: int) -> bool:
        from storage.db import get_db
        try:
            with get_db() as conn:
                row = conn.execute("""
                    SELECT id FROM findings_canonical
                    WHERE program_id=? AND template_id=? AND host=?
                    AND status != 'false_positive'
                    LIMIT 1
                """, (program_id,
                      finding.get("template_id", ""),
                      finding.get("host", ""))).fetchone()
                return row is not None
        except Exception:
            return False

    def verify_finding(self, finding: dict) -> dict:
        """
        READ-ONLY VERIFICATION ONLY. Hard coded — cannot be changed by config.

        Permitted:
          HEAD request to verify host is still alive
          Check for header presence

        NEVER in autonomous mode:
          Sending any payloads
          POST requests
          Any action that modifies server state
        """
        host     = finding.get("host", "")
        template = finding.get("template_id", "").lower()

        # Safety classifier — defer anything that requires active payloads
        if any(marker in template for marker in _ACTIVE_ONLY_MARKERS):
            return {
                "verified":       False,
                "method":         "deferred_active",
                "evidence":       "active verification requires operator",
                "needs_operator": True,
            }

        # For simple exposure/misconfiguration: HEAD request only
        if host and (host.startswith("http://") or host.startswith("https://")):
            try:
                from security.sanitizer import validate_url
                validate_url(host)
                import urllib.request
                req = urllib.request.Request(host, method="HEAD")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return {
                        "verified": resp.status in (200, 301, 302, 403),
                        "method":   "head_request",
                        "evidence": f"HTTP {resp.status}",
                        "needs_operator": False,
                    }
            except Exception as e:
                return {
                    "verified":       False,
                    "method":         "head_failed",
                    "evidence":       str(e)[:100],
                    "needs_operator": False,
                }

        return {
            "verified":       False,
            "method":         "no_safe_method",
            "evidence":       "",
            "needs_operator": False,
        }

    def draft_report(self, finding: dict, program: dict, finding_id: int) -> str:
        """
        Drafts a complete HackerOne/Bugcrowd report.
        Evidence section has secrets stripped.
        Report saved encrypted at rest.
        Returns path to the report file.
        """
        from security.sanitizer import sanitize_for_report

        title     = finding.get("title", "Vulnerability Found")
        severity  = finding.get("severity", "medium").title()
        host      = finding.get("host", "unknown")
        template  = finding.get("template_id", "")
        ts        = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prog_name = program.get("name", "Program")
        safe_evidence = sanitize_for_report(finding.get("raw_output", ""))
        cvss = self.calculate_cvss(finding)

        report = (
            f"# [{severity}] {title} — {host}\n\n"
            f"**Program:** {prog_name}\n"
            f"**Severity:** {severity}\n"
            f"**CVSS:** {cvss}\n"
            f"**Asset:** {host}\n"
            f"**Template:** {template}\n"
            f"**Discovered:** {ts}\n"
            f"**Finding ID:** {finding_id}\n\n"
            f"## Summary\n{self._generate_summary(finding)}\n\n"
            f"## Steps to Reproduce\n"
            f"1. Navigate to `{host}`\n"
            f"2. {self._generate_repro_steps(finding)}\n\n"
            f"## Impact\n{self._generate_impact(finding)}\n\n"
            f"## Remediation\n{self._generate_remediation(finding)}\n\n"
            f"## Evidence\n```\n{safe_evidence[:2000]}\n```\n\n"
            f"---\n"
            f"*Report generated by JARVIS autonomous finding engine.*\n"
            f"*Verify all details before submission.*\n"
        )

        safe_filename = re.sub(r"[^\w\-_.]", "_", f"{prog_name}_{template}_{ts}.md")
        report_path = str(REPORTS_DIR / safe_filename)
        self._save_report(report, report_path)
        return report_path

    def _save_report(self, content: str, path: str) -> None:
        try:
            from cryptography.fernet import Fernet
            from security.secrets import load_secret, store_secret
            key = load_secret("JARVIS_REPORT_KEY")
            if not key:
                key = Fernet.generate_key().decode()
                store_secret("JARVIS_REPORT_KEY", key)
            f = Fernet(key.encode() if isinstance(key, str) else key)
            Path(path + ".enc").write_bytes(f.encrypt(content.encode()))
        except ImportError:
            logger.warning("[FindingEngine] cryptography not installed — report unencrypted")
            Path(path).write_text(content, encoding="utf-8")
        except Exception as e:
            logger.error("[FindingEngine] encryption failed: %s — report unencrypted", e)
            Path(path).write_text(content, encoding="utf-8")

    def _store_finding(
        self, finding: dict, program_id: int, score: dict, verification: dict
    ) -> int:
        from storage.db import get_db
        try:
            with get_db() as conn:
                cur = conn.execute("""
                    INSERT INTO findings_canonical
                    (program_id, title, severity, host, template_id, matched_at,
                     raw_output, status, bounty_potential, priority_score, verified,
                     created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """, (
                    program_id,
                    finding.get("title", ""),
                    finding.get("severity", "info"),
                    finding.get("host", ""),
                    finding.get("template_id", ""),
                    finding.get("matched_at", ""),
                    finding.get("raw_output", "")[:5000],
                    "verified" if verification.get("verified") else "unverified",
                    score.get("bounty_potential", "low"),
                    float(score.get("priority_score", 0)),
                    1 if verification.get("verified") else 0,
                ))
                return cur.lastrowid
        except Exception as e:
            logger.error("[FindingEngine] store finding error: %s", e)
            return -1

    def calculate_cvss(self, finding: dict) -> str:
        severity = finding.get("severity", "").lower()
        tmpl     = finding.get("template_id", "").lower()
        _CVE_MAP = {
            "cve-2021-44228": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
            "cve-2022-22965": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        }
        for cve, vec in _CVE_MAP.items():
            if cve in tmpl:
                return vec
        return {
            "critical": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "high":     "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            "medium":   "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:L/A:N",
            "low":      "CVSS:3.1/AV:N/AC:H/PR:L/UI:R/S:U/C:L/I:N/A:N",
            "info":     "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N",
        }.get(severity, "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:L/A:N")

    def _generate_summary(self, finding: dict) -> str:
        severity = finding.get("severity", "").lower()
        title    = finding.get("title", "vulnerability")
        host     = finding.get("host", "the target")
        return (
            f"A {severity}-severity {title} was identified on {host}. "
            f"This vulnerability may allow an attacker to compromise the "
            f"confidentiality, integrity, or availability of the affected asset. "
            f"Immediate remediation is recommended."
        )

    def _generate_repro_steps(self, finding: dict) -> str:
        template = finding.get("template_id", "").lower()
        matched  = finding.get("matched_at", "the target URL")
        if "cors" in template:
            return (
                f"Send a request to `{matched}` with header `Origin: https://evil.com`. "
                f"Observe that the response includes "
                f"`Access-Control-Allow-Origin: https://evil.com`."
            )
        if "takeover" in template:
            return (
                f"Observe that `{matched}` returns a domain takeover indicator "
                f"(CNAME pointing to unclaimed cloud service). Claim the unclaimed resource."
            )
        if "exposure" in template or "config" in template:
            return f"Navigate to `{matched}`. Observe that sensitive data is exposed."
        return (
            f"Navigate to `{matched}`. Observe the vulnerability "
            f"as described in the evidence section."
        )

    def _generate_impact(self, finding: dict) -> str:
        severity = finding.get("severity", "").lower()
        return {
            "critical": "An unauthenticated remote attacker could achieve full system compromise, exfiltrate all data, or gain persistent access.",
            "high":     "An attacker could gain unauthorized access to sensitive data or functionality, potentially compromising user accounts or backend systems.",
            "medium":   "An attacker could gain access to information that aids further attacks or perform actions with limited impact.",
            "low":      "Limited impact. This issue provides information to an attacker that could assist in crafting more targeted attacks.",
            "info":     "Informational finding. No direct impact, but indicates potential security hygiene issues.",
        }.get(severity, "An attacker may be able to exploit this vulnerability to compromise the target.")

    def _generate_remediation(self, finding: dict) -> str:
        template = finding.get("template_id", "").lower()
        if "cors" in template:
            return "Restrict `Access-Control-Allow-Origin` to explicitly trusted origins. Never use `*` for authenticated endpoints."
        if "takeover" in template:
            return "Remove or update the dangling DNS CNAME record. Claim or delete the referenced cloud resource."
        if "exposure" in template or "config" in template:
            return "Remove or restrict access to the exposed file. Ensure sensitive files are not accessible from the web root."
        if "cve" in template:
            return "Apply the vendor-recommended patch for this CVE. Refer to the official security advisory."
        return "Apply defense-in-depth: update dependencies, restrict access, implement input validation, and review security configurations."

    def schedule_notification(
        self, finding: dict, score: dict, program_id: int
    ) -> Optional[str]:
        """
        Timing rules for operator notifications.
        Critical: immediate. High: next 8am if quiet hours. Medium/low: morning briefing.
        """
        import config
        severity    = finding.get("severity", "").lower()
        quiet_hours = getattr(config, "RECON_QUIET_HOURS", [(22, 8)])
        h           = datetime.now().hour

        def _in_quiet() -> bool:
            for (start, end) in quiet_hours:
                if start > end:
                    if h >= start or h < end:
                        return True
                else:
                    if start <= h < end:
                        return True
            return False

        if severity == "critical":
            return datetime.now(timezone.utc).isoformat()  # immediate
        if severity == "high":
            if _in_quiet():
                next_morning = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0)
                return next_morning.isoformat()
            return datetime.now(timezone.utc).isoformat()
        return None  # included in next morning briefing
