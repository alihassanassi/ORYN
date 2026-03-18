"""
gui/mini_window.py — Compact always-on-top mini HUD for JARVIS.

MiniHUD is a frameless, semi-transparent floating widget that mirrors the
last JARVIS response, current AI state, last tool used, and mic status.
It is positioned at the bottom-right of the primary screen on first show.

Public API (called from main_window.py):
    update_response(text)  — update displayed response text
    update_status(state)   — "IDLE" | "THINKING" | "LISTENING" | "EXECUTING"
    update_tool(tool_name) — update bottom-left tool label
    toggle()               — show if hidden, hide if visible
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QApplication,
)

from config import P, MONO
import config as _cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_markdown(text: str) -> str:
    """Remove common markdown tokens for plain-text display."""
    # Strip headings, bold/italic markers, inline code
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^[\*\-]\s+", "", text, flags=re.MULTILINE)
    return text.strip()


# State → dot color mapping
# Persona border color mapping
_PERSONA_COLOR: dict[str, str] = {
    "jarvis":  "#18e0c1",   # teal
    "india":   "#ff9800",   # warm orange
    "ct7567":  "#4caf50",   # military green
    "morgan":  "#9c27b0",   # deep purple
}

_STATE_DOT: dict[str, str] = {
    "IDLE":      P["t3"],
    "THINKING":  P["arc"],
    "LISTENING": P["green"],
    "EXECUTING": P["amber"],
}


class _StatusDot(QWidget):
    """12×12 filled circle that changes color based on AI state."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._color = QColor(P["t3"])

    def set_color(self, hex_color: str) -> None:
        self._color = QColor(hex_color)
        self.update()

    def paintEvent(self, ev):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(1, 1, 10, 10)
        painter.end()


# ---------------------------------------------------------------------------
# MiniHUD
# ---------------------------------------------------------------------------

