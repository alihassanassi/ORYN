"""
gui/widgets/orb_widget.py — JARVIS Iron Circuit AI Core orb.

Full-canvas animated HUD. Fills its entire parent widget.
No borders. No boxes. Pure dark space with a beating core.

Renders at 60fps via QTimer + QPainter.
Responds to theme changes via gui.theme listener.
"""
from __future__ import annotations
import math
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush,
                            QFont, QPolygonF, QLinearGradient)


class OrbWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 300)
        # no fixed size — fills parent completely

        self._t         = 0.0
        self._scan_y    = 0.0
        self._state     = "NEURAL CORE ACTIVE"
        self._sub_state = "STANDING BY"
        self._uptime_s  = 0

        self._persona  = "JARVIS"
        self._voice    = "CHATTERBOX"
        self._stt      = "WHISPER"
        self._context  = "8K"
        self._tokens   = "0"
        self._local    = "94%"
        self._cost     = "$0.00/mo"
        self._research = "STANDBY"
        self._recon    = "DISABLED"
        self._model    = "qwen3:14b"

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)  # 60fps

        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._tick_uptime)
        self._uptime_timer.start(1000)

        try:
            from gui.theme import theme as _t
            _t.add_change_listener(self.update)
        except Exception:
            pass

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_state(self, state: str, sub: str = "STANDING BY") -> None:
        self._state = state
        self._sub_state = sub
        self.update()

    def set_persona(self, name: str) -> None:
        self._persona = name.upper()
        self.update()

    def set_ambient(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self, f"_{k}"):
                setattr(self, f"_{k}", str(v))
        self.update()

    # ── Animation ──────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._t += 0.016
        h = self.height() if self.height() > 0 else 400
        self._scan_y = (self._scan_y + h / (8.0 * 60)) % h
        self.update()

    def _tick_uptime(self) -> None:
        self._uptime_s += 1

    def _accent(self) -> QColor:
        try:
            from gui.theme import theme as _t
            return QColor(_t.accent())
        except Exception:
            return QColor("#00d4b1")

    def _warm(self) -> QColor:
        try:
            from gui.theme import theme as _t
            return QColor(_t.warm())
        except Exception:
            return QColor("#ff6b35")

    def _bg(self) -> QColor:
        try:
            from gui.theme import theme as _t
            return QColor(_t.bg(1))
        except Exception:
            return QColor("#060b10")

    def _t2(self) -> QColor:
        try:
            from gui.theme import theme as _t
            return QColor(_t.text(2))
        except Exception:
            return QColor("#6a8fa0")

    def _t3(self) -> QColor:
        try:
            from gui.theme import theme as _t
            return QColor(_t.text(3))
        except Exception:
            return QColor("#3a5566")

    # ── Paint ──────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        ac = self._accent()

        # Background
        p.fillRect(0, 0, W, H, self._bg())

        # HUD corner brackets
        bracket_c = QColor(ac)
        bracket_c.setAlpha(120)
        pen = QPen(bracket_c, 1.0)
        p.setPen(pen)
        S = 18
        for bx, by, dx, dy in [(8,8,1,1),(W-8,8,-1,1),(8,H-8,1,-1),(W-8,H-8,-1,-1)]:
            p.drawLine(bx, by, bx + dx*S, by)
            p.drawLine(bx, by, bx, by + dy*S)

        # Scan line
        sy = int(self._scan_y)
        grad = QLinearGradient(0, sy, W, sy)
        trans = QColor(0, 0, 0, 0)
        scan_c = QColor(ac); scan_c.setAlpha(80)
        grad.setColorAt(0.0, trans)
        grad.setColorAt(0.3, scan_c)
        grad.setColorAt(0.5, QColor(ac.red(), ac.green(), ac.blue(), 140))
        grad.setColorAt(0.7, scan_c)
        grad.setColorAt(1.0, trans)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(0, sy - 1, W, 2)

        # Orb center
        cx, cy = W // 2, H // 2

        rings = [
            (85, True,  self._t * -1.1,  22, True),
            (66, True,  self._t *  0.88, 16, True),
            (47, False, 0.0,              0, False),
        ]

        ring_alphas = [55, 36, 76]
        for idx, (r, animated, angle, _, dashed) in enumerate(rings):
            ring_c = QColor(ac)
            ring_c.setAlpha(ring_alphas[idx])
            pen2 = QPen(ring_c, 0.8)
            if dashed:
                pen2.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen2)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.save()
            p.translate(cx, cy)
            if animated:
                p.rotate(math.degrees(angle))
            p.drawEllipse(QRectF(-r, -r, r*2, r*2))
            p.restore()

        # Hexagonal corner accents at N/E/S/W
        for hx, hy in [(cx, cy-86), (cx+86, cy), (cx, cy+86), (cx-86, cy)]:
            self._draw_hex(p, hx, hy, 4, ac)

        # Core sphere
        sphere_r = 28
        sphere_fill = QColor(ac); sphere_fill.setAlpha(18)
        p.setBrush(QBrush(sphere_fill))
        p.setPen(QPen(QColor(ac.red(), ac.green(), ac.blue(), 180), 1.0))
        p.drawEllipse(QRectF(cx - sphere_r, cy - sphere_r, sphere_r*2, sphere_r*2))

        # Inner pulse
        pulse = 0.85 + math.sin(self._t * 2.2) * 0.15
        ip_r = int(13 * pulse)
        ip_fill = QColor(ac); ip_fill.setAlpha(int(38 * pulse))
        p.setBrush(QBrush(ip_fill))
        p.setPen(QPen(QColor(ac.red(), ac.green(), ac.blue(), 200), 1.0))
        p.drawEllipse(QRectF(cx - ip_r, cy - ip_r, ip_r*2, ip_r*2))

        # State label
        p.setPen(self._accent())
        p.setFont(QFont("Courier New", 10))
        p.drawText(QRectF(0, cy + 95, W, 20),
                   Qt.AlignmentFlag.AlignCenter, self._state)
        p.setPen(self._t2())
        p.setFont(QFont("Courier New", 8))
        p.drawText(QRectF(0, cy + 113, W, 16),
                   Qt.AlignmentFlag.AlignCenter, self._sub_state)

        # Left ambient data
        lx = 14
        left_rows = [
            ("PERSONA", self._persona,  False),
            ("VOICE",   self._voice,    False),
            ("STT",     self._stt,      False),
            ("CONTEXT", self._context,  False),
            ("UPTIME",  self._uptime_str(), False),
        ]
        start_y = H // 2 - len(left_rows) * 12
        mono_sm = QFont("Courier New", 8)
        for i, (lbl, val, warm) in enumerate(left_rows):
            ly = start_y + i * 24
            p.setFont(mono_sm)
            p.setPen(self._t3())
            p.drawText(lx, ly, lbl)
            p.setPen(self._warm() if warm else self._accent())
            p.drawText(lx, ly + 13, val)

        # Right ambient data
        right_rows = [
            ("TOKENS",   self._tokens,   True),
            ("LOCAL %",  self._local,    False),
            ("COST/MTH", self._cost,     True),
            ("RESEARCH", self._research, False),
            ("RECON",    self._recon,    True),
        ]
        start_y2 = H // 2 - len(right_rows) * 12
        for i, (lbl, val, warm) in enumerate(right_rows):
            ry = start_y2 + i * 24
            p.setFont(mono_sm)
            p.setPen(self._t3())
            tw = p.fontMetrics().horizontalAdvance(lbl)
            p.drawText(W - tw - lx, ry, lbl)
            p.setPen(self._warm() if warm else self._accent())
            vw = p.fontMetrics().horizontalAdvance(val)
            p.drawText(W - vw - lx, ry + 13, val)

        p.end()

    def _draw_hex(self, p: QPainter, cx: float, cy: float,
                   r: float, color: QColor) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        pts = []
        for i in range(6):
            a = math.pi / 3 * i
            pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        p.drawPolygon(QPolygonF(pts))

    def _uptime_str(self) -> str:
        h = self._uptime_s // 3600
        m = (self._uptime_s % 3600) // 60
        s = self._uptime_s % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
