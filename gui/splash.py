"""
gui/splash.py — JARVIS animated boot splash screen.

Shown immediately when the app starts; emits boot_complete when the
fade-out finishes so main.py can show the main window at the right time.

Design:
  Left 1/3  — animated concentric rings + sweeping arcs (60 fps)
  Right 2/3 — system label, J.A.R.V.I.S. title, progress bar, boot ticker
  Corners   — L-bracket accents matching the main HUD
  Bottom    — separator + secure-boot status line
"""
from __future__ import annotations

import math
from PySide6.QtCore import Qt, QTimer, QPoint, QRectF, Signal
from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont,
    QLinearGradient, QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

# ── Palette (mirrors config.P) ─────────────────────────────────────────────
_BASE  = "#0e1621"
_PANEL = "#142233"
_ARC   = "#18e0c1"
_BLUE  = "#3aa0ff"
_T1    = "#e6f2ff"
_T2    = "#8ca4be"
_T3    = "#4a6070"
_B0    = "#1f3050"

# ── Boot sequence messages ─────────────────────────────────────────────────
_MSGS = [
    "INITIALIZING NEURAL CORE",
    "LOADING LANGUAGE MODEL",
    "ESTABLISHING BRIDGE LINK",
    "SCANNING ENVIRONMENT",
    "LOADING TOOL REGISTRY",
    "CALIBRATING VOICE SYSTEMS",
    "SECURING EXECUTION CONTEXT",
    "ALL SYSTEMS NOMINAL",
]

_W, _H = 920, 560   # fixed window dimensions


