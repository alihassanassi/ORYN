"""
gui/windows/presentation_window.py – JARVIS Presentation Mode.

Deploys an immersive Iron Circuit styled presentation on demand.
Opens on the secondary monitor (or primary if only one).
Fully interactive: keyboard navigation, click to advance.

Usage via tool: "present the history of the Roman Empire"
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStackedWidget, QPushButton, QApplication
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeyEvent, QScreen


def get_secondary_screen() -> QScreen:
    """Returns the secondary monitor, or primary if only one."""
    screens = QApplication.screens()
    if len(screens) > 1:
        primary = QApplication.primaryScreen()
        for s in screens:
            if s != primary:
                return s
    return QApplication.primaryScreen()


class PresentationSlide(QWidget):
    """A single slide in the presentation."""

    def __init__(self, title: str, content: str, parent=None):
        super().__init__(parent)
        try:
            from gui.theme import theme
            bg    = theme.bg(1)
            acc   = theme.accent()
            t1    = theme.text(1)
            bord  = theme.border()
        except Exception:
            bg   = "#0a1018"
            acc  = "#18e0c1"
            t1   = "#ffffff"
            bord = "#1a2830"

        self.setStyleSheet(f"background:{bg};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 60, 80, 60)
        layout.setSpacing(24)

        title_lbl = QLabel(title.upper())
        title_lbl.setStyleSheet(
            f"font-family:'Courier New';font-size:28px;font-weight:bold;"
            f"color:{acc};letter-spacing:4px;background:transparent;"
        )
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        div = QWidget()
        div.setFixedHeight(2)
        div.setStyleSheet(f"background:{bord};")
        layout.addWidget(div)

        content_lbl = QLabel(content)
        content_lbl.setStyleSheet(
            f"font-family:'Courier New';font-size:15px;line-height:1.8;"
            f"color:{t1};background:transparent;"
        )
        content_lbl.setWordWrap(True)
        content_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(content_lbl, 1)


class PresentationWindow(QMainWindow):
    """Full-screen presentation window for the second monitor."""

    def __init__(self, title: str, slides: list):
        super().__init__()
        self.setWindowTitle(f"JARVIS – {title.upper()}")
        self._current = 0
        self._slides_data = slides
        self._build_ui()
        self._go_to_slide(0)

        screen = get_secondary_screen()
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()

    def _build_ui(self):
        try:
            from gui.theme import theme
            bg2   = theme.bg(2)
            acc   = theme.accent()
            acc_bg = theme.accent_bg()
            bord  = theme.border()
            t2    = theme.text(2)
        except Exception:
            bg2   = "#0d1820"
            acc   = "#18e0c1"
            acc_bg = "rgba(24,224,193,0.08)"
            bord  = "#1a2830"
            t2    = "rgba(255,255,255,0.5)"

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet(
            f"background:{bg2};border-bottom:1px solid {bord};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        hud_lbl = QLabel("J.A.R.V.I.S. — PRESENTATION")
        hud_lbl.setStyleSheet(
            f"font-family:'Courier New';font-size:11px;letter-spacing:3px;"
            f"color:{acc};background:transparent;")
        self._slide_counter = QLabel("1 / 1")
        self._slide_counter.setStyleSheet(
            f"font-family:'Courier New';font-size:10px;"
            f"color:{t2};background:transparent;")
        hl.addWidget(hud_lbl)
        hl.addStretch()
        hl.addWidget(self._slide_counter)
        layout.addWidget(header)

        self._stack = QStackedWidget()
        for sd in self._slides_data:
            slide = PresentationSlide(
                sd.get('title', ''),
                sd.get('content', ''),
            )
            self._stack.addWidget(slide)
        layout.addWidget(self._stack, 1)

        nav = QWidget()
        nav.setFixedHeight(52)
        nav.setStyleSheet(
            f"background:{bg2};border-top:1px solid {bord};")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(20, 0, 20, 0)
        nl.setSpacing(10)

        btn_style = (
            f"font-family:'Courier New';font-size:10px;letter-spacing:2px;"
            f"color:{acc};background:{acc_bg};"
            f"border:1px solid {bord};padding:0 16px;min-height:32px;")
        close_style = (
            f"font-family:'Courier New';font-size:10px;letter-spacing:2px;"
            f"color:rgba(255,80,80,0.8);background:rgba(255,50,50,0.05);"
            f"border:1px solid rgba(255,50,50,0.2);padding:0 16px;min-height:32px;")

        prev_btn  = QPushButton("◀  PREV")
        next_btn  = QPushButton("NEXT  ▶")
        close_btn = QPushButton("✕  CLOSE")
        prev_btn.setStyleSheet(btn_style)
        next_btn.setStyleSheet(btn_style)
        close_btn.setStyleSheet(close_style)

        prev_btn.clicked.connect(self._prev_slide)
        next_btn.clicked.connect(self._next_slide)
        close_btn.clicked.connect(self.close)

        nl.addStretch()
        nl.addWidget(prev_btn)
        nl.addWidget(next_btn)
        nl.addWidget(close_btn)
        layout.addWidget(nav)

    def _go_to_slide(self, idx: int):
        idx = max(0, min(idx, max(0, len(self._slides_data) - 1)))
        self._current = idx
        self._stack.setCurrentIndex(idx)
        self._slide_counter.setText(f"{idx + 1} / {len(self._slides_data)}")

    def _prev_slide(self):
        self._go_to_slide(self._current - 1)

    def _next_slide(self):
        self._go_to_slide(self._current + 1)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space):
            self._next_slide()
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._prev_slide()
        elif event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)


# Public API
def launch_presentation(title: str, slides: list) -> PresentationWindow:
    """Launch the presentation window on secondary monitor."""
    win = PresentationWindow(title, slides)
    return win
