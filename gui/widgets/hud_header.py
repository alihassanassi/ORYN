"""
gui/widgets/hud_header.py — Iron Man HUD-style window title bar.

A reusable frameless header for JARVIS windows.
Replace the OS title bar by calling:
    window.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
    header = HUDHeader("WINDOW TITLE", parent=window)
    layout.insertWidget(0, header)

Signals:
    minimize_requested  — wire to window.showMinimized()
    maximize_requested  — wire to window.showMaximized() / showNormal()
    close_requested     — wire to window.close()

Dragging the header moves the parent window.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton,
)

from config import P
import config as _cfg


class HUDHeader(QWidget):
    """36px frameless title bar with JARVIS branding and window controls."""

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested    = Signal()

    def __init__(self, title: str = "", subtitle: str = "",
                 show_maximize: bool = True, parent: QWidget = None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #0d1117,stop:1 #111827);"
        )

        self._drag_pos: QPoint | None = None
        self._show_max = show_maximize

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 6, 0)
        lay.setSpacing(8)

        # ── Logo mark (teal hexagon text) ─────────────────────────────────────
        _logo = QLabel("⬡")
        _logo.setFixedSize(20, 20)
        _logo.setAlignment(Qt.AlignCenter)
        _logo.setStyleSheet(
            f"color:{P['arc']};font-size:16px;background:transparent;"
        )
        lay.addWidget(_logo)

        # ── App identity ──────────────────────────────────────────────────────
        _app = QLabel("J.A.R.V.I.S")
        _app.setStyleSheet(
            f"color:{P['arc']};font-family:{_cfg.DISPLAY_CSS};"
            f"font-size:11px;font-weight:700;letter-spacing:3px;"
            f"background:transparent;"
        )
        lay.addWidget(_app)

        # ── Separator ─────────────────────────────────────────────────────────
        _sep = QLabel("│")
        _sep.setStyleSheet(f"color:{P['b2']};background:transparent;font-size:14px;")
        lay.addWidget(_sep)

        # ── Window title ──────────────────────────────────────────────────────
        self._title_lbl = QLabel(title.upper())
        self._title_lbl.setStyleSheet(
            f"color:{P['blue']};font-family:'{_cfg.MONO}';"
            f"font-size:11px;letter-spacing:1px;background:transparent;"
        )
        lay.addWidget(self._title_lbl)

        if subtitle:
            _sub = QLabel(f"— {subtitle}")
            _sub.setStyleSheet(
                f"color:{P['t3']};font-family:'{_cfg.MONO}';"
                f"font-size:10px;background:transparent;"
            )
            lay.addWidget(_sub)

        lay.addStretch()

        # ── Window control buttons ─────────────────────────────────────────────
        btn_base = (
            f"QPushButton{{"
            f"background:transparent;color:{P['t3']};"
            f"border:none;border-radius:4px;"
            f"font-size:13px;font-weight:400;"
            f"min-width:28px;max-width:28px;"
            f"min-height:28px;max-height:28px;"
            f"}}"
            f"QPushButton:hover{{background:rgba(255,255,255,0.08);color:#ffffff;}}"
        )
        close_style = (
            f"QPushButton{{"
            f"background:transparent;color:{P['t3']};"
            f"border:none;border-radius:4px;"
            f"font-size:13px;font-weight:400;"
            f"min-width:28px;max-width:28px;"
            f"min-height:28px;max-height:28px;"
            f"}}"
            f"QPushButton:hover{{background:rgba(255,0,0,0.3);color:#ffffff;}}"
        )

        self._btn_min = QPushButton("─")
        self._btn_min.setStyleSheet(btn_base)
        self._btn_min.setToolTip("Minimize")
        self._btn_min.clicked.connect(self.minimize_requested)
        lay.addWidget(self._btn_min)

        if show_maximize:
            self._btn_max = QPushButton("□")
            self._btn_max.setStyleSheet(btn_base)
            self._btn_max.setToolTip("Maximize / Restore")
            self._btn_max.clicked.connect(self.maximize_requested)
            lay.addWidget(self._btn_max)

        self._btn_cls = QPushButton("✕")
        self._btn_cls.setStyleSheet(close_style)
        self._btn_cls.setToolTip("Close")
        self._btn_cls.clicked.connect(self.close_requested)
        lay.addWidget(self._btn_cls)

        # ── Bottom separator line ─────────────────────────────────────────────
        # Drawn by the parent — we add a 1px bottom border via stylesheet
        self.setStyleSheet(
            self.styleSheet()
            + f"border-bottom:1px solid rgba(24,224,193,0.20);"
        )

    def set_title(self, title: str) -> None:
        self._title_lbl.setText(title.upper())

    # ── Drag to move parent window ─────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.LeftButton:
            win = self.window()
            if win:
                delta = event.globalPosition().toPoint() - self._drag_pos
                win.move(win.pos() + delta)
                self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Double-click header to maximize/restore."""
        if self._show_max:
            self.maximize_requested.emit()
        super().mouseDoubleClickEvent(event)
