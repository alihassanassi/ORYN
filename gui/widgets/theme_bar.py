"""
gui/widgets/theme_bar.py — Floating brightness slider + color theme picker.

Contains:
  - Brightness slider (QSlider) with live preview
  - 10 color swatches (one per theme)
  - Active theme label

All changes apply immediately and persist via theme.save().
Can be embedded in the settings panel or shown as a floating overlay.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSlider, QPushButton,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QBrush, QPen

from gui.theme import theme, THEMES, THEME_ORDER


class ColorSwatch(QPushButton):
    """One color swatch button representing a theme."""

    def __init__(self, theme_name: str, parent=None):
        super().__init__(parent)
        self._tname = theme_name
        self.setFixedSize(22, 22)
        self.setToolTip(theme_name)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._on_click)
        self._active = False

    def set_active(self, v: bool):
        self._active = v
        self.update()

    def _on_click(self):
        theme.set_theme(self._tname)
        theme.save()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        td = THEMES[self._tname]
        col = QColor(td.accent)
        # Outer ring if active
        if self._active:
            p.setPen(QPen(col, 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(1, 1, 19, 19)
        # Inner fill circle
        p.setPen(Qt.NoPen)
        col.setAlpha(220)
        p.setBrush(QBrush(col))
        inset = 4 if self._active else 2
        p.drawEllipse(inset, inset, 22 - inset * 2, 22 - inset * 2)


class ThemeBar(QWidget):
    """Compact theme switcher + brightness slider."""

    theme_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._swatches: dict[str, ColorSwatch] = {}
        self._build_ui()
        theme.add_change_listener(self._on_theme_changed)
        self._on_theme_changed()

    def _build_ui(self):
        T = theme
        self.setStyleSheet(
            f"background:{T.bg(2)};"
            f"border:1px solid {T.border()};"
            f"border-radius:4px;"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # ── Row 1: brightness ─────────────────────────────────────────────────
        br_row = QHBoxLayout()
        br_row.setSpacing(8)
        br_lbl = QLabel("BRIGHTNESS")
        br_lbl.setStyleSheet(
            f"font-family:'Courier New';font-size:7px;letter-spacing:2px;"
            f"color:{T.text(2)};background:transparent;")
        br_lbl.setFixedWidth(80)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(20, 100)
        self._slider.setValue(int(T.brightness() * 100))
        self._slider.setFixedHeight(18)
        self._slider.valueChanged.connect(self._on_brightness)

        self._br_val = QLabel(f"{int(T.brightness() * 100)}%")
        self._br_val.setFixedWidth(36)
        self._br_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._br_val.setStyleSheet(
            f"font-family:'Courier New';font-size:8px;"
            f"color:{T.accent()};background:transparent;")

        br_row.addWidget(br_lbl)
        br_row.addWidget(self._slider, 1)
        br_row.addWidget(self._br_val)
        root.addLayout(br_row)

        # ── Row 2: color swatches ─────────────────────────────────────────────
        sw_row = QHBoxLayout()
        sw_row.setSpacing(4)
        sw_lbl = QLabel("THEME")
        sw_lbl.setStyleSheet(
            f"font-family:'Courier New';font-size:7px;letter-spacing:2px;"
            f"color:{T.text(2)};background:transparent;")
        sw_lbl.setFixedWidth(80)
        sw_row.addWidget(sw_lbl)
        for name in THEME_ORDER:
            sw = ColorSwatch(name)
            self._swatches[name] = sw
            sw_row.addWidget(sw)
        sw_row.addStretch()
        root.addLayout(sw_row)

        # ── Row 3: active theme name ──────────────────────────────────────────
        self._name_lbl = QLabel(T.name())
        self._name_lbl.setAlignment(Qt.AlignRight)
        self._name_lbl.setStyleSheet(
            f"font-family:'Courier New';font-size:8px;letter-spacing:3px;"
            f"color:{T.accent()};background:transparent;")
        root.addWidget(self._name_lbl)

    def _on_brightness(self, value: int):
        theme.set_brightness(value / 100.0)
        theme.save()
        self._br_val.setText(f"{value}%")

    def _on_theme_changed(self):
        for name, sw in self._swatches.items():
            sw.set_active(name == theme.name())
        self._name_lbl.setText(theme.name())
        self._name_lbl.setStyleSheet(
            f"font-family:'Courier New';font-size:8px;letter-spacing:3px;"
            f"color:{theme.accent()};background:transparent;")
        self._br_val.setStyleSheet(
            f"font-family:'Courier New';font-size:8px;"
            f"color:{theme.accent()};background:transparent;")
        self.theme_changed.emit(theme.name())
