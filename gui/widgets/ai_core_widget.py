"""
gui/widgets/ai_core_widget.py — AI CORE full-panel display.

Full-height animated panel showing:
  - Spinning ring orb with breathing core and hexagonal accents
  - Left ambient column: persona, voice, STT, uptime
  - Right ambient column: tokens, local%, est. cost
  - State label below orb: "NEURAL CORE ACTIVE"
  - Horizontal scan line animation
"""
from __future__ import annotations

import math
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient,
    QConicalGradient, QLinearGradient,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

import config as _cfg
from config import P


# ── Hex helpers ────────────────────────────────────────────────────────────────

def _hex_points(cx: float, cy: float, r: float, angle_offset: float = 0.0):
    pts = []
    for i in range(6):
        a = math.radians(60 * i + angle_offset)
        pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _draw_hex(painter: QPainter, cx, cy, r, angle_offset=0.0):
    pts = _hex_points(cx, cy, r, angle_offset)
    path = QPainterPath()
    path.moveTo(pts[0])
    for p in pts[1:]:
        path.lineTo(p)
    path.closeSubpath()
    painter.drawPath(path)


# ── Orb canvas ─────────────────────────────────────────────────────────────────

class _OrbCanvas(QWidget):
    """Animated orb: spinning rings + breathing core + hexagonal accents + scan line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = 0.0          # animation time (seconds)
        self._scan_y = 0.0     # scan line Y fraction 0.0–1.0
        self._scan_dir = 1
        self.setMinimumSize(260, 260)

    def tick(self, dt: float):
        self._t += dt
        self._scan_y += dt * 0.18 * self._scan_dir
        if self._scan_y >= 1.0:
            self._scan_y = 1.0
            self._scan_dir = -1
        elif self._scan_y <= 0.0:
            self._scan_y = 0.0
            self._scan_dir = 1
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        W = self.width()
        H = self.height()
        cx = W / 2
        cy = H / 2
        t  = self._t

        arc_color  = QColor(P["arc"])
        arc_dim    = QColor(P["arc_d"])
        arc_glow   = QColor(P["arc"])
        arc_glow.setAlpha(18)

        # ── Background radial glow ──────────────────────────────────────────
        grad = QRadialGradient(cx, cy, min(W, H) * 0.5)
        grad.setColorAt(0.0, QColor(P["arc"]).darker(400))
        grad.setColorAt(0.0, QColor(22, 40, 60, 80))
        grad.setColorAt(1.0, QColor(P["base"]).darker(110))
        painter.fillRect(0, 0, W, H, grad)

        r_core = min(W, H) * 0.12   # breathing core radius

        # ── Outer decorative hex ────────────────────────────────────────────
        hex_r   = min(W, H) * 0.42
        hex_rot = t * 3.0   # slow rotation deg/s
        pen = QPen(arc_color, 0.8)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        _draw_hex(painter, cx, cy, hex_r, hex_rot)

        # ── Mid decorative hex (counter-rotate) ────────────────────────────
        hex_r2 = min(W, H) * 0.32
        painter.setPen(QPen(arc_dim, 0.6))
        _draw_hex(painter, cx, cy, hex_r2, -hex_rot * 0.7 + 30)

        # ── Spinning rings ──────────────────────────────────────────────────
        for i, (ring_r, speed, width, alpha) in enumerate([
            (min(W, H) * 0.38, 40.0,  1.2, 180),
            (min(W, H) * 0.30, -28.0, 0.8, 120),
            (min(W, H) * 0.22,  60.0, 0.6, 80),
        ]):
            angle_deg = (t * speed) % 360
            arc_pen   = QColor(P["arc"])
            arc_pen.setAlpha(alpha)
            pen = QPen(arc_pen, width)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            # Draw arc segment (200°) rotated by angle
            painter.drawArc(rect, int(angle_deg * 16), int(200 * 16))

        # ── Tick marks on outer ring ────────────────────────────────────────
        tick_r  = min(W, H) * 0.40
        tick_r2 = tick_r - 8
        painter.setPen(QPen(arc_dim, 0.8))
        for i in range(24):
            a = math.radians(360 / 24 * i + t * 15)
            x1 = cx + tick_r  * math.cos(a)
            y1 = cy + tick_r  * math.sin(a)
            x2 = cx + tick_r2 * math.cos(a)
            y2 = cy + tick_r2 * math.sin(a)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # ── Dot accents on hex corners ──────────────────────────────────────
        dot_col = QColor(P["arc"])
        dot_col.setAlpha(200)
        painter.setBrush(dot_col)
        painter.setPen(Qt.NoPen)
        for pt in _hex_points(cx, cy, hex_r, hex_rot):
            painter.drawEllipse(pt, 3, 3)

        # ── Breathing core ──────────────────────────────────────────────────
        breath   = 0.85 + 0.15 * math.sin(t * 1.8)   # 0.85–1.0
        core_r   = r_core * breath
        core_grad = QRadialGradient(cx, cy, core_r)
        arc_full  = QColor(P["arc"])
        arc_full.setAlpha(255)
        arc_mid   = QColor(P["arc"])
        arc_mid.setAlpha(100)
        arc_none  = QColor(P["arc"])
        arc_none.setAlpha(0)
        core_grad.setColorAt(0.0, arc_full)
        core_grad.setColorAt(0.6, arc_mid)
        core_grad.setColorAt(1.0, arc_none)
        painter.setPen(Qt.NoPen)
        painter.setBrush(core_grad)
        painter.drawEllipse(QPointF(cx, cy), core_r * 1.5, core_r * 1.5)

        # Solid core center
        painter.setBrush(QColor(P["arc"]))
        painter.drawEllipse(QPointF(cx, cy), core_r * 0.6, core_r * 0.6)

        # ── Scan line ───────────────────────────────────────────────────────
        scan_y_px  = self._scan_y * H
        scan_alpha = int(40 + 30 * math.sin(t * 4))
        scan_color = QColor(P["arc"])
        scan_color.setAlpha(scan_alpha)
        grad_line = QLinearGradient(0, scan_y_px, W, scan_y_px)
        grad_line.setColorAt(0.0, QColor(P["arc"]).darker(300))
        grad_line.setColorAt(0.4, scan_color)
        grad_line.setColorAt(0.6, scan_color)
        grad_line.setColorAt(1.0, QColor(P["arc"]).darker(300))
        painter.setPen(QPen(QColor(grad_line.stops()[1][1]), 1))
        painter.drawLine(0, int(scan_y_px), W, int(scan_y_px))

        painter.end()


# ── Data column helper ─────────────────────────────────────────────────────────

class _DataColumn(QWidget):
    def __init__(self, title: str, rows: list[str], parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 12, 8, 12)
        v.setSpacing(10)

        hdr = QLabel(title)
        hdr.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';"
            f"font-size:7px;letter-spacing:3px;font-weight:600;"
        )
        v.addWidget(hdr)

        self._value_labels: dict[str, QLabel] = {}
        for row_key in rows:
            row_w = QWidget(); row_w.setStyleSheet("background:transparent;")
            rh = QHBoxLayout(row_w); rh.setContentsMargins(0, 0, 0, 0); rh.setSpacing(6)
            k = QLabel(row_key)
            k.setStyleSheet(
                f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;"
            )
            vl = QLabel("—")
            vl.setStyleSheet(
                f"color:{P['arc']};font-family:'{_cfg.MONO}';font-size:8px;font-weight:700;"
            )
            rh.addWidget(k)
            rh.addStretch()
            rh.addWidget(vl)
            self._value_labels[row_key] = vl
            v.addWidget(row_w)

        v.addStretch()

    def set_value(self, key: str, value: str):
        if key in self._value_labels:
            self._value_labels[key].setText(value)


# ── Main AI CORE widget ────────────────────────────────────────────────────────

class AICoreWidget(QWidget):
    """Full-height AI CORE panel — orb + ambient data + scan line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{P['base']};")
        self._boot_time = time.time()
        self._last_tick  = time.time()

        # ── Layout: left column | orb | right column ──────────────────────
        root_h = QHBoxLayout(self)
        root_h.setContentsMargins(24, 20, 24, 20)
        root_h.setSpacing(0)

        # Left column
        self._left = _DataColumn("SYSTEM STATUS", ["PERSONA", "VOICE", "STT", "UPTIME"])
        self._left.setFixedWidth(160)
        root_h.addWidget(self._left)

        # Center: orb + label
        center_v = QVBoxLayout()
        center_v.setContentsMargins(0, 0, 0, 0)
        center_v.setSpacing(12)
        center_v.addStretch()

        self._orb = _OrbCanvas()
        center_v.addWidget(self._orb, 0, Qt.AlignCenter)

        self._state_lbl = QLabel("NEURAL CORE ACTIVE")
        self._state_lbl.setAlignment(Qt.AlignCenter)
        self._state_lbl.setStyleSheet(
            f"color:{P['arc']};font-family:'{_cfg.MONO}';"
            f"font-size:9px;letter-spacing:5px;font-weight:700;"
            f"background:transparent;"
        )
        center_v.addWidget(self._state_lbl)

        self._sub_lbl = QLabel("")
        self._sub_lbl.setAlignment(Qt.AlignCenter)
        self._sub_lbl.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';"
            f"font-size:8px;letter-spacing:2px;background:transparent;"
        )
        center_v.addWidget(self._sub_lbl)
        center_v.addStretch()

        root_h.addLayout(center_v, 1)

        # Right column
        self._right = _DataColumn("INTELLIGENCE", ["TOKENS", "LOCAL%", "EST. COST", "MODEL"])
        self._right.setFixedWidth(160)
        root_h.addWidget(self._right)

        # ── Animation timer (33ms ≈ 30 fps) ───────────────────────────────
        self._anim_t = QTimer(self)
        self._anim_t.setInterval(33)
        self._anim_t.timeout.connect(self._tick)
        self._anim_t.start()

        # ── Data refresh (every 5s) ────────────────────────────────────────
        self._data_t = QTimer(self)
        self._data_t.setInterval(5000)
        self._data_t.timeout.connect(self._refresh_data)
        self._data_t.start()
        self._refresh_data()   # immediate first refresh

    def _tick(self):
        now = time.time()
        dt  = now - self._last_tick
        self._last_tick = now
        self._orb.tick(dt)

        # Update uptime in left column
        elapsed = int(now - self._boot_time)
        h, rem  = divmod(elapsed, 3600)
        m, s    = divmod(rem, 60)
        self._left.set_value("UPTIME", f"{h:02d}:{m:02d}:{s:02d}")

    def _refresh_data(self):
        try:
            persona = _cfg.ACTIVE_PERSONA.upper()
        except Exception:
            persona = "JARVIS"

        voice_profile = getattr(_cfg, "VOICE_DEFAULT_PROFILE", None) or "auto"
        self._left.set_value("PERSONA", persona)
        self._left.set_value("VOICE", voice_profile.upper().replace("_", " ")[:12])
        self._left.set_value("STT", "ONLINE")

        model_short = (getattr(_cfg, "OLLAMA_MODEL", "qwen3:14b") or "").split(":")[0].upper()
        self._right.set_value("MODEL", model_short)

        try:
            from llm.router import LLMRouter
            stats  = LLMRouter().get_token_stats()
            tokens = stats.get("total_tokens", 0)
            local  = stats.get("local_ratio", 0.0) * 100
            cost   = stats.get("estimated_cost_month_usd", 0.0)
            self._right.set_value("TOKENS",   f"{tokens:,}")
            self._right.set_value("LOCAL%",   f"{local:.0f}%")
            self._right.set_value("EST. COST", f"${cost:.2f}/mo")
        except Exception:
            self._right.set_value("TOKENS",   "—")
            self._right.set_value("LOCAL%",   "100%")
            self._right.set_value("EST. COST", "$0.00/mo")

    def set_state(self, label: str, sub: str = ""):
        self._state_lbl.setText(label)
        self._sub_lbl.setText(sub)