class MiniHUD(QWidget):
    """
    Frameless, always-on-top, semi-transparent JARVIS status overlay.

    Fixed size 320 × 140 px. Draggable by left-click anywhere on the window.
    Bottom-right positioned relative to the primary screen on first show.
    """

    _WIDTH  = 320
    _HEIGHT = 170

    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )

        # Translucent compositing (required for custom paintEvent alpha)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self._WIDTH, self._HEIGHT)

        self._drag_pos      = None   # set during drag
        self._positioned    = False  # first-show position sentinel
        self._finding_count = 0
        self._recon_status  = "STANDING BY"

        self._build_ui()
        self._start_live_updater()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 4)
        root.setSpacing(2)

        # ── Title row ──────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_row.setSpacing(0)

        title_lbl = QLabel("◈ JARVIS")
        title_lbl.setFixedHeight(24)
        title_lbl.setStyleSheet(
            f"color:{P['arc']};"
            f"font-family:'{MONO}';"
            f"font-size:11px;"
            f"font-weight:700;"
            f"letter-spacing:2px;"
            f"background:transparent;"
        )

        self._status_dot = _StatusDot()

        title_row.addWidget(title_lbl, alignment=Qt.AlignVCenter)
        title_row.addStretch()
        title_row.addWidget(self._status_dot, alignment=Qt.AlignVCenter)

        root.addLayout(title_row)

        # ── Response area ──────────────────────────────────────────────
        self._response_view = QTextEdit()
        self._response_view.setReadOnly(True)
        self._response_view.setFixedHeight(80)
        self._response_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._response_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._response_view.setFont(QFont(MONO, 9))
        self._response_view.setStyleSheet(
            f"QTextEdit {{"
            f"  color:{P['t1']};"
            f"  background:transparent;"
            f"  border:none;"
            f"  font-family:'{MONO}';"
            f"  font-size:9px;"
            f"}}"
        )
        self._response_view.setPlaceholderText("Awaiting response…")

        root.addWidget(self._response_view)

        # ── Bottom row ─────────────────────────────────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(0)

        self._tool_lbl = QLabel("—")
        self._tool_lbl.setFixedHeight(20)
        self._tool_lbl.setStyleSheet(
            f"color:{P['t3']};"
            f"font-family:'{MONO}';"
            f"font-size:8px;"
            f"background:transparent;"
        )

        self._mic_lbl = QLabel("MIC OFF")
        self._mic_lbl.setFixedHeight(20)
        self._mic_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._mic_lbl.setStyleSheet(
            f"color:{P['t3']};"
            f"font-family:'{MONO}';"
            f"font-size:8px;"
            f"background:transparent;"
        )

        bottom_row.addWidget(self._tool_lbl, alignment=Qt.AlignVCenter)
        bottom_row.addStretch()
        bottom_row.addWidget(self._mic_lbl, alignment=Qt.AlignVCenter)

        root.addLayout(bottom_row)

        # ── Recon/finding status line ───────────────────────────────────
        self._recon_lbl = QLabel("STANDING BY")
        self._recon_lbl.setFixedHeight(18)
        self._recon_lbl.setAlignment(Qt.AlignCenter)
        self._recon_lbl.setStyleSheet(
            f"color:{P['t3']};"
            f"font-family:'{MONO}';"
            f"font-size:8px;"
            f"letter-spacing:2px;"
            f"background:transparent;"
        )
        root.addWidget(self._recon_lbl)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_response(self, text: str) -> None:
        """Display first 200 chars of text after stripping markdown."""
        clean = _strip_markdown(text)
        if len(clean) > 200:
            clean = clean[:200] + "…"
        self._response_view.setPlainText(clean)

    def update_status(self, state: str) -> None:
        """Update status dot color. state: IDLE | THINKING | LISTENING | EXECUTING."""
        color = _STATE_DOT.get(state.upper(), P["t3"])
        self._status_dot.set_color(color)

    def update_tool(self, tool_name: str) -> None:
        """Update the bottom-left tool label."""
        label = tool_name if tool_name else "—"
        self._tool_lbl.setText(label)

    def set_mic_status(self, active: bool) -> None:
        """Update mic status label (bottom-right)."""
        if active:
            self._mic_lbl.setStyleSheet(
                f"color:{P['green']};"
                f"font-family:'{MONO}';"
                f"font-size:8px;"
                f"background:transparent;"
            )
            self._mic_lbl.setText("MIC ON")
        else:
            self._mic_lbl.setStyleSheet(
                f"color:{P['t3']};"
                f"font-family:'{MONO}';"
                f"font-size:8px;"
                f"background:transparent;"
            )
            self._mic_lbl.setText("MIC OFF")

    def toggle(self) -> None:
        """Show if hidden, hide if visible."""
        if self.isVisible():
            self.hide()
        else:
            self.show()

    # ------------------------------------------------------------------
    # Live data updater
    # ------------------------------------------------------------------

    def _start_live_updater(self) -> None:
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._refresh_live_data)
        self._live_timer.start(30_000)   # every 30 seconds
        self._refresh_live_data()        # immediate first call

    def _refresh_live_data(self) -> None:
        """Poll DB for unreviewed findings and active job status."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                self._finding_count = conn.execute(
                    "SELECT COUNT(*) FROM findings_canonical WHERE status='unverified'"
                ).fetchone()[0]
                # Check for active recon job
                active = conn.execute(
                    "SELECT domain FROM jobs WHERE status='in_progress' LIMIT 1"
                ).fetchone()
            if active:
                self._recon_status = f"HUNTING: {active[0]}"
            elif self._finding_count > 0:
                self._recon_status = f"{self._finding_count} FINDING{'S' if self._finding_count != 1 else ''}"
            else:
                self._recon_status = "STANDING BY"
        except Exception:
            pass
        self._update_recon_display()
        self.update()   # trigger repaint for finding badge

    def _update_recon_display(self) -> None:
        color = P["amber"] if "HUNTING" in self._recon_status else (
            P["arc"] if "FINDING" in self._recon_status else P["t3"]
        )
        self._recon_lbl.setText(self._recon_status)
        self._recon_lbl.setStyleSheet(
            f"color:{color};"
            f"font-family:'{MONO}';"
            f"font-size:8px;"
            f"letter-spacing:2px;"
            f"background:transparent;"
        )

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def showEvent(self, ev) -> None:  # noqa: N802
        if not self._positioned:
            screen = QApplication.primaryScreen().geometry()
            self.move(
                screen.width()  - self.width()  - 20,
                screen.height() - self.height() - 60,
            )
            self._positioned = True
        super().showEvent(ev)

    def paintEvent(self, ev) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Semi-transparent void background
        painter.setBrush(QColor(8, 14, 26, 210))

        # Persona-colored border ring
        persona = getattr(_cfg, "ACTIVE_PERSONA", "jarvis")
        hex_col = _PERSONA_COLOR.get(persona, "#18e0c1")
        border_color = QColor(hex_col)
        border_color.setAlpha(180)
        painter.setPen(border_color)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 2, 2)

        # Finding badge (top-right corner): orange dot + count when > 0
        if self._finding_count > 0:
            badge_r = 9
            bx = self.width() - badge_r - 4
            by = badge_r + 4
            badge_bg = QColor(P["amber"])
            badge_bg.setAlpha(220)
            painter.setBrush(badge_bg)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(bx - badge_r, by - badge_r,
                                badge_r * 2, badge_r * 2)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont(MONO, 7))
            painter.drawText(
                QRect(bx - badge_r, by - badge_r, badge_r * 2, badge_r * 2),
                Qt.AlignCenter,
                str(min(self._finding_count, 99))
            )

        painter.end()

    # Drag support ----------------------------------------------------------

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if ev.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._drag_pos = None
