"""
gui/panels/pipeline_monitor.py — Recon pipeline status panel for JARVIS.

Visualizes the 3-stage recon pipeline (SUBFINDER → HTTPX → NUCLEI → DONE)
for active and recent jobs. An indeterminate progress bar animates for any
in_progress job. Findings count is shown when available.

Auto-refreshes every 5 seconds. Empty state shown when no jobs exist.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar,
    QScrollArea, QVBoxLayout, QWidget,
)

from config import P
import config as _cfg

_STAGES = ["SUBFINDER", "HTTPX", "NUCLEI", "DONE"]

# How many stages are "done" for each job status
_STAGES_DONE: dict[str, int] = {
    "pending":     0,
    "in_progress": 1,   # at least stage 1 running
    "completed":   4,
    "failed":      1,
}


class PipelineMonitorPanel(QWidget):
    """Recon pipeline visualizer — one card per job."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background:{P['base']};")
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5_000)
        self.refresh()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        hdr = QWidget()
        hdr.setFixedHeight(34)
        hdr.setStyleSheet(
            f"background:{P['surface']};border-bottom:1px solid {P['b0']};"
        )
        hdr_row = QHBoxLayout(hdr)
        hdr_row.setContentsMargins(16, 0, 16, 0)
        title = QLabel("PIPELINE STATUS")
        title.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;"
            f"letter-spacing:3px;"
        )
        self._status_lbl = QLabel("IDLE")
        self._status_lbl.setStyleSheet(
            f"color:{P['arc']};font-family:'{_cfg.MONO}';font-size:8px;"
            f"letter-spacing:2px;font-weight:700;"
        )
        hdr_row.addWidget(title)
        hdr_row.addStretch()
        hdr_row.addWidget(self._status_lbl)
        root.addWidget(hdr)

        # Stage legend
        legend = QWidget()
        legend.setFixedHeight(26)
        legend.setStyleSheet(
            f"background:{P['void']};border-bottom:1px solid {P['b0']};"
        )
        leg_row = QHBoxLayout(legend)
        leg_row.setContentsMargins(12, 0, 12, 0)
        leg_row.setSpacing(0)
        for i, stage in enumerate(_STAGES):
            lbl = QLabel(stage)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:7px;"
                f"letter-spacing:2px;"
            )
            leg_row.addWidget(lbl, 1)
            if i < len(_STAGES) - 1:
                sep = QLabel("›")
                sep.setAlignment(Qt.AlignCenter)
                sep.setFixedWidth(14)
                sep.setStyleSheet(f"color:{P['b1']};font-size:10px;")
                leg_row.addWidget(sep)
        root.addWidget(legend)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{P['base']};}}"
            f"QScrollBar:vertical{{width:4px;background:{P['void']};}}"
            f"QScrollBar::handle:vertical{{background:{P['b1']};border-radius:2px;}}"
        )
        self._inner = QWidget()
        self._inner.setStyleSheet(f"background:{P['base']};")
        self._inner_v = QVBoxLayout(self._inner)
        self._inner_v.setContentsMargins(12, 12, 12, 12)
        self._inner_v.setSpacing(8)
        self._inner_v.addStretch()
        self._scroll.setWidget(self._inner)
        root.addWidget(self._scroll, 1)

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload jobs from DB and rebuild pipeline cards."""
        while self._inner_v.count() > 1:
            item = self._inner_v.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rows = self._load_jobs()

        if not rows:
            empty = QLabel(
                "No pipelines running.\n\n"
                "To start a pipeline:\n"
                "  create_program → add_scope → recon_loop_start"
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:9px;"
                f"line-height:1.8;"
            )
            self._inner_v.insertWidget(0, empty)
            self._status_lbl.setText("IDLE")
            return

        running = sum(1 for r in rows if r[2] == "in_progress")
        pending = sum(1 for r in rows if r[2] == "pending")
        if running:
            self._status_lbl.setText(f"{running} RUNNING")
        elif pending:
            self._status_lbl.setText(f"{pending} QUEUED")
        else:
            self._status_lbl.setText("COMPLETE")

        for row in rows:
            card = self._mk_pipeline_card(*row)
            self._inner_v.insertWidget(self._inner_v.count() - 1, card)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_jobs(self) -> list[tuple]:
        try:
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT j.id, j.domain, j.status, j.created_at, "
                    "COALESCE(p.name, 'unknown') AS prog "
                    "FROM jobs j "
                    "LEFT JOIN programs p ON p.id = j.program_id "
                    "WHERE j.status IN ('in_progress','pending','completed','failed') "
                    "ORDER BY "
                    "  CASE j.status "
                    "    WHEN 'in_progress' THEN 0 "
                    "    WHEN 'pending'     THEN 1 "
                    "    WHEN 'failed'      THEN 2 "
                    "    ELSE 3 END, "
                    "  j.created_at DESC "
                    "LIMIT 20"
                ).fetchall()
                # Count findings per program
                prog_findings: dict[str, int] = {}
                for r in rows:
                    prog = r[4]
                    if prog not in prog_findings:
                        try:
                            cnt = conn.execute(
                                "SELECT COUNT(*) FROM findings_canonical fc "
                                "JOIN programs pp ON pp.id = fc.program_id "
                                "WHERE pp.name = ?",
                                (prog,)
                            ).fetchone()[0]
                            prog_findings[prog] = cnt
                        except Exception:
                            prog_findings[prog] = 0
                return [
                    (r[0], r[1], r[2], (r[3] or "")[:16], r[4],
                     prog_findings.get(r[4], 0))
                    for r in rows
                ]
        except Exception:
            return []

    # ── Card builder ──────────────────────────────────────────────────────────

    def _mk_pipeline_card(self, job_id: int, domain: str, status: str,
                          ts: str, program: str, f_count: int) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{P['surface']};border:1px solid {P['b0']};"
            f"border-radius:4px;}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        # Title row
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        domain_lbl = QLabel(domain or "—")
        domain_lbl.setStyleSheet(
            f"color:{P['t1']};font-family:'{_cfg.MONO}';font-size:10px;"
            f"font-weight:600;"
        )
        prog_lbl = QLabel(program)
        prog_lbl.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;"
        )
        ts_lbl = QLabel(ts)
        ts_lbl.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;"
        )
        ts_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title_row.addWidget(domain_lbl)
        title_row.addWidget(prog_lbl)
        title_row.addStretch()
        title_row.addWidget(ts_lbl)
        v.addLayout(title_row)

        # Stage step row
        stages_done = _STAGES_DONE.get(status, 0)
        step_row = QHBoxLayout()
        step_row.setSpacing(2)
        for i, stage in enumerate(_STAGES):
            done   = i < stages_done
            active = (i == stages_done and status == "in_progress")
            if done:
                col = P["arc"]
                bg  = f"{P['arc']}22"
                border = f"{P['arc']}66"
            elif active:
                col = P["amber"]
                bg  = f"{P['amber']}22"
                border = f"{P['amber']}66"
            else:
                col = P["t3"]
                bg  = "transparent"
                border = P["b0"]

            stage_lbl = QLabel(stage)
            stage_lbl.setAlignment(Qt.AlignCenter)
            stage_lbl.setStyleSheet(
                f"color:{col};font-family:'{_cfg.MONO}';font-size:7px;"
                f"letter-spacing:1px;background:{bg};"
                f"border:1px solid {border};border-radius:2px;padding:2px 0;"
            )
            step_row.addWidget(stage_lbl, 1)
            if i < len(_STAGES) - 1:
                arrow = QLabel("›")
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setFixedWidth(12)
                arrow.setStyleSheet(
                    f"color:{P['b1'] if not done else P['arc']};font-size:10px;"
                )
                step_row.addWidget(arrow)
        v.addLayout(step_row)

        # Indeterminate progress bar for running jobs
        if status == "in_progress":
            bar = QProgressBar()
            bar.setRange(0, 0)
            bar.setFixedHeight(3)
            bar.setTextVisible(False)
            bar.setStyleSheet(
                f"QProgressBar{{background:{P['b0']};border:none;border-radius:1px;}}"
                f"QProgressBar::chunk{{background:{P['arc']};border-radius:1px;}}"
            )
            v.addWidget(bar)

        # Findings count
        if f_count > 0:
            fin_lbl = QLabel(
                f"↳ {f_count} finding{'s' if f_count != 1 else ''} discovered"
            )
            fin_lbl.setStyleSheet(
                f"color:{P['arc']};font-family:'{_cfg.MONO}';font-size:8px;"
            )
            v.addWidget(fin_lbl)

        return card
