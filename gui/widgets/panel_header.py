"""
gui/widgets/panel_header.py — Reusable Iron Man HUD section header widget.

PanelHeader replaces the _sec_hdr() helper method pattern used in main_window.py.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton

from config import P
import config as _cfg


class PanelHeader(QWidget):
    """
    Standard HUD section header with optional action button.

    Usage:
        header = PanelHeader("SCAN INTELLIGENCE")
        header = PanelHeader("PROJECTS", action_icon="＋", action_tooltip="New project")
        header.action_clicked.connect(some_slot)
    """

    action_clicked = Signal()

    def __init__(
        self,
        title: str,
        action_icon: str = "",
        action_tooltip: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setStyleSheet(
            f"background:{P['void']};"
            f"border-top:1px solid {P['b0']};"
            f"border-bottom:1px solid {P['b0']};"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(0)

        # Title label
        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet(
            f"color:{P['t3']};"
            f"font-family:{_cfg.DISPLAY_CSS};"
            f"font-size:9px;"
            f"font-weight:600;"
            f"letter-spacing:3px;"
            f"padding-left:12px;"
            f"background:transparent;"
            f"border:none;"
        )
        lay.addWidget(self._title_lbl)
        lay.addStretch()

        # Optional action button
        self._btn = None
        if action_icon:
            self._btn = QPushButton(action_icon)
            self._btn.setFixedSize(20, 20)
            self._btn.setCursor(Qt.PointingHandCursor)
            if action_tooltip:
                self._btn.setToolTip(action_tooltip)
            self._btn.setStyleSheet(
                f"QPushButton {{"
                f"  border:none;"
                f"  color:{P['t2']};"
                f"  background:transparent;"
                f"  font-size:13px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  color:{P['arc']};"
                f"}}"
            )
            self._btn.clicked.connect(self.action_clicked)
            lay.addWidget(self._btn)
