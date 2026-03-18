"""
scheduler/job_executor.py — Recon pipeline job worker.

Polls DB for pending jobs, executes subfinder → httpx → nuclei in sequence,
feeds findings to FindingEngine. Runs on a daemon thread started by boot_manager.

Security properties:
  - Kill switch checked every poll cycle (filesystem-based, cannot be bypassed in Python)
  - All tool calls go through tools/network_tools.py which enforces BLOCKED_COMMANDS
  - Nuclei strips intrusive/dos/bruteforce/rce-active tags before execution
  - Results feed through FindingEngine which applies sanitization + deduplication
  - Max concurrent jobs enforced (from config.RECON_MAX_CONCURRENT)

Schema note: scan_targets uses (project TEXT, target TEXT, notes, created_at) —
no program_id column. We derive a project name as "program_<id>" for grouping.
"""
from __future__ import annotations
import logging
import threading
import time

logger = logging.getLogger(__name__)


class JobExecutor:
    POLL_INTERVAL = 30  # seconds between DB polls

    def __init__(self):
        self._running = False
        self._thread  = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="JobExecutor"
        )
        self._thread.start()
        logger.info("[JobExecutor] started — polling every %ds", self.POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        time.sleep(15)  # give the main process time to settle
        while self._running:
            try:
                self._process_pending()
            except Exception as e:
                logger.error("[JobExecutor] loop error: %s", e)
            time.sleep(self.POLL_INTERVAL)

    def _process_pending(self) -> None:
        from runtime.kill_switch import KILL_FLAG
        if KILL_FLAG.exists():
            return

        from scheduler.recon_scheduler import get_pending_jobs, mark_job_running, mark_job_complete
        jobs = get_pending_jobs(limit=2)  # honour max_concurrent

        for job in jobs:
            if KILL_FLAG.exists():
                break
            try:
                mark_job_running(job["id"])
                self._execute_job(job)
                mark_job_complete(job["id"], "completed")
            except Exception as e:
                logger.error("[JobExecutor] job %d failed: %s", job["id"], e)
                mark_job_complete(job["id"], "failed")

    def _execute_job(self, job: dict) -> None:
        domain     = job["domain"]
        program_id = job["program_id"]

        logger.info("[JobExecutor] executing job %d: %s", job["id"], domain)

        # Stage 1: Subdomain discovery
        from tools.network_tools import tool_run_subfinder, tool_run_httpx, tool_run_nuclei
        sub_output = tool_run_subfinder(domain)
        subdomains = [l for l in sub_output.splitlines() if l.strip() and not l.startswith("subfinder")]

        # Save discovered subdomains to scan_targets
        if subdomains:
            self._save_subdomains(domain, subdomains, program_id)

        # Stage 2: Live host check
        if not subdomains:
            targets_str = domain
        else:
            targets_str = "\n".join(subdomains[:50])  # cap to avoid hammering httpx

        httpx_output = tool_run_httpx(targets_str)
        live_hosts = [l for l in httpx_output.splitlines() if l.strip() and "http" in l.lower()]

        if not live_hosts:
            logger.info("[JobExecutor] no live hosts for %s", domain)
            return

        # Stage 3: Vulnerability scan
        live_str = "\n".join(live_hosts[:20])  # cap nuclei targets
        nuclei_output = tool_run_nuclei(live_str, template_tags="cves,exposed-panels,misconfigs")

        # Stage 4: Parse and feed findings
        if nuclei_output and not nuclei_output.startswith("nuclei not installed"):
            self._process_findings(nuclei_output, program_id, domain)

    def _save_subdomains(self, parent: str, subdomains: list[str], program_id: int) -> None:
        """
        Save discovered subdomains into scan_targets.
        Schema: (id, project TEXT, target TEXT, notes TEXT, created_at TEXT)
        No program_id column — use project name derived from program_id.
        """
        from storage.db import get_db
        # Derive a stable project-name string from the program_id
        project_name = f"program_{program_id}"
        try:
            with get_db() as conn:
                for sub in subdomains:
                    sub = sub.strip()
                    if not sub:
                        continue
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO scan_targets "
                            "(project, target, notes, created_at) "
                            "VALUES (?, ?, ?, datetime('now'))",
                            (project_name, sub, f"discovered via subfinder for {parent}")
                        )
                    except Exception:
                        pass
            logger.info("[JobExecutor] saved %d subdomains for %s", len(subdomains), parent)
        except Exception as e:
            logger.warning("[JobExecutor] subdomain save error: %s", e)

    def _process_findings(self, nuclei_output: str, program_id: int, domain: str) -> None:
        """Parse nuclei output and feed each finding through FindingEngine."""
        from autonomy.finding_engine import FindingEngine
        engine = FindingEngine()
        program = {"id": program_id, "name": f"program_{program_id}"}

        for line in nuclei_output.splitlines():
            if not line.strip() or "[" not in line:
                continue
            try:
                raw = self._parse_nuclei_line(line, domain)
                if raw:
                    engine.process_raw_finding(raw, program)
            except Exception as e:
                logger.debug("[JobExecutor] finding parse error: %s", e)

    @staticmethod
    def _parse_nuclei_line(line: str, domain: str) -> dict | None:
        """
        Parse a nuclei output line into a finding dict.

        Nuclei v2/v3 text format:
          [template-id] [protocol] [severity] https://... [matcher-name]
        Older/simple format:
          [template-id] [severity] https://...

        Strategy: extract template-id from the first bracket, scan for a
        known severity keyword in any subsequent bracket, then grab the URL.
        """
        import re
        _SEVERITIES = ("critical", "high", "medium", "low", "info")
        # template-id is always the first bracket
        id_m = re.match(r"\[([^\]]+)\]", line)
        if not id_m:
            return None
        template_id = id_m.group(1).strip()
        # Find a severity-valued bracket anywhere in the line
        sev_m = re.search(
            r"\[(critical|high|medium|low|info)\]", line, re.IGNORECASE
        )
        severity = sev_m.group(1).lower() if sev_m else "info"
        # URL is the first https?:// token
        url_m = re.search(r"(https?://\S+)", line)
        if not url_m:
            return None
        host = url_m.group(1).rstrip("]")  # strip trailing bracket if stuck
        return {
            "template_id": template_id,
            "severity":    severity,
            "host":        host,
            "title":       f"{template_id} on {host}",
            "raw_output":  line,
        }
