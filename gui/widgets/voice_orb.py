"""
gui/widgets/voice_orb.py — Iron Man mic button with state-aware animation.

States:
    idle      — ambient/wake-word listening (breathing glow)
    listening — active after wake word (waveform pulse, strong glow)
    speaking  — JARVIS is responding (speaker icon, blue glow)
    muted     — mic disabled (red border, slash icon)

Signals:
    clicked       — operator manually activates listen
    mute_toggled  — mute/unmute request

Usage:
    orb = VoiceOrb()
    orb.set_state('listening')
    orb.clicked.connect(on_mic_click)
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Signal, QRect
from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from config import P


_STATE_CONFIG = {
    "idle": {
        "border":    "#18e0c1",
        "glow":      "#18e0c1",
        "glow_alpha": 0.25,
        "fill":      "#18e0c100",
        "icon":      "MIC",
        "label":     "WAKE WORD",
        "label_col": "#18e0c1",
        "pulse":     True,
    },
    "listening": {
        "border":    "#ffffff",
        "glow":      "#18e0c1",
        "glow_alpha": 0.8,
        "fill":      "#18e0c1",
        "icon":      "WAVE",
        "label":     "LISTENING...",
        "label_col": "#18e0c1",
        "pulse":     False,
    },
    "speaking": {
        "border":    "#45a5ff",
        "glow":      "#45a5ff",
        "glow_alpha": 0.45,
        "fill":      "#45a5ff33",
        "icon":      "SPK",
        "label":     "",          # filled at runtime with persona name
        "label_col": "#45a5ff",
        "pulse":     False,
    },
    "muted": {
        "border":    "#ff4444",
        "glow":      "#ff444400",
        "glow_alpha": 0.0,
        "fill":      "#1a1a2e",
        "icon":      "MUTE",
        "label":     "MUTED",
        "label_col": "#ff4444",
        "pulse":     False,
    },
}


class VoiceOrb(QWidget):
    """52px circular voice button with Iron Man HUD aesthetic."""

    clicked      = Signal()
    mute_toggled = Signal(bool)   # True = now muted

    DIAMETER = 52

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setFixedSize(self.DIAMETER + 20, self.DIAMETER + 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setToolTip("Voice interface — click to activate, right-click to mute")

        self._state      = "idle"
        self._muted      = False
        self._phase      = 0.0     # animation phase 0..2π
        self._wave_bars  = [0.3, 0.6, 1.0, 0.7, 0.4]   # waveform heights

        # Animation timer — 30fps
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        """Set display state: 'idle' | 'listening' | 'speaking' | 'muted'"""
        if state not in _STATE_CONFIG:
            return
        self._state = state
        self.update()

    def state(self) -> str:
        return self._state

    # ── Animation ─────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._phase = (self._phase + 0.08) % (2 * math.pi)
        # Animate waveform bars when listening
        if self._state == "listening":
            import random
            self._wave_bars = [
                0.2 + 0.8 * abs(math.sin(self._phase + i * 0.7))
                for i in range(5)
            ]
        self.update()

    # ── Paint ──────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        cfg   = _STATE_CONFIG[self._state]
        cx    = self.width() // 2
        cy    = self.DIAMETER // 2 + 8
        r     = self.DIAMETER // 2

        # ── Glow (outermost) ─────────────────────────────────────────────────
        glow_alpha = cfg["glow_alpha"]
        if cfg["pulse"]:
            glow_alpha *= 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._phase))

        glow_color = QColor(cfg["glow"])
        glow_color.setAlphaF(glow_alpha * 0.4)
        for spread in range(12, 0, -2):
            gc = QColor(cfg["glow"])
            gc.setAlphaF(glow_alpha * (spread / 12) * 0.15)
            p.setBrush(QBrush(gc))
            p.setPen(Qt.NoPen)
            p.drawEllipse(cx - r - spread, cy - r - spread,
                          (r + spread) * 2, (r + spread) * 2)

        # ── Fill ──────────────────────────────────────────────────────────────
        fill = QColor(cfg["fill"])
        p.setBrush(QBrush(fill))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # ── Border ────────────────────────────────────────────────────────────
        border_alpha = 0.6 + 0.4 * (0.5 + 0.5 * math.sin(self._phase)) if cfg["pulse"] else 1.0
        bc = QColor(cfg["border"])
        bc.setAlphaF(border_alpha)
        pen = QPen(bc, 2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(cx - r + 1, cy - r + 1, (r - 1) * 2, (r - 1) * 2)

        # ── Icon ──────────────────────────────────────────────────────────────
        icon_col = QColor(cfg["border"])
        p.setPen(icon_col)

        if self._state == "listening":
            # Animated waveform bars
            bar_w  = 3
            bar_gap = 2
            total_w = len(self._wave_bars) * bar_w + (len(self._wave_bars) - 1) * bar_gap
            bx = cx - total_w // 2
            for i, h in enumerate(self._wave_bars):
                bh = int(16 * h)
                p.fillRect(
                    bx + i * (bar_w + bar_gap),
                    cy - bh // 2,
                    bar_w, bh,
                    icon_col
                )
        elif self._state == "speaking":
            # Speaker shape (simplified)
            p.setFont(QFont(_get_mono_font(), 16))
            p.drawText(QRect(cx - 12, cy - 12, 24, 24), Qt.AlignCenter, "♫")
        elif self._state == "muted":
            # Mic with slash
            p.setFont(QFont(_get_mono_font(), 14))
            p.drawText(QRect(cx - 10, cy - 12, 24, 24), Qt.AlignCenter, "⊘")
        else:
            # Mic symbol
            p.setFont(QFont(_get_mono_font(), 14))
            p.drawText(QRect(cx - 10, cy - 12, 24, 24), Qt.AlignCenter, "🎙")

        # ── Label below orb ───────────────────────────────────────────────────
        label = cfg["label"]
        if self._state == "speaking":
            import config as _cfg
            label = getattr(_cfg, "ACTIVE_PERSONA", "jarvis").upper()
        if label:
            lc = QColor(cfg["label_col"])
            p.setPen(lc)
            p.setFont(QFont(_get_mono_font(), 7))
            p.drawText(
                QRect(0, cy + r + 4, self.width(), 14),
                Qt.AlignCenter,
                label
            )

        p.end()

    # ── Mouse events ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        elif event.button() == Qt.RightButton:
            self._muted = not self._muted
            self.set_state("muted" if self._muted else "idle")
            self.mute_toggled.emit(self._muted)
        super().mousePressEvent(event)


def _get_mono_font() -> str:
    try:
        import config as _cfg
        return _cfg.MONO
    except Exception:
        return "Consolas"
