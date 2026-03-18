"""
gui/widgets.py — Custom-drawn PySide6 widgets.

ArcReactor     — Animated arc reactor logo (states: idle/speaking/listening/busy/error)
PTT            — Push-to-talk button (idle/rec/proc states)
ThinkDots      — Animated thinking indicator (3 dots)
WaveformVisualizer — Oscilloscope-style bar visualizer (no real audio dependency)
Bubble         — Chat message bubble (role: user/assistant/tool)
ProposalCard   — Autonomous agent proposal card (approve/reject)
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRect, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QPainter, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QMetaObject, Q_ARG, Slot

import config as _cfg
from config import P, MONO


# ── Arc Reactor ───────────────────────────────────────────────────────────────

class ArcReactor(QWidget):
    """Animated arc reactor. States: idle, speaking, listening, busy, error."""

    _STATE_COLORS = {
        "idle":      "#00f0c8",
        "speaking":  "#00f0c8",
        "listening": "#ffa020",
        "busy":      "#ffa020",
        "error":     "#ff3355",
    }

    def __init__(self, size: int = 54, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._angle       = 0.0
        self._pulse       = 0.0
        self._pulse_d     = 1.0
        self._state       = "idle"
        self._ring_expand = 0.0
        self._qc  = QColor(self._STATE_COLORS["idle"])
        self._qc2 = QColor(self._STATE_COLORS["idle"]); self._qc2.setAlpha(140)
        self._qcc = QColor(self._STATE_COLORS["idle"])
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._t.isActive():
            self._t.start(33)

    def set_state(self, state: str):
        if self._state == state:
            return
        self._state = state
        col = self._STATE_COLORS.get(state, self._STATE_COLORS["idle"])
        self._qc  = QColor(col)
        self._qc2 = QColor(col); self._qc2.setAlpha(140)
        self._qcc = QColor(col)

    def _tick(self):
        speed = {"speaking": 3.2, "busy": 2.8, "listening": 0.25}.get(self._state, 0.6)
        self._angle = (self._angle + speed) % 360

        if self._state == "speaking":
            step = 0.045
        elif self._state == "listening":
            step = 0.012
        elif self._state == "busy":
            step = 0.03
        else:
            step = 0.015

        self._pulse = max(0.0, min(1.0, self._pulse + step * self._pulse_d))
        if self._pulse >= 1.0: self._pulse_d = -1.0
        if self._pulse <= 0.0: self._pulse_d =  1.0

        if self._state == "speaking":
            self._ring_expand = min(1.0,  self._ring_expand + 0.06)
        elif self._state == "listening":
            self._ring_expand = max(-0.5, self._ring_expand - 0.025)
        else:
            self._ring_expand *= 0.92

        self.update()

    def paintEvent(self, _):
        p   = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        sz  = self._size
        cx  = cy = sz / 2
        r   = sz * 0.37
        pf  = self._pulse

        expand = self._ring_expand * r * 0.18
        r_draw = r + expand

        # Background disc
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(P["card"]))
        p.drawEllipse(int(cx - r*1.45), int(cy - r*1.45), int(r*2.9), int(r*2.9))

        # Outer glow
        glow_mult = 1.6 if self._state in ("speaking", "listening") else 1.0
        gr = r_draw * 1.6 + pf * 8
        gc = QColor(self._qc); gc.setAlpha(int((18 + 38 * pf) * glow_mult))
        g  = QRadialGradient(cx, cy, gr)
        g.setColorAt(0, gc); g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(g)); p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx - gr), int(cy - gr), int(gr*2), int(gr*2))

        # Outer spinning arc
        pen = QPen(self._qc, 2.2); pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawArc(QRect(int(cx-r_draw), int(cy-r_draw), int(r_draw*2), int(r_draw*2)),
                  int(self._angle * 16), int(255 * 16))

        # Counter-rotating inner arc
        r2   = (r + expand * 0.6) * 0.62
        pen2 = QPen(self._qc2, 1.4); pen2.setCapStyle(Qt.RoundCap)
        p.setPen(pen2)
        p.drawArc(QRect(int(cx-r2), int(cy-r2), int(r2*2), int(r2*2)),
                  int((-self._angle * 1.7) % 360 * 16), int(110 * 16))

        # Core pulse
        cr = r * 0.22
        cc = QColor(self._qcc); cc.setAlpha(int(190 + 65 * pf))
        cg = QRadialGradient(cx, cy, cr * 2.2)
        cg.setColorAt(0, cc); cg.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(cg)); p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx-cr), int(cy-cr), int(cr*2), int(cr*2))
        p.end()


# ── Push-To-Talk Button ───────────────────────────────────────────────────────

class PTT(QWidget):
    pressed  = Signal()
    released = Signal()

    IDLE, REC, PROC = "idle", "rec", "proc"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 76)
        self._state   = self.IDLE
        self._enabled = False
        self._pulse   = 0.0
        self._pd      = 1.0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def _tick(self):
        spd = 6.0 if self._state == self.REC else 2.0
        self._pulse = max(0.0, min(1.0, self._pulse + 0.02 * spd * self._pd))
        if self._pulse >= 1.0: self._pd = -1.0
        if self._pulse <= 0.0: self._pd =  1.0
        self.update()

    def set_enabled(self, v: bool):
        self._enabled = v
        if not v:
            self._t.stop(); self._state = self.IDLE; self._pulse = 0
        self.update()

    def set_state(self, s: str):
        QMetaObject.invokeMethod(self, "_apply_state",
                                 Qt.QueuedConnection, Q_ARG(str, s))

    @Slot(str)
    def _apply_state(self, s: str):
        self._state = s
        if s != self.IDLE: self._t.start(33)
        else: self._t.stop(); self._pulse = 0
        self.update()

    def paintEvent(self, _):
        p  = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = cy = 38; r = 30; pf = self._pulse

        if not self._enabled:
            p.setPen(Qt.NoPen); p.setBrush(QColor(P["card"]))
            p.drawEllipse(cx-r, cy-r, r*2, r*2)
            p.setPen(QPen(QColor(P["b1"]), 1.5)); p.setBrush(Qt.NoBrush)
            p.drawEllipse(cx-r+1, cy-r+1, r*2-2, r*2-2)
            p.setPen(QColor(P["t2"])); p.setFont(QFont(MONO, 15))
            p.drawText(QRect(0, 0, 76, 76), Qt.AlignCenter, "🎤")
            p.end(); return

        col = {self.REC: P["red"], self.PROC: P["amber"]}.get(self._state, P["arc"])

        gr = r + 16 + int(12 * pf)
        g  = QRadialGradient(cx, cy, gr)
        gc = QColor(col); gc.setAlpha(int(30 + 70 * pf))
        g.setColorAt(0, gc); g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(g))
        p.drawEllipse(cx-gr, cy-gr, gr*2, gr*2)

        p.setBrush(QColor(col).darker(240)); p.setPen(Qt.NoPen)
        p.drawEllipse(cx-r, cy-r, r*2, r*2)
        p.setPen(QPen(QColor(col), 2.2)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(cx-r+1, cy-r+1, r*2-2, r*2-2)

        if self._state == self.REC:
            p.setBrush(QColor("white")); p.setPen(Qt.NoPen)
            p.drawRoundedRect(cx-11, cy-11, 22, 22, 4, 4)
        elif self._state == self.PROC:
            p.setPen(QColor("white")); p.setFont(QFont(MONO, 9, QFont.Bold))
            p.drawText(QRect(0, 0, 76, 76), Qt.AlignCenter, "…")
        else:
            p.setPen(QColor("white")); p.setFont(QFont(MONO, 16))
            p.drawText(QRect(0, 0, 76, 76), Qt.AlignCenter, "🎤")
        p.end()

    def mousePressEvent(self, e):
        if self._enabled and self._state == self.IDLE:
            self._apply_state(self.REC)
            self.pressed.emit()

    def mouseReleaseEvent(self, e):
        if self._enabled and self._state == self.REC:
            self._apply_state(self.PROC)
            self.released.emit()


# ── Thinking Dots ─────────────────────────────────────────────────────────────

class ThinkDots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 28)
        self._f = 0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._t.isActive():
            self._t.start(220)

    def _tick(self):
        self._f = (self._f + 1) % 5
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i in range(3):
            lit = self._f > i
            c   = QColor(P["arc"] if lit else P["t3"])
            p.setBrush(QBrush(c)); p.setPen(Qt.NoPen)
            p.drawEllipse(8 + i * 18, 10, 8, 8)
        p.end()


# ── Waveform Visualizer ───────────────────────────────────────────────────────

class WaveformVisualizer(QWidget):
    """Oscilloscope-style bar visualizer. Pure animation — no real audio dependency."""

    BARS = 64

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self._state  = "idle"
        self._bars   = [0.0] * self.BARS
        self._phase  = 0.0
        self._breath = 0.0
        self._bd     = 1.0
        self._brush  = QBrush(QColor(P["arc_d"]))
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(33)

    def set_state(self, state: str):
        if self._state == state:
            return
        self._state = state
        if state == "idle":
            c = QColor(P["arc_d"]); c.setAlpha(80)
        elif state == "mic":
            c = QColor(P["amber"]); c.setAlpha(210)
        else:
            c = QColor(P["arc"]);   c.setAlpha(195)
        self._brush = QBrush(c)

    def _tick(self):
        self._phase += 0.18

        if self._state == "idle":
            self._breath = max(0.0, min(1.0, self._breath + 0.012 * self._bd))
            if self._breath >= 1.0: self._bd = -1.0
            if self._breath <= 0.0: self._bd =  1.0
            amp = 0.03 + 0.03 * self._breath
            for i in range(self.BARS):
                self._bars[i] = amp * (0.5 + 0.5 * math.sin(i / 9.0 + self._phase * 0.25))

        elif self._state == "mic":
            for i in range(self.BARS):
                v = (0.40 * math.sin(i / 3.5 + self._phase * 2.8)
                   + 0.25 * math.sin(i / 7.0 + self._phase * 1.6)
                   + 0.35)
                self._bars[i] = max(0.08, min(1.0, v))

        elif self._state == "speak":
            for i in range(self.BARS):
                v = (0.28 * math.sin(i / 3.0  + self._phase * 3.2)
                   + 0.18 * math.sin(i / 5.5  + self._phase * 2.0)
                   + 0.14 * math.sin(i / 9.0  + self._phase * 1.1)
                   + 0.40)
                self._bars[i] = max(0.0, min(1.0, v))

        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        p.fillRect(0, 0, w, h, QColor(P["void"]))

        bar_w = w / self.BARS
        half  = h / 2.0
        p.setBrush(self._brush)
        p.setPen(Qt.NoPen)
        bw = max(1, int(bar_w) - 1)
        for i in range(self.BARS):
            bh = max(2, int(self._bars[i] * (h - 6)))
            x  = int(i * bar_w) + 1
            y  = int(half - bh / 2)
            p.drawRect(x, y, bw, bh)
        p.end()


# ── Message Bubble ────────────────────────────────────────────────────────────

class Bubble(QFrame):
    def __init__(self, role: str, content: str, ts: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(8)

        # Header
        hrow = QHBoxLayout(); hrow.setSpacing(8)
        if role == "assistant":
            who_text  = "J.A.R.V.I.S."
            who_color = P["arc"]
        elif role == "user":
            who_text  = "YOU"
            who_color = P["t1"]
        else:
            who_text  = "⚙  SYSTEM"
            who_color = P["amber"]

        who = QLabel(who_text)
        who.setStyleSheet(
            f"color:{who_color};font-family:'{MONO}';font-size:9px;"
            f"font-weight:700;letter-spacing:2.5px;background:transparent;"
        )
        ts_lbl = QLabel(ts)
        ts_lbl.setStyleSheet(
            f"color:{P['t3']};font-family:'{MONO}';font-size:9px;background:transparent;"
        )
        hrow.addWidget(who); hrow.addWidget(ts_lbl); hrow.addStretch()
        lay.addLayout(hrow)

        # Body
        body = QLabel(content)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)

        if role == "assistant":
            body.setStyleSheet(
                f"color:{P['t0']};font-family:'{MONO}';font-size:12px;"
                f"line-height:185%;background:transparent;"
            )
        elif role == "user":
            body.setStyleSheet(
                f"color:{P['t1']};font-family:'{MONO}';font-size:12px;"
                f"line-height:175%;background:transparent;"
            )
        else:
            body.setStyleSheet(
                f"color:{P['t1']};font-family:'{MONO}';font-size:10px;"
                f"line-height:160%;padding:10px 14px;"
                f"background:{P['void']};border:1px solid {P['b0']};"
                f"border-left:3px solid {P['amber']};border-radius:4px;"
            )
        lay.addWidget(body)
        self._body = body

        # Divider
        div = QFrame(); div.setFixedHeight(1)
        div.setStyleSheet(f"background:{P['b0']};margin-top:4px;")
        lay.addWidget(div)

    def append_text(self, chunk: str):
        self._body.setText(self._body.text() + chunk)


# ── Proposal Card ─────────────────────────────────────────────────────────────

class ProposalCard(QFrame):
    approved = Signal(str)
    rejected = Signal(str)

    def __init__(self, proposal: dict, parent=None):
        super().__init__(parent)
        pid = proposal["id"]
        col = {"high": P["red"], "medium": P["amber"], "low": P["arc_d"]}.get(
            proposal.get("priority", "medium"), P["amber"]
        )
        self.setStyleSheet(
            f"QFrame{{background:{P['card']};border:1px solid {col}33;"
            f"border-left:3px solid {col};border-radius:5px;}}"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8); v.setSpacing(8)

        title = QLabel(proposal.get("title", "Task"))
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color:{P['t0']};font-family:'{MONO}';font-size:11px;"
            f"font-weight:700;background:transparent;border:none;"
        )

        desc = proposal.get("description", "")
        if len(desc) > 80: desc = desc[:80] + "…"
        d_lbl = QLabel(desc)
        d_lbl.setWordWrap(True)
        d_lbl.setStyleSheet(
            f"color:{P['t1']};font-family:'{MONO}';font-size:10px;"
            f"background:transparent;border:none;"
        )

        row = QHBoxLayout(); row.setSpacing(6)

        ok = QPushButton("✓  Approve")
        ok.setCursor(QCursor(Qt.PointingHandCursor))
        ok.setStyleSheet(
            f"QPushButton{{background:{P['green']}1a;color:{P['green']};"
            f"border:1px solid {P['green']}44;border-radius:3px;"
            f"font-family:'{MONO}';font-size:10px;padding:4px 10px;}}"
            f"QPushButton:hover{{background:{P['green']}33;}}"
        )
        ok.clicked.connect(lambda: self.approved.emit(pid))

        no = QPushButton("✗  Skip")
        no.setCursor(QCursor(Qt.PointingHandCursor))
        no.setStyleSheet(
            f"QPushButton{{background:transparent;color:{P['t2']};"
            f"border:1px solid {P['b1']};border-radius:3px;"
            f"font-family:'{MONO}';font-size:10px;padding:4px 10px;}}"
            f"QPushButton:hover{{color:{P['red']};border-color:{P['red']}44;}}"
        )
        no.clicked.connect(lambda: self.rejected.emit(pid))

        row.addWidget(ok); row.addWidget(no); row.addStretch()
        v.addWidget(title); v.addWidget(d_lbl); v.addLayout(row)
