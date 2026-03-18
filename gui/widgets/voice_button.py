"""
gui/widgets/voice_button.py — Iron Man HUD voice activation button.

VoiceButton is a drop-in QPushButton replacement for the plain "ENABLE VOICE"
button in main_window.py. It is still checkable — main_window.py connects the
toggled signal as before. The set_state() method is called externally (e.g.,
from _on_voice_toggle) to switch between visual states.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QPushButton

from config import P
import config as _cfg


class VoiceButton(QPushButton):
    """
    Iron Man HUD voice activation button.

    States:
        'offline'   — default; button unchecked, dim border
        'online'    — STT active; teal accent fill
        'listening' — currently capturing audio; green pulse fill
    """

    _STYLES: dict[str, str] = {
        "offline": (
            f"QPushButton {{"
            f"  background:transparent;"
            f"  color:{P['t3']};"
            f"  border:1px solid {P['b1']};"
            f"  border-radius:4px;"
            f"  font-family:{_cfg.MONO_CSS};"
            f"  font-size:10px;"
            f"  letter-spacing:2px;"
            f"  padding:7px;"
            f"  margin:4px 12px 4px 12px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  border-color:{P['b2']};"
            f"  color:{P['t1']};"
            f"}}"
        ),
        "online": (
            f"QPushButton {{"
            f"  color:{P['arc']};"
            f"  border:1px solid {P['arc_d']};"
            f"  background:{P['arc_g']};"
            f"  border-radius:4px;"
            f"  font-family:{_cfg.MONO_CSS};"
            f"  font-size:10px;"
            f"  letter-spacing:2px;"
            f"  padding:7px;"
            f"  margin:4px 12px 4px 12px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  border-color:{P['arc']};"
            f"}}"
        ),
        "listening": (
            f"QPushButton {{"
            f"  color:{P['green']};"
            f"  border:1px solid {P['green']}66;"
            f"  background:{P['green']}14;"
            f"  border-radius:4px;"
            f"  font-family:{_cfg.MONO_CSS};"
            f"  font-size:10px;"
            f"  letter-spacing:2px;"
            f"  padding:7px;"
            f"  margin:4px 12px 4px 12px;"
            f"}}"
        ),
    }

    _LABELS: dict[str, str] = {
        "offline":   "VOICE  OFFLINE",
        "online":    "VOICE  ONLINE",
        "listening": "LISTENING...",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self._current_state = "offline"
        self.set_state("offline")

    def set_state(self, state: str) -> None:
        """Switch button text and stylesheet to match the given state.

        Args:
            state: One of 'offline', 'online', or 'listening'.
        """
        if state not in self._STYLES:
            return
        self._current_state = state
        self.setText(self._LABELS[state])
        self.setStyleSheet(self._STYLES[state])
