"""
gui/panels/intelligence_panel.py — IntelligencePanel: live intelligence feeds HUD.

Displays four sections:
  1. OPERATOR PROFILE  — skill summary from memory/operator_model
  2. COACHING HINT     — latest hint from intelligence/coaching_engine
  3. THREAT INTEL      — top 3 unactioned research_items by severity
  4. HUNT PROPOSALS    — pending hunt proposals with ACTION buttons

Self-contained: gracefully degrades if any subsystem is unavailable.
Auto-refreshes every 30 seconds. No blocking calls on main thread.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from config import P
import config as _cfg

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _section_hdr(text: str) -> QLabel:
    """28px section header matching the HUD aesthetic."""
    lbl = QLabel(text)
    lbl.setFixedHeight(28)
    lbl.setStyleSheet(
        f"color:{P['t3']};font-size:9px;letter-spacing:3px;font-weight:600;"
        f"padding-left:12px;border-top:1px solid {P['b0']};"
        f"border-bottom:1px solid {P['b0']};background:{P['void']};"
    )
    return lbl


def _severity_color(severity: str) -> str:
    """Return the badge color for a given severity string."""
    s = (severity or "").lower()
    if s in ("critical", "high"):
        return P["red"]
    if s == "medium":
        return P["amber"]
    return P["t3"]


def _action_btn(label: str, color: str) -> QPushButton:
    btn = QPushButton(label)
    btn.setFixedHeight(20)
    btn.setCursor(QCursor(Qt.PointingHandCursor))
    btn.setStyleSheet(
        f"QPushButton{{background:transparent;color:{color};"
        f"border:1px solid {color}55;border-radius:3px;"
        f"font-family:{_cfg.DISPLAY_CSS};font-size:8px;letter-spacing:1px;"
        f"padding:0 8px;}}"
        f"QPushButton:hover{{background:{color}22;border-color:{color};}}"
    )
    return btn


# ── Panel ─────────────────────────────────────────────────────────────────────

class IntelligencePanel(QWidget):
    """
    Full-height intelligence feeds panel.

    Sections: Operator Profile | Coaching Hint | Threat Intel | Hunt Proposals
    Auto-refreshes every 30 seconds via QTimer.
    """

    REFRESH_INTERVAL_MS = 30_000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{P['base']};")

        # Build scroll area wrapping all content
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        root.addWidget(self._build_header_bar())

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{P['base']};}}"
            f"QScrollBar:vertical{{background:{P['void']};width:6px;border:none;}}"
            f"QScrollBar::handle:vertical{{background:{P['b1']};border-radius:3px;}}"
        )

        self._content = QWidget()
        self._content.setStyleSheet(f"background:{P['base']};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 12)
        self._content_layout.setSpacing(0)

        # ── Section 1: Operator Profile ───────────────────────────────────────
        self._content_layout.addWidget(_section_hdr("◈ OPERATOR PROFILE"))
        self._skill_lbl = QLabel("Loading…")
        self._skill_lbl.setWordWrap(True)
        self._skill_lbl.setStyleSheet(
            f"color:{P['t1']};font-family:'{_cfg.MONO}';"
            f"font-size:10px;padding:10px 14px;background:transparent;"
        )
        self._content_layout.addWidget(self._skill_lbl)

        # ── Section 2: Coaching Hint ──────────────────────────────────────────
        self._content_layout.addWidget(_section_hdr("◈ COACHING HINT"))
        self._hint_lbl = QLabel("Loading…")
        self._hint_lbl.setWordWrap(True)
        self._hint_lbl.setStyleSheet(
            f"color:{P['t2']};font-family:'{_cfg.MONO}';"
            f"font-size:10px;padding:10px 14px;background:transparent;"
        )
        self._content_layout.addWidget(self._hint_lbl)

        # ── Section 3: Threat Intel ───────────────────────────────────────────
        self._content_layout.addWidget(_section_hdr("◈ THREAT INTEL"))
        self._threat_frame = QFrame()
        self._threat_frame.setStyleSheet(
            f"QFrame{{background:{P['card']};border:none;"
            f"border-bottom:1px solid {P['b0']};}}"
        )
        self._threat_layout = QVBoxLayout(self._threat_frame)
        self._threat_layout.setContentsMargins(12, 8, 12, 8)
        self._threat_layout.setSpacing(6)
        self._content_layout.addWidget(self._threat_frame)

        # ── Section 4: Hunt Proposals ─────────────────────────────────────────
        self._content_layout.addWidget(_section_hdr("◈ HUNT PROPOSALS"))
        self._hunt_frame = QFrame()
        self._hunt_frame.setStyleSheet(
            f"QFrame{{background:{P['card']};border:none;"
            f"border-bottom:1px solid {P['b0']};}}"
        )
        self._hunt_layout = QVBoxLayout(self._hunt_frame)
        self._hunt_layout.setContentsMargins(12, 8, 12, 8)
        self._hunt_layout.setSpacing(6)
        self._content_layout.addWidget(self._hunt_frame)

        self._content_layout.addStretch()

        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        # Auto-refresh timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(self.REFRESH_INTERVAL_MS)

        # Initial population (slight delay so window is visible first)
        QTimer.singleShot(400, self.refresh)

    # ── Header bar ────────────────────────────────────────────────────────────

    def _build_header_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet(
            f"background:{P['surface']};"
            f"border-bottom:1px solid {P['b0']};"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(8)

        title = QLabel("INTELLIGENCE FEEDS")
        title.setStyleSheet(
            f"color:{P['t3']};font-family:{_cfg.DISPLAY_CSS};"
            f"font-size:9px;letter-spacing:3px;font-weight:600;"
            f"background:transparent;"
        )

        self._status_lbl = QLabel("—")
        self._status_lbl.setStyleSheet(
            f"color:{P['arc']};font-family:'{_cfg.MONO}';"
            f"font-size:9px;background:transparent;"
        )

        refresh_btn = QPushButton("REFRESH")
        refresh_btn.setFixedHeight(22)
        refresh_btn.setCursor(QCursor(Qt.PointingHandCursor))
        refresh_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{P['t3']};"
            f"border:1px solid {P['b1']};border-radius:3px;"
            f"font-family:{_cfg.DISPLAY_CSS};font-size:8px;letter-spacing:2px;"
            f"padding:0 8px;}}"
            f"QPushButton:hover{{color:{P['arc']};border-color:{P['arc_d']};}}"
        )
        refresh_btn.clicked.connect(self.refresh)

        row.addWidget(title)
        row.addStretch()
        row.addWidget(self._status_lbl)
        row.addWidget(refresh_btn)
        return bar

    # ── Public refresh ────────────────────────────────────────────────────────

    @Slot()
    def refresh(self) -> None:
        """Reload all intelligence sections. Fast DB reads only — no LLM calls."""
        self._refresh_operator_profile()
        self._refresh_coaching_hint()
        self._refresh_threat_intel()
        self._refresh_hunt_proposals()
        self._status_lbl.setText("live")

    # ── Section refresh methods ───────────────────────────────────────────────

    def _refresh_operator_profile(self) -> None:
        try:
            from memory.operator_model import get_skill_summary  # type: ignore
            summary = get_skill_summary()
            self._skill_lbl.setText(summary or "No skill data available.")
        except Exception:
            self._skill_lbl.setText("Operator model unavailable.")

    def _refresh_coaching_hint(self) -> None:
        try:
            from intelligence.coaching_engine import CoachingEngine  # type: ignore
            hint = CoachingEngine.get_hint_if_due()
            self._hint_lbl.setText(hint or "No active coaching hint.")
        except Exception:
            self._hint_lbl.setText("Coaching engine unavailable.")

    def _refresh_threat_intel(self) -> None:
        try:
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT title, severity, source FROM research_items "
                    "WHERE actioned=0 ORDER BY "
                    "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                    "WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC LIMIT 3"
                ).fetchall()
            self._update_threat_list(rows)
        except Exception as exc:
            log.debug("[IntelligencePanel] threat intel error: %s", exc)
            self._update_threat_list([])

    def _refresh_hunt_proposals(self) -> None:
        try:
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT id, title, raw_data FROM research_items "
                    "WHERE item_type='hunt_proposal' AND actioned=0 LIMIT 5"
                ).fetchall()
            self._update_hunt_list(rows)
        except Exception as exc:
            log.debug("[IntelligencePanel] hunt proposals error: %s", exc)
            self._update_hunt_list([])

    # ── List builders ─────────────────────────────────────────────────────────

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        """Remove all widgets from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _update_threat_list(self, rows: list) -> None:
        self._clear_layout(self._threat_layout)

        if not rows:
            empty = QLabel("No unactioned threat intel.")
            empty.setStyleSheet(
                f"color:{P['t3']};font-family:'{_cfg.MONO}';"
                f"font-size:10px;background:transparent;"
            )
            self._threat_layout.addWidget(empty)
            return

        for row in rows:
            title    = row[0] if row[0] else "Unknown"
            severity = row[1] if row[1] else "info"
            source   = row[2] if row[2] else "—"

            item_row = QHBoxLayout()
            item_row.setSpacing(8)

            # Severity badge
            badge_color = _severity_color(severity)
            badge = QLabel(severity.upper()[:4])
            badge.setFixedWidth(42)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                f"background:{badge_color}22;color:{badge_color};"
                f"border:1px solid {badge_color}55;border-radius:3px;"
                f"font-family:{_cfg.DISPLAY_CSS};font-size:8px;"
                f"letter-spacing:1px;font-weight:700;padding:1px 0;"
            )

            # Title label
            title_display = title[:80] + ("…" if len(title) > 80 else "")
            title_lbl = QLabel(title_display)
            title_lbl.setWordWrap(True)
            title_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            title_lbl.setStyleSheet(
                f"color:{P['t1']};font-family:'{_cfg.MONO}';"
                f"font-size:10px;background:transparent;"
            )

            # Source label
            src_lbl = QLabel(source)
            src_lbl.setStyleSheet(
                f"color:{P['t3']};font-family:'{_cfg.MONO}';"
                f"font-size:8px;background:transparent;"
            )

            item_row.addWidget(badge)
            item_row.addWidget(title_lbl, 1)
            item_row.addWidget(src_lbl)

            item_widget = QWidget()
            item_widget.setStyleSheet("background:transparent;")
            item_widget.setLayout(item_row)
            self._threat_layout.addWidget(item_widget)

    def _update_hunt_list(self, rows: list) -> None:
        self._clear_layout(self._hunt_layout)

        if not rows:
            empty = QLabel("No pending hunt proposals.")
            empty.setStyleSheet(
                f"color:{P['t3']};font-family:'{_cfg.MONO}';"
                f"font-size:10px;background:transparent;"
            )
            self._hunt_layout.addWidget(empty)
            return

        for row in rows:
            proposal_id = row[0]
            title       = row[1] if row[1] else "Untitled Proposal"
            raw_data    = row[2] if row[2] else ""

            item_row = QHBoxLayout()
            item_row.setSpacing(10)

            # Title label
            title_display = title[:72] + ("…" if len(title) > 72 else "")
            title_lbl = QLabel(title_display)
            title_lbl.setWordWrap(False)
            title_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            title_lbl.setStyleSheet(
                f"color:{P['t1']};font-family:'{_cfg.MONO}';"
                f"font-size:10px;background:transparent;"
            )

            # Action button
            act_btn = _action_btn("▶ ACTION", P["arc"])
            act_btn.clicked.connect(
                lambda _, pid=proposal_id, rd=raw_data: self._on_hunt_action(pid, rd)
            )

            item_row.addWidget(title_lbl, 1)
            item_row.addWidget(act_btn)

            item_widget = QWidget()
            item_widget.setStyleSheet("background:transparent;")
            item_widget.setLayout(item_row)
            self._hunt_layout.addWidget(item_widget)

    # ── Hunt action slot ──────────────────────────────────────────────────────

    @Slot(int, str)
    def _on_hunt_action(self, proposal_id: int, raw_data: str) -> None:
        """Mark proposal actioned and show its raw_data to the operator."""
        # Mark actioned in DB
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "UPDATE research_items SET actioned=1 WHERE id=?",
                    (proposal_id,)
                )
                conn.commit()
        except Exception as exc:
            log.warning("[IntelligencePanel] failed to mark proposal actioned: %s", exc)

        # Show proposal details
        try:
            msg = QMessageBox(self)
            msg.setWindowTitle("Hunt Proposal")
            msg.setText(raw_data or "(No proposal details available)")
            msg.setStandardButtons(QMessageBox.Ok)
            msg.setStyleSheet(
                f"QMessageBox{{background:{P['base']};color:{P['t0']};}}"
                f"QLabel{{color:{P['t0']};font-family:'{_cfg.MONO}';font-size:10px;}}"
                f"QPushButton{{background:{P['surface']};color:{P['t1']};"
                f"border:1px solid {P['b1']};border-radius:3px;"
                f"padding:4px 12px;}}"
            )
            msg.exec()
        except Exception as exc:
            log.debug("[IntelligencePanel] message box error: %s", exc)

        # Refresh proposals list after actioning
        self._refresh_hunt_proposals()
