"""
gui/panels/agent_monitor.py — Agent task monitor panel for JARVIS.

Displays the recon job queue as agent tasks: pending, in_progress,
completed, failed. Each job is rendered as a card with status badge,
domain, program name, and timestamp.

Auto-refreshes every 5 seconds. Shows empty state when no jobs exist.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel,
    QScrollArea, QVBoxLayout, QWidget,
)

from config import P
import config as _cfg

_STATUS_COLOR: dict[str, str] = {
    "in_progress": "#18e0c1",
    "pending":     "#ffc107",
    "completed":   "#4caf50",
    "failed":      "#ff5252",
}


class AgentMonitorPanel(QWidget):
    """Scrollable job-queue monitor that shows recon tasks as agent tasks."""

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

        title = QLabel("AGENT TASKS")
        title.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;"
            f"letter-spacing:3px;"
        )
        self._count_lbl = QLabel("IDLE")
        self._count_lbl.setStyleSheet(
            f"color:{P['arc']};font-family:'{_cfg.MONO}';font-size:8px;"
            f"letter-spacing:2px;font-weight:700;"
        )
        hdr_row.addWidget(title)
        hdr_row.addStretch()
        hdr_row.addWidget(self._count_lbl)
        root.addWidget(hdr)

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
        self._inner_v.setSpacing(6)
        self._inner_v.addStretch()
        self._scroll.setWidget(self._inner)
        root.addWidget(self._scroll, 1)

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload jobs from DB and rebuild card list."""
        # Remove all cards (keep trailing stretch)
        while self._inner_v.count() > 1:
            item = self._inner_v.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rows = self._load_jobs()

        if not rows:
            empty = QLabel(
                "No active agent tasks.\n\n"
                "To start reconnaissance:\n"
                "  create_program → add_scope → recon_loop_start"
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:9px;"
                f"line-height:1.8;"
            )
            self._inner_v.insertWidget(0, empty)
            self._count_lbl.setText("IDLE")
            return

        active = sum(1 for r in rows if r[2] in ("in_progress", "pending"))
        self._count_lbl.setText(f"{active} ACTIVE" if active else "IDLE")

        for row in rows:
            card = self._mk_card(*row)
            self._inner_v.insertWidget(self._inner_v.count() - 1, card)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_jobs(self) -> list[tuple]:
        try:
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT j.id, j.domain, j.status, j.created_at, "
                    "COALESCE(p.name, 'unknown') AS program_name "
                    "FROM jobs j "
                    "LEFT JOIN programs p ON p.id = j.program_id "
                    "ORDER BY "
                    "  CASE j.status "
                    "    WHEN 'in_progress' THEN 0 "
                    "    WHEN 'pending'     THEN 1 "
                    "    WHEN 'failed'      THEN 2 "
                    "    ELSE 3 END, "
                    "  j.created_at DESC "
                    "LIMIT 40"
                ).fetchall()
                return [
                    (r[0], r[1], r[2], (r[3] or "")[:16], r[4])
                    for r in rows
                ]
        except Exception:
            return []

    # ── Card builder ──────────────────────────────────────────────────────────

    def _mk_card(self, job_id: int, domain: str, status: str,
                 ts: str, program: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{P['surface']};border:1px solid {P['b0']};"
            f"border-radius:4px;}}"
            f"QFrame:hover{{border-color:{P['b1']};}}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)

        # Status badge
        color = _STATUS_COLOR.get(status, P["t3"])
        badge = QLabel(status.upper().replace("_", " "))
        badge.setFixedWidth(88)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"color:{color};font-family:'{_cfg.MONO}';font-size:7px;"
            f"font-weight:700;letter-spacing:1px;"
            f"background:{color}18;border:1px solid {color}44;"
            f"border-radius:2px;padding:2px 0;"
        )

        # Domain
        domain_lbl = QLabel(domain or "—")
        domain_lbl.setStyleSheet(
            f"color:{P['t1']};font-family:'{_cfg.MONO}';font-size:10px;"
            f"font-weight:600;"
        )

        # Program · timestamp
        meta_lbl = QLabel(f"{program}  ·  {ts}")
        meta_lbl.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;"
        )
        meta_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        row.addWidget(badge)
        row.addWidget(domain_lbl, 1)
        row.addWidget(meta_lbl)
        return card

    # ── Active task count (for tab badge) ─────────────────────────────────────

    def active_count(self) -> int:
        """Return count of in_progress + pending jobs (for tab badge)."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('in_progress','pending')"
                ).fetchone()[0]
        except Exception:
            return 0