class JarvisSplash(QWidget):
    """Animated boot splash.  Call show() before creating the main window."""

    boot_complete = Signal()

    def __init__(self, total_ms: int = 3200, parent=None):
        super().__init__(parent)
        # Fire startup sound immediately (non-blocking; fails silently if
        # sound engine not yet started or audio device unavailable)
        try:
            from audio.sound_engine import play as _play, start as _sstart
            _sstart()
            _play("ui_startup")
        except Exception:
            pass
        self._total_ms  = total_ms
        self._progress  = 0.0
        self._msg_idx   = 0
        self._angle     = 0.0      # outer-ring sweep angle (degrees)
        self._frame     = 0
        self._phase     = 0        # 0 = booting, 1 = fade-out
        self._opacity   = 1.0

        # ── Window flags ──────────────────────────────────────────────────
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedSize(_W, _H)
        self._center_on_screen()

        # ── 60 fps animation tick ─────────────────────────────────────────
        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._tick)
        self._anim.start()

        # ── Message timer (advances every total_ms / num_msgs ms) ─────────
        step = max(80, total_ms // len(_MSGS))
        self._msg_timer = QTimer(self)
        self._msg_timer.setInterval(step)
        self._msg_timer.timeout.connect(self._next_msg)
        self._msg_timer.start()

        # ── Schedule fade-out ─────────────────────────────────────────────
        QTimer.singleShot(total_ms, self._start_fadeout)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.geometry()
            self.move(
                sg.center().x() - _W // 2,
                sg.center().y() - _H // 2,
            )

    def _tick(self) -> None:
        self._frame += 1
        self._angle = (self._angle + 0.85) % 360.0

        if self._phase == 1:
            self._opacity = max(0.0, self._opacity - 0.048)
            self.setWindowOpacity(self._opacity)
            if self._opacity <= 0.0:
                self._anim.stop()
                self.close()
                self.boot_complete.emit()
                return

        self.update()

    def _next_msg(self) -> None:
        if self._msg_idx < len(_MSGS) - 1:
            self._msg_idx += 1
        self._progress = self._msg_idx / (len(_MSGS) - 1)
        if self._msg_idx == len(_MSGS) - 1:
            # All systems nominal — play confirmation tone
            try:
                from audio.sound_engine import play as _play
                _play("ui_ready")
            except Exception:
                pass

    def _start_fadeout(self) -> None:
        self._msg_timer.stop()
        self._msg_idx = len(_MSGS) - 1
        self._progress = 1.0
        self._phase = 1

    # ── Paint ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = _W, _H

        self._paint_background(p, w, h)
        self._paint_scanlines(p, w, h)
        self._paint_corners(p, w, h)
        self._paint_divider(p, w, h)
        self._paint_orb(p, w // 3 // 2, h // 2)
        self._paint_text_panel(p, w // 3 + 38, h)
        self._paint_bottom_bar(p, w, h)

        p.end()

    # ── Background + atmosphere ────────────────────────────────────────────

    def _paint_background(self, p: QPainter, w: int, h: int) -> None:
        p.fillRect(0, 0, w, h, QColor(_BASE))
        vg = QRadialGradient(w * 0.65, h * 0.45, max(w, h) * 0.75)
        vg.setColorAt(0, QColor(18, 40, 72, 35))
        vg.setColorAt(1, QColor(0, 0, 0, 110))
        p.fillRect(0, 0, w, h, vg)

    def _paint_scanlines(self, p: QPainter, w: int, h: int) -> None:
        c = QColor(255, 255, 255, 5)
        p.setPen(QPen(c, 1))
        for y in range(0, h, 4):
            p.drawLine(0, y, w, y)

    # ── Corner accents ─────────────────────────────────────────────────────

    def _paint_corners(self, p: QPainter, w: int, h: int) -> None:
        col = QColor(_ARC)
        col.setAlpha(210)
        p.setPen(QPen(col, 2))
        arm, m = 30, 14
        # top-left
        p.drawLine(m, m + arm, m, m)
        p.drawLine(m, m, m + arm, m)
        # top-right
        p.drawLine(w - m - arm, m, w - m, m)
        p.drawLine(w - m, m, w - m, m + arm)
        # bottom-left
        p.drawLine(m, h - m - arm, m, h - m)
        p.drawLine(m, h - m, m + arm, h - m)
        # bottom-right
        p.drawLine(w - m - arm, h - m, w - m, h - m)
        p.drawLine(w - m, h - m, w - m, h - m - arm)

    def _paint_divider(self, p: QPainter, w: int, h: int) -> None:
        col = QColor(_ARC)
        col.setAlpha(28)
        p.setPen(QPen(col, 1))
        p.drawLine(w // 3, 22, w // 3, h - 22)

    # ── Animated orb ───────────────────────────────────────────────────────

    def _paint_orb(self, p: QPainter, cx: int, cy: int) -> None:
        # Static concentric rings
        for r, alpha, lw in ((106, 16, 1.0), (82, 28, 1.0), (61, 42, 1.2), (40, 62, 1.4)):
            c = QColor(_ARC)
            c.setAlpha(alpha)
            p.setPen(QPen(c, lw))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPoint(cx, cy), r, r)

        # Outer sweep arc + trailing glow
        outer = 112
        sweep_col = QColor(_ARC)
        sweep_col.setAlpha(230)
        p.setPen(QPen(sweep_col, 2))
        p.setBrush(Qt.NoBrush)
        rect = QRectF(cx - outer, cy - outer, outer * 2, outer * 2)
        p.drawArc(rect, int(-self._angle * 16), 60 * 16)

        for i in range(1, 6):
            trail = QColor(_ARC)
            trail.setAlpha(max(0, 170 - i * 32))
            p.setPen(QPen(trail, max(1, 2)))
            t_start = int((-self._angle + i * 5) * 16) % (360 * 16)
            p.drawArc(rect, t_start, 22 * 16)

        # Counter-rotating inner ring sweep (blue)
        r2 = 82
        r2c = QColor(_BLUE)
        r2c.setAlpha(110)
        p.setPen(QPen(r2c, 1))
        r2r = QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2)
        r2s = int(self._angle * 16 * 0.55) % (360 * 16)
        p.drawArc(r2r, r2s, 45 * 16)

        # Inner glow
        ig = QRadialGradient(cx, cy, 32)
        ig.setColorAt(0, QColor(24, 224, 193, 110))
        ig.setColorAt(0.6, QColor(24, 224, 193, 35))
        ig.setColorAt(1, QColor(24, 224, 193, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(ig)
        p.drawEllipse(QPoint(cx, cy), 32, 32)

        # Center dot
        p.setBrush(QColor(_ARC))
        p.drawEllipse(QPoint(cx, cy), 5, 5)

        # Tick marks (every 30°)
        tick_c = QColor(_ARC)
        tick_c.setAlpha(55)
        p.setPen(QPen(tick_c, 1))
        for i in range(12):
            a = math.radians(i * 30 + self._angle * 0.1)
            x0 = int(cx + (outer - 2) * math.cos(a))
            y0 = int(cy + (outer - 2) * math.sin(a))
            x1 = int(cx + (outer + 7) * math.cos(a))
            y1 = int(cy + (outer + 7) * math.sin(a))
            p.drawLine(x0, y0, x1, y1)

    # ── Text panel ─────────────────────────────────────────────────────────

    def _paint_text_panel(self, p: QPainter, rx: int, h: int) -> None:
        # System label
        _font(p, 7, mono=True, spacing=3)
        p.setPen(QColor(_T3))
        p.drawText(rx, 68, "JARVIS OPERATIONS SYSTEM  //  v2.0  //  SECURE BOOT")

        # Separator
        s1 = QColor(_ARC); s1.setAlpha(52)
        p.setPen(QPen(s1, 1))
        p.drawLine(rx, 80, rx + 490, 80)

        # Main title (J.A.R.V.I.S.)
        tf = QFont()
        tf.setFamilies(["Rajdhani", "Segoe UI", "Arial"])
        tf.setPixelSize(62)
        tf.setWeight(QFont.Bold)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 10)
        p.setFont(tf)
        p.setPen(QColor(_T1))
        p.drawText(rx, 158, "J.A.R.V.I.S.")

        # Subtitle
        _font(p, 9, mono=True, spacing=4)
        p.setPen(QColor(_ARC))
        p.drawText(rx, 183, "CYBERSECURITY OPERATIONS CENTER")

        # Separator 2
        s2 = QColor(_ARC); s2.setAlpha(28)
        p.setPen(QPen(s2, 1))
        p.drawLine(rx, 197, rx + 490, 197)

        # Progress bar
        self._paint_progress(p, rx, 218, 460)

        # Boot messages
        self._paint_messages(p, rx, 248)

    def _paint_progress(self, p: QPainter, x: int, y: int, bar_w: int) -> None:
        bh = 3

        # Track
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(_PANEL))
        p.drawRect(x, y, bar_w, bh)
        tb = QColor(_B0); tb.setAlpha(100)
        p.setPen(QPen(tb, 1)); p.setBrush(Qt.NoBrush)
        p.drawRect(x, y, bar_w, bh)

        # Fill
        fw = int(bar_w * self._progress)
        if fw > 0:
            fg = QLinearGradient(x, 0, x + bar_w, 0)
            fg.setColorAt(0, QColor(_ARC))
            fg.setColorAt(1, QColor(100, 245, 220))
            p.setPen(Qt.NoPen); p.setBrush(fg)
            p.drawRect(x, y, fw, bh)

            # Glow tip
            tg = QRadialGradient(x + fw, y + bh // 2, 12)
            tg.setColorAt(0, QColor(24, 224, 193, 210))
            tg.setColorAt(1, QColor(24, 224, 193, 0))
            p.setBrush(tg)
            p.drawEllipse(QPoint(x + fw, y + bh // 2), 12, 12)

        # Percentage
        _font(p, 8, mono=True, spacing=1)
        p.setPen(QColor(_T2))
        p.drawText(x + bar_w + 14, y + 10, f"{int(self._progress * 100):3d}%")

    def _paint_messages(self, p: QPainter, rx: int, y: int) -> None:
        current = _MSGS[self._msg_idx]
        cursor = "_" if (self._frame // 18) % 2 == 0 else " "

        _font(p, 9, mono=True, spacing=2)
        p.setPen(QColor(_ARC))
        p.drawText(rx, y, f"> {current}  {cursor}")

        _font(p, 8, mono=True, spacing=1)
        alphas = [85, 60, 42, 22]
        prev = list(range(max(0, self._msg_idx - len(alphas)), self._msg_idx))
        for i, mi in enumerate(reversed(prev)):
            c = QColor(_T3); c.setAlpha(alphas[i])
            p.setPen(c)
            p.drawText(rx, y + 20 + i * 16, f"  {_MSGS[mi]}")

    # ── Bottom bar ─────────────────────────────────────────────────────────

    def _paint_bottom_bar(self, p: QPainter, w: int, h: int) -> None:
        sep = QColor(_ARC); sep.setAlpha(38)
        p.setPen(QPen(sep, 1))
        p.drawLine(14, h - 42, w - 14, h - 42)

        _font(p, 7, mono=True, spacing=2)
        items = [
            ("SECURE BOOT", _ARC, 190),
            ("LOCALHOST", _T3, 140),
            ("NO EXTERNAL CALLS", _T3, 190),
            ("AES-256", _T3, 100),
        ]
        bx = 24
        for label, color, _ in items:
            c = QColor(color); c.setAlpha(150)
            p.setPen(c)
            p.drawText(bx, h - 20, label)
            bx += len(label) * 7 + 16
            sep2 = QColor(_T3); sep2.setAlpha(70)
            p.setPen(sep2)
            p.drawText(bx - 10, h - 20, "//")
            bx += 10

        p.setPen(QColor(_T3))
        p.drawText(w - 160, h - 20, "BUILD 2026.03.16")


# ── Module-level font helper ────────────────────────────────────────────────

def _font(p: QPainter, size: int, mono: bool = False, spacing: float = 0) -> None:
    f = QFont()
    if mono:
        f.setFamilies(["JetBrains Mono", "Share Tech Mono", "Consolas", "Courier New"])
    else:
        f.setFamilies(["Rajdhani", "Segoe UI", "Arial"])
    f.setPixelSize(size)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    p.setFont(f)
