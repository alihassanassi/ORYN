"""
autonomy/strategy.py — Bug Bounty Mission Tracker and Strategy Engine.

Tracks the current mission: which target is active, what recon stages have
been completed, and what the next recommended action is.

No imports from workers, voice, or GUI layers.
"""
from __future__ import annotations
import dataclasses
import logging
from enum import Enum

logger = logging.getLogger(__name__)


# ── Recon stage progression ───────────────────────────────────────────────────

class ReconStage(str, Enum):
    DISCOVERY      = "discovery"       # subfinder / amass
    LIVE_CHECK     = "live_check"      # httpx
    CRAWL          = "crawl"           # katana / gau
    VULN_SCAN      = "vuln_scan"       # nuclei
    FINDING_TRIAGE = "finding_triage"  # review findings
    REPORT_DRAFT   = "report_draft"    # draft HackerOne report


# ── Mission state dataclass ───────────────────────────────────────────────────

@dataclasses.dataclass
class MissionState:
    target:      str
    program:     str
    stage:       ReconStage
    subdomains:  int = 0
    live_hosts:  int = 0
    findings:    int = 0
    started_at:  str = ""
    last_action: str = ""
    notes:       str = ""


# ── Strategy engine ───────────────────────────────────────────────────────────

class StrategyEngine:
    """
    Bug bounty mission tracker and next-action recommender.
    Reads DB state to determine what stage we're at and what to do next.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def get_current_mission(self, project: str | None = None) -> MissionState | None:
        """
        Read scan_targets to get the most recently added target for the project.
        Count subdomains (all targets under main domain) and findings.
        Infer stage based on counts.
        Returns MissionState or None if no targets exist.
        """
        try:
            from storage.db import _db, get_active_project  # type: ignore
            if project is None:
                project = get_active_project()

            # Most recently added target for this project
            row = _db(
                "SELECT id, target, notes, created_at "
                "FROM scan_targets WHERE project=? ORDER BY id DESC LIMIT 1",
                (project,),
                fetch="one",
            )
            if row is None:
                return None

            main_target  = row["target"]
            started_at   = row["created_at"] or ""
            notes        = row["notes"] or ""

            # Count subdomains: all scan_targets whose target contains the main domain
            # (includes the root itself)
            subdomain_rows = _db(
                "SELECT COUNT(*) as cnt FROM scan_targets "
                "WHERE project=? AND target LIKE ?",
                (project, f"%{main_target}%"),
                fetch="one",
            )
            subdomains = subdomain_rows["cnt"] if subdomain_rows else 0

            # live_hosts: we don't have a dedicated column; approximate as subdomains
            # that have been explicitly saved post-httpx (tagged "live" in notes).
            live_rows = _db(
                "SELECT COUNT(*) as cnt FROM scan_targets "
                "WHERE project=? AND notes LIKE ?",
                (project, "%live%"),
                fetch="one",
            )
            live_hosts = live_rows["cnt"] if live_rows else 0

            # findings count for this project
            finding_rows = _db(
                "SELECT COUNT(*) as cnt FROM findings WHERE project=?",
                (project,),
                fetch="one",
            )
            findings = finding_rows["cnt"] if finding_rows else 0

            stage = self._infer_stage(subdomains, live_hosts, findings)

            return MissionState(
                target=main_target,
                program=project,
                stage=stage,
                subdomains=subdomains,
                live_hosts=live_hosts,
                findings=findings,
                started_at=started_at,
                notes=notes,
            )

        except Exception as exc:
            logger.error("[StrategyEngine] get_current_mission error: %s", exc)
            return None

    def recommend_next_action(self, state: MissionState) -> str:
        """Return a natural-language recommendation based on current stage."""
        stage = state.stage
        if stage == ReconStage.DISCOVERY:
            return f"Run subfinder on {state.target} to enumerate subdomains."
        elif stage == ReconStage.LIVE_CHECK:
            return (
                f"Run httpx against {state.subdomains} discovered subdomain(s) "
                f"to identify live hosts."
            )
        elif stage == ReconStage.CRAWL:
            return f"Crawl {state.live_hosts} live host(s) with katana to map attack surface."
        elif stage == ReconStage.VULN_SCAN:
            return (
                f"Run nuclei against {state.live_hosts} live host(s) with safe templates."
            )
        elif stage == ReconStage.FINDING_TRIAGE:
            return (
                f"You have {state.findings} finding(s) waiting for review. "
                f"Start with the highest severity."
            )
        else:  # REPORT_DRAFT
            return "Draft a HackerOne report for your top finding."

    def get_strategy_briefing(
        self, state: MissionState, persona: str = "jarvis"
    ) -> str:
        """
        Return a 2-3 sentence natural language mission status.
        Framing adapts to the active persona.
        """
        rec   = self.recommend_next_action(state)
        stage = state.stage.value.replace("_", " ").title()

        persona = (persona or "jarvis").lower()

        if persona == "ct7567":
            return (
                f"Target: {state.target}. "
                f"Stage: {stage}. "
                f"Next move: {rec}"
            )
        elif persona == "india":
            return (
                f"We're working on {state.target} — currently in {stage}. "
                f"I'd suggest {rec}"
            )
        elif persona == "morgan":
            return (
                f"The mission continues on {state.target}. "
                f"{stage} awaits. "
                f"{rec}"
            )
        else:  # default: jarvis
            return (
                f"Current target: {state.target}. "
                f"{stage} phase. "
                f"Recommendation: {rec}"
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _infer_stage(
        self, subdomains: int, live_hosts: int, findings: int
    ) -> ReconStage:
        """Simple heuristic to infer current recon stage from DB counts."""
        if subdomains == 0:
            return ReconStage.DISCOVERY
        elif live_hosts == 0:
            return ReconStage.LIVE_CHECK
        elif findings == 0:
            return ReconStage.VULN_SCAN
        elif findings < 3:
            return ReconStage.FINDING_TRIAGE
        else:
            return ReconStage.REPORT_DRAFT


# ── Tool entry point ──────────────────────────────────────────────────────────

def tool_strategy_briefing() -> str:
    """Tool entry point — callable from tools/registry.py dispatch."""
    try:
        import config as _c
        persona = getattr(_c, "ACTIVE_PERSONA", "jarvis")
        project = None  # use active project
        try:
            from storage.db import get_active_project
            project = get_active_project()
        except Exception:
            pass
        engine = StrategyEngine()
        state  = engine.get_current_mission(project)
        if state is None:
            return "No active mission. Add a target with: save_target <domain>"
        return engine.get_strategy_briefing(state, persona)
    except Exception as exc:
        logger.error("[Strategy] briefing error: %s", exc)
        return "Strategy engine unavailable."
