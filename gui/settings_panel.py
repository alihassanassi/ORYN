"""
gui/settings_panel.py — JARVIS operator settings panel.

Layer 1 (Interface). No Layer 2–5 business logic.

Architecture:
    Frameless QDialog (Qt.Tool | Qt.FramelessWindowHint).
    Positioned flush to the right edge of main_window by
    JARVIS._on_settings_toggled() on each open.
    Width: 420px fixed. Height: set by caller to match main window.

Layout:
    Title bar (44px)
    ├── Category sidebar (110px) — AUDIO / DISPLAY / BEHAVIOR / SYSTEM
    └── Content QStackedWidget (310px) — one page per category

Signals emitted to main_window:
    hud_brightness_changed(float) — main_window applies QGraphicsOpacityEffect
                                     to self._center (CenterPanel)

Live vs restart classification:
    LIVE:    audio.tts_enabled, audio.voice_name, audio.auto_speak,
             audio.output_device_index, display.hud_brightness, display.fullscreen
    RESTART: audio.voice_rate, display.reduced_motion,
             display.dim_idle_effects, behavior.startup_voice,
             behavior.minimal_mode
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import config as _cfg
from config import P
import storage.settings_store as _ss
from gui.theme import theme as _theme

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QSlider,
    QStackedWidget, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from voice.tts import TTS
    from voice.stt import STT


# ── Panel CSS ─────────────────────────────────────────────────────────────────

_PANEL_CSS = f"""
QDialog, QWidget {{
    background: {P['void']};
    color: {P['t0']};
    border: none;
    outline: none;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 4px; border-radius: 2px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {P['b2']}; border-radius: 2px; min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}

QComboBox {{
    background: {_theme.bg(3)};
    color: {_theme.text(1)};
    border: 1px solid {_theme.border()};
    border-radius: 3px;
    padding: 6px 10px;
    font-family: 'Courier New';
    font-size: 10px;
    min-height: 32px;
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
    background: {_theme.bg(3)};
}}
QComboBox::down-arrow {{
    color: {_theme.accent()};
    font-size: 10px;
}}
QComboBox QAbstractItemView {{
    background: {_theme.bg(2)};
    color: {_theme.text(1)};
    border: 1px solid {_theme.border()};
    selection-background-color: {_theme.accent_bg()};
    selection-color: {_theme.accent()};
    font-family: 'Courier New';
    font-size: 10px;
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 4px 10px;
}}
QComboBox QAbstractItemView::item:selected {{
    background: {_theme.accent_bg()};
    color: {_theme.accent()};
}}

QCheckBox {{
    color: {P['t1']};
    spacing: 10px;
    font-family: '{_cfg.MONO}';
    font-size: 10px;
    letter-spacing: 1px;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {P['b2']};
    border-radius: 3px;
    background: {P['base']};
}}
QCheckBox::indicator:checked {{
    background: {P['arc_d']};
    border-color: {P['arc']};
    image: none;
}}
QCheckBox::indicator:hover {{ border-color: {P['arc_d']}; }}

QSlider::groove:horizontal {{
    background: {P['b1']}; height: 4px; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {P['arc_d']}, stop:1 {P['arc']});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {P['arc']};
    border: 2px solid {P['void']};
    width: 14px; height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: {P['t0']};
    border-color: {P['arc']};
}}
"""

# ── Style constants ────────────────────────────────────────────────────────────

_MONO = _cfg.MONO

def _css_sec_hdr():
    return (f"color:{P['arc']};font-family:'{_MONO}';font-size:9px;"
            f"letter-spacing:2px;font-weight:800;background:transparent;")

def _css_lbl():
    return (f"color:{P['t3']};font-family:'{_MONO}';font-size:10px;"
            f"letter-spacing:1px;background:transparent;")

def _css_val():
    return (f"color:{P['t1']};font-family:'{_MONO}';font-size:10px;"
            f"background:transparent;")

def _css_restart():
    return (f"color:{P['amber']}90;font-family:'{_MONO}';font-size:8px;"
            f"letter-spacing:1px;background:transparent;")

def _css_card():
    return (f"background:{P['card']};border:1px solid {P['b1']};"
            f"border-radius:6px;")


# ── Builder helpers ────────────────────────────────────────────────────────────

def _section(text: str) -> QWidget:
    """Section header: accent dot + uppercase label + hairline rule."""
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 12, 0, 12)
    h.setSpacing(8)

    dot = QLabel("◈")
    dot.setStyleSheet(f"color:{P['arc']};font-size:8px;background:transparent;")
    h.addWidget(dot)

    lbl = QLabel(text)
    lbl.setStyleSheet(_css_sec_hdr())
    h.addWidget(lbl)

    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"color:{P['b2']};background:{P['b2']};border:none;max-height:1px;")
    line.setFixedHeight(1)
    h.addWidget(line, 1)

    return w


def _lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(_css_lbl())
    return l


def _val(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(_css_val())
    l.setWordWrap(True)
    return l


def _restart_note(text: str = "↺ Requires restart") -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(_css_restart())
    return l


def _status_badge(text: str, color: str) -> QLabel:
    """Colored status pill label."""
    l = QLabel(text)
    l.setStyleSheet(
        f"color:{color};background:{color}18;border:1px solid {color}40;"
        f"border-radius:3px;padding:1px 6px;"
        f"font-family:'{_MONO}';font-size:9px;font-weight:700;"
    )
    l.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return l


def _card(*widgets) -> QWidget:
    """Wrap widgets in a subtle card container."""
    card = QWidget()
    card.setStyleSheet(_css_card())
    v = QVBoxLayout(card)
    v.setContentsMargins(12, 10, 12, 10)
    v.setSpacing(10)
    for w in widgets:
        if w is None:
            continue
        v.addWidget(w)
    return card


def _ctrl_block(label_text: str, control: QWidget, note: str = None) -> QWidget:
    """Vertical control block: label → control → optional note."""
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    v.addWidget(_lbl(label_text))
    v.addWidget(control)
    if note:
        v.addWidget(_restart_note(note))
    return w


def _inline_row(label_text: str, right_widget: QWidget) -> QWidget:
    """Horizontal inline row: label left, widget right."""
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    h.addWidget(_lbl(label_text))
    h.addStretch()
    h.addWidget(right_widget)
    return w


def _slider_row(slider: QSlider, val_lbl: QLabel) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    h.addWidget(slider, 1)
    h.addWidget(val_lbl)
    return w


def _action_btn(text: str, color: str = None) -> QPushButton:
    """Styled action button."""
    c = color or P['arc']
    btn = QPushButton(text)
    btn.setFixedHeight(32)
    btn.setCursor(QCursor(Qt.PointingHandCursor))
    btn.setStyleSheet(
        f"QPushButton{{color:{c};background:transparent;"
        f"border:1px solid {c}50;border-radius:4px;"
        f"font-family:'{_MONO}';font-size:9px;letter-spacing:2px;font-weight:700;}}"
        f"QPushButton:hover{{background:{c}14;border-color:{c};color:{P['t0']};}}"
        f"QPushButton:pressed{{background:{c}22;}}"
    )
    return btn


def _val_label(initial: str = "—", width: int = 42) -> QLabel:
    l = QLabel(initial)
    l.setStyleSheet(
        f"color:{P['arc']};font-family:'{_MONO}';font-size:10px;"
        f"font-weight:700;background:transparent;"
    )
    l.setFixedWidth(width)
    l.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return l


# ── Main panel class ───────────────────────────────────────────────────────────

class SettingsPanel(QDialog):
    """
    JARVIS operator settings panel — frameless QDialog, right-edge anchored.

    Caller (JARVIS._on_settings_toggled) sets geometry each time it is shown.
    """

    hud_brightness_changed = Signal(float)

    def __init__(self, tts: "TTS", stt: "STT", parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self._tts = tts
        self._stt = stt
        self.setFixedWidth(420)
        self.resize(420, 900)
        self.setStyleSheet(_PANEL_CSS)
        self._build_ui()
        self._load_from_store()

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_titlebar())

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        bh = QHBoxLayout(body)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(0)

        self._cat_btns: list[QPushButton] = []
        bh.addWidget(self._build_sidebar())

        vdiv = QFrame()
        vdiv.setFixedWidth(1)
        vdiv.setStyleSheet(f"background:{P['b1']};")
        bh.addWidget(vdiv)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:transparent;")
        self._stack.addWidget(self._build_audio_page())    # 0
        self._stack.addWidget(self._build_display_page())  # 1
        self._stack.addWidget(self._build_behavior_page()) # 2
        self._stack.addWidget(self._build_system_page())   # 3
        bh.addWidget(self._stack, 1)

        outer.addWidget(body, 1)
        self._switch_cat(0)

    def _build_titlebar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet(
            f"background:{P['surface']};border-bottom:1px solid {P['b1']};"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 0, 12, 0)
        row.setSpacing(8)

        icon = QLabel("⚙")
        icon.setStyleSheet(
            f"color:{P['arc']};font-size:14px;background:transparent;"
        )
        row.addWidget(icon)

        title = QLabel("SETTINGS")
        title.setStyleSheet(
            f"color:{P['t0']};font-family:'{_MONO}';font-size:11px;"
            f"letter-spacing:4px;font-weight:700;background:transparent;"
        )
        row.addWidget(title)
        row.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{P['t3']};"
            f"border:none;font-size:12px;border-radius:4px;}}"
            f"QPushButton:hover{{color:{P['red']};background:{P['red']}15;}}"
        )
        close_btn.clicked.connect(self.hide)
        row.addWidget(close_btn)
        return bar

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setFixedWidth(110)
        side.setStyleSheet(f"background:{P['void']};")
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 16, 0, 16)
        v.setSpacing(2)

        _NAV = [
            ("◈", "AUDIO"),
            ("◉", "DISPLAY"),
            ("⟁", "BEHAVIOR"),
            ("⊞", "SYSTEM"),
        ]
        for idx, (icon, label) in enumerate(_NAV):
            btn = QPushButton(f"  {icon}  {label}")
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.clicked.connect(lambda _=False, i=idx: self._switch_cat(i))
            btn.setFixedHeight(40)
            v.addWidget(btn)
            self._cat_btns.append(btn)

        v.addStretch()
        return side

    def _cat_css(self, active: bool) -> str:
        if active:
            return (
                f"QPushButton{{color:{P['arc']};background:{P['arc']}12;"
                f"border:none;border-left:2px solid {P['arc']};"
                f"border-right:none;border-top:none;border-bottom:none;"
                f"font-family:'{_MONO}';font-size:9px;letter-spacing:2px;"
                f"text-align:left;padding:0px 12px;font-weight:800;}}"
            )
        return (
            f"QPushButton{{color:{P['t3']};background:transparent;"
            f"border:none;border-left:2px solid transparent;"
            f"border-right:none;border-top:none;border-bottom:none;"
            f"font-family:'{_MONO}';font-size:9px;letter-spacing:2px;"
            f"text-align:left;padding:0px 12px;}}"
            f"QPushButton:hover{{color:{P['t1']};background:{P['b0']}30;}}"
        )

    def _switch_cat(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._cat_btns):
            btn.setStyleSheet(self._cat_css(i == idx))

    # ── Page helpers ──────────────────────────────────────────────────────────

    def _make_page(self) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        v = QVBoxLayout(inner)
        v.setContentsMargins(14, 14, 14, 20)
        v.setSpacing(12)
        scroll.setWidget(inner)
        return scroll, v

    def _make_slider(self, lo: int, hi: int, step: int = 5) -> QSlider:
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setSingleStep(step)
        return sl

    # ── AUDIO page ────────────────────────────────────────────────────────────

    def _build_audio_page(self) -> QScrollArea:
        page, v = self._make_page()

        # ── OUTPUT ────────────────────────────────────────────────────────────
        v.addWidget(_section("OUTPUT"))

        # TTS toggle + engine status in one card
        self._tts_toggle = QCheckBox("VOICE OUTPUT ENABLED")
        self._tts_toggle.setToolTip("Enable or disable TTS speech output (LIVE)")
        self._tts_toggle.stateChanged.connect(self._on_tts_toggle)

        engine_row = QWidget()
        engine_row.setStyleSheet("background:transparent;")
        er = QHBoxLayout(engine_row)
        er.setContentsMargins(0, 0, 0, 0)
        er.setSpacing(8)
        er.addWidget(_lbl("TTS ENGINE"))
        er.addStretch()
        self._tts_mode_lbl = _status_badge("—", P["t3"])
        er.addWidget(self._tts_mode_lbl)

        v.addWidget(_card(self._tts_toggle, engine_row))

        # Voice Profile card
        self._profile_combo = QComboBox()
        self._profile_combo.setToolTip("Active voice profile (LIVE)")
        self._profile_combo.setMaxVisibleItems(12)
        self._profile_combo.view().setMinimumWidth(300)
        try:
            for name in self._tts.list_profiles():
                self._profile_combo.addItem(name)
            self._profile_combo.addItem("auto")
        except Exception:
            self._profile_combo.addItem("auto")
        self._profile_combo.currentTextChanged.connect(self._on_profile_changed)

        v.addWidget(_card(_ctrl_block("VOICE PROFILE", self._profile_combo)))

        # Output Device card
        self._output_device_combo = QComboBox()
        self._output_device_combo.setToolTip("Audio output device (LIVE)")
        self._output_device_combo.setMaxVisibleItems(12)
        self._output_device_combo.view().setMinimumWidth(300)
        self._output_device_combo.addItem("System default", None)
        try:
            for idx, name in self._tts.list_output_devices():
                self._output_device_combo.addItem(name[:48], idx)
        except Exception:
            pass
        self._output_device_combo.currentIndexChanged.connect(self._on_output_device_changed)

        v.addWidget(_card(_ctrl_block("OUTPUT DEVICE", self._output_device_combo)))

        # Speech Rate card
        self._rate_slider  = self._make_slider(50, 200)
        self._rate_val_lbl = _val_label("1.0×", 44)
        self._rate_slider.setToolTip("Speech rate 0.5×–2.0× (LIVE)")
        self._rate_slider.valueChanged.connect(self._on_rate_changed)

        rate_row = QWidget()
        rate_row.setStyleSheet("background:transparent;")
        rr = QVBoxLayout(rate_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(6)
        rr.addWidget(_lbl("SPEECH RATE"))
        rr.addWidget(_slider_row(self._rate_slider, self._rate_val_lbl))
        rr.addWidget(_restart_note("↺ Piper restarts process · Kokoro/SAPI apply live"))

        test_btn = _action_btn("▶  TEST VOICE", P["arc"])
        test_btn.clicked.connect(self._on_test_voice)

        v.addWidget(_card(rate_row, test_btn))

        # ── CHATTERBOX ────────────────────────────────────────────────────────
        v.addWidget(_section("CHATTERBOX"))

        self._exagg_slider  = self._make_slider(0, 100, step=5)
        self._exagg_val_lbl = _val_label("0.50", 44)
        self._exagg_slider.setToolTip(
            "Emotion exaggeration 0.0–1.0 (LIVE; requires Chatterbox backend)"
        )
        self._exagg_slider.valueChanged.connect(self._on_exagg_changed)

        exagg_block = QWidget()
        exagg_block.setStyleSheet("background:transparent;")
        eb = QVBoxLayout(exagg_block)
        eb.setContentsMargins(0, 0, 0, 0)
        eb.setSpacing(6)
        eb.addWidget(_lbl("EXAGGERATION"))
        eb.addWidget(_slider_row(self._exagg_slider, self._exagg_val_lbl))

        cb_row = QWidget()
        cb_row.setStyleSheet("background:transparent;")
        cr = QHBoxLayout(cb_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)
        cr.addWidget(_lbl("CB STATUS"))
        cr.addStretch()
        self._cb_status_lbl = _status_badge("—", P["t3"])
        cr.addWidget(self._cb_status_lbl)

        v.addWidget(_card(exagg_block, cb_row))

        # ── AUTO-SPEAK ────────────────────────────────────────────────────────
        self._auto_speak_toggle = QCheckBox("AUTO-SPEAK ALL REPLIES")
        self._auto_speak_toggle.setToolTip(
            "Speak all LLM replies automatically without voice toggle (LIVE)"
        )
        self._auto_speak_toggle.stateChanged.connect(self._on_auto_speak_toggle)
        v.addWidget(_card(self._auto_speak_toggle))

        # ── INPUT ─────────────────────────────────────────────────────────────
        v.addWidget(_section("INPUT"))

        self._mic_combo = QComboBox()
        self._mic_combo.setToolTip("Select microphone input device (LIVE)")
        self._mic_combo.setMaxVisibleItems(12)
        self._mic_combo.view().setMinimumWidth(300)
        self._mic_combo.addItem("Auto (keyword match)", None)
        try:
            for idx, name in self._stt.list_input_devices():
                self._mic_combo.addItem(name[:48], idx)
        except Exception:
            pass
        self._mic_combo.currentIndexChanged.connect(self._on_input_device_changed)

        stt_row = QWidget()
        stt_row.setStyleSheet("background:transparent;")
        sr = QHBoxLayout(stt_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(8)
        sr.addWidget(_lbl("STT STATUS"))
        sr.addStretch()
        self._stt_lbl = _status_badge("—", P["t3"])
        sr.addWidget(self._stt_lbl)

        v.addWidget(_card(
            _ctrl_block("MICROPHONE", self._mic_combo),
            stt_row,
        ))

        v.addStretch()
        return page

    # ── DISPLAY page ──────────────────────────────────────────────────────────

    def _build_display_page(self) -> QScrollArea:
        page, v = self._make_page()

        # ── APPEARANCE ────────────────────────────────────────────────────────
        v.addWidget(_section("APPEARANCE"))
        try:
            from gui.widgets.theme_bar import ThemeBar
            self._theme_bar = ThemeBar()
            v.addWidget(_card(self._theme_bar))
        except Exception:
            v.addWidget(_card(_val("Theme system unavailable")))

        # ── VISUAL ────────────────────────────────────────────────────────────
        v.addWidget(_section("VISUAL"))

        self._brightness_slider = self._make_slider(50, 150)
        self._bright_val_lbl    = _val_label("1.0", 36)
        self._brightness_slider.setToolTip(
            "Center panel brightness 0.5–1.5 (LIVE; values >1.0 clamped to 1.0)"
        )
        self._brightness_slider.valueChanged.connect(self._on_brightness_changed)

        bright_block = QWidget()
        bright_block.setStyleSheet("background:transparent;")
        bb = QVBoxLayout(bright_block)
        bb.setContentsMargins(0, 0, 0, 0)
        bb.setSpacing(6)
        bb.addWidget(_lbl("HUD BRIGHTNESS"))
        bb.addWidget(_slider_row(self._brightness_slider, self._bright_val_lbl))

        self._reduced_motion = QCheckBox("REDUCED MOTION")
        self._reduced_motion.setToolTip(
            "Suppress widget animations (RESTART required)"
        )
        self._reduced_motion.stateChanged.connect(
            lambda s: _ss.set("display.reduced_motion", bool(s))
        )

        self._dim_idle = QCheckBox("DIM IDLE EFFECTS")
        self._dim_idle.setToolTip(
            "Dim ambient animations when idle (RESTART required)"
        )
        self._dim_idle.stateChanged.connect(
            lambda s: _ss.set("display.dim_idle_effects", bool(s))
        )

        v.addWidget(_card(
            bright_block,
            self._reduced_motion,
            self._dim_idle,
            _restart_note("↺ Reduced motion + dim idle require restart"),
        ))

        # ── WINDOW ────────────────────────────────────────────────────────────
        v.addWidget(_section("WINDOW"))

        self._fullscreen_toggle = QCheckBox("FULLSCREEN MODE")
        self._fullscreen_toggle.setToolTip("Toggle fullscreen mode (LIVE)")
        self._fullscreen_toggle.stateChanged.connect(self._on_fullscreen_toggle)
        v.addWidget(_card(self._fullscreen_toggle))

        v.addStretch()
        return page

    # ── BEHAVIOR page ─────────────────────────────────────────────────────────

    def _build_behavior_page(self) -> QScrollArea:
        page, v = self._make_page()

        v.addWidget(_section("STARTUP"))

        self._startup_voice = QCheckBox("STARTUP VOICE GREETING")
        self._startup_voice.setToolTip("Speak greeting on launch (RESTART required)")
        self._startup_voice.stateChanged.connect(
            lambda s: _ss.set("behavior.startup_voice", bool(s))
        )
        v.addWidget(_card(
            self._startup_voice,
            _restart_note("↺ Startup greeting requires restart"),
        ))

        v.addWidget(_section("OPERATION"))

        ref = _lbl("Auto-Speak Replies → AUDIO tab")
        self._minimal_mode = QCheckBox("MINIMAL MODE")
        self._minimal_mode.setToolTip(
            "Suppress non-essential UI elements (RESTART required)"
        )
        self._minimal_mode.stateChanged.connect(
            lambda s: _ss.set("behavior.minimal_mode", bool(s))
        )
        v.addWidget(_card(
            ref,
            self._minimal_mode,
            _restart_note("↺ Minimal mode requires restart"),
        ))

        v.addStretch()
        return page

    # ── SYSTEM page ───────────────────────────────────────────────────────────

    def _build_system_page(self) -> QScrollArea:
        page, v = self._make_page()
        import config as _c

        v.addWidget(_section("RUNTIME"))

        runtime_card_items = []
        for label, value in [
            ("LLM MODEL",  _c.OLLAMA_MODEL),
            ("OLLAMA URL", _c.OLLAMA_BASE_URL),
        ]:
            row = _inline_row(label, _val(value))
            runtime_card_items.append(row)
        v.addWidget(_card(*runtime_card_items))

        v.addWidget(_section("STORAGE"))
        db_val = _val(str(_c.DB_PATH))
        db_val.setStyleSheet(
            f"color:{P['t2']};font-family:'{_MONO}';font-size:9px;background:transparent;"
        )
        v.addWidget(_card(_ctrl_block("DATABASE PATH", db_val)))

        v.addWidget(_section("VOICE PATHS"))

        piper_exists  = _c.PIPER_EXE.exists()
        voices_exists = _c.PIPER_VOICES.exists()

        def _path_lbl(path, ok):
            l = _val(str(path))
            l.setStyleSheet(
                f"color:{P['green'] if ok else P['red']};"
                f"font-family:'{_MONO}';font-size:9px;background:transparent;"
            )
            return l

        v.addWidget(_card(
            _ctrl_block("PIPER EXECUTABLE", _path_lbl(_c.PIPER_EXE, piper_exists)),
            _ctrl_block("VOICES PATH", _path_lbl(_c.PIPER_VOICES, voices_exists)),
        ))

        v.addWidget(_section("MAINTENANCE"))

        reset_btn = _action_btn("⚠  RESET TO DEFAULTS", P["amber"])
        reset_btn.clicked.connect(self._on_reset_defaults)
        v.addWidget(_card(reset_btn))

        v.addStretch()
        return page

    # ── Control handlers ──────────────────────────────────────────────────────

    def _on_tts_toggle(self, state: int) -> None:
        _ss.set("audio.tts_enabled", bool(state))

    def _on_profile_changed(self, profile_name: str) -> None:
        if not profile_name:
            return
        _ss.set("audio.voice_name", profile_name)
        try:
            self._tts.set_profile(profile_name)
        except Exception as exc:
            print(f"[Settings] Profile change failed: {exc}", flush=True)

    def _on_output_device_changed(self, combo_idx: int) -> None:
        device_index = self._output_device_combo.itemData(combo_idx)
        try:
            msg = self._tts.set_output_device(device_index)
            print(f"[Settings] {msg}", flush=True)
        except Exception as exc:
            print(f"[Settings] Output device change failed: {exc}", flush=True)

    def _on_rate_changed(self, int_val: int) -> None:
        rate = int_val / 100.0
        _ss.set("audio.voice_rate", rate)
        self._rate_val_lbl.setText(f"{rate:.1f}×")
        try:
            self._tts.set_speed(rate)
        except Exception as exc:
            print(f"[Settings] Rate change failed: {exc}", flush=True)

    def _on_exagg_changed(self, int_val: int) -> None:
        val = int_val / 100.0
        self._exagg_val_lbl.setText(f"{val:.2f}")
        _ss.set("audio.chatterbox_exaggeration", val)
        try:
            self._tts.set_chatterbox_exaggeration(val)
        except Exception as exc:
            print(f"[Settings] Exaggeration change failed: {exc}", flush=True)

    def _on_input_device_changed(self, combo_idx: int) -> None:
        try:
            self._stt.set_input_device(self._mic_combo.itemData(combo_idx))
        except Exception as exc:
            print(f"[Settings] Mic change failed: {exc}", flush=True)

    def _on_auto_speak_toggle(self, state: int) -> None:
        _ss.set("audio.auto_speak", bool(state))

    def _on_test_voice(self) -> None:
        try:
            from voice.profiles import get_profile
            active = self._tts.get_active_profile()
            p = get_profile(active) if active != "auto" else None
            self._tts.speak(p.test_line if p else "Voice configuration verified.")
        except Exception as exc:
            print(f"[Settings] Test voice failed: {exc}", flush=True)

    def _on_brightness_changed(self, int_val: int) -> None:
        value = int_val / 100.0
        _ss.set("display.hud_brightness", value)
        self.hud_brightness_changed.emit(value)
        self._bright_val_lbl.setText(f"{value:.1f}")

    def _on_fullscreen_toggle(self, state: int) -> None:
        enabled = bool(state)
        _ss.set("display.fullscreen", enabled)
        parent = self.parent()
        if parent is not None:
            if enabled:
                parent.showFullScreen()
            else:
                parent.showNormal()

    def _on_reset_defaults(self) -> None:
        _ss.reset()
        self._load_from_store()
        self.hud_brightness_changed.emit(_ss.get("display.hud_brightness"))

    # ── Populate controls from store ──────────────────────────────────────────

    def _load_from_store(self) -> None:
        self._block(True)
        try:
            self._tts_toggle.setChecked(_ss.get("audio.tts_enabled"))

            profile = _ss.get("audio.voice_name") or "auto"
            idx = self._profile_combo.findText(profile)
            if idx >= 0:
                self._profile_combo.setCurrentIndex(idx)

            rate = _ss.get("audio.voice_rate")
            self._rate_slider.setValue(int(rate * 100))
            self._rate_val_lbl.setText(f"{rate:.1f}×")

            self._auto_speak_toggle.setChecked(_ss.get("audio.auto_speak"))

            stored_dev_idx = _ss.get("audio.output_device_index")
            matched = False
            for i in range(self._output_device_combo.count()):
                if self._output_device_combo.itemData(i) == stored_dev_idx:
                    self._output_device_combo.setCurrentIndex(i)
                    matched = True
                    break
            if not matched:
                self._output_device_combo.setCurrentIndex(0)

            stored_mic_idx = _ss.get("audio.input_device_index")
            matched_mic = False
            for i in range(self._mic_combo.count()):
                if self._mic_combo.itemData(i) == stored_mic_idx:
                    self._mic_combo.setCurrentIndex(i)
                    matched_mic = True
                    break
            if not matched_mic:
                self._mic_combo.setCurrentIndex(0)

            exagg = _ss.get("audio.chatterbox_exaggeration")
            if exagg is not None:
                self._exagg_slider.setValue(int(float(exagg) * 100))
                self._exagg_val_lbl.setText(f"{float(exagg):.2f}")

            brightness = _ss.get("display.hud_brightness")
            self._brightness_slider.setValue(int(brightness * 100))
            self._bright_val_lbl.setText(f"{brightness:.1f}")

            self._reduced_motion.setChecked(_ss.get("display.reduced_motion"))
            self._dim_idle.setChecked(_ss.get("display.dim_idle_effects"))
            self._fullscreen_toggle.setChecked(_ss.get("display.fullscreen"))

            self._startup_voice.setChecked(_ss.get("behavior.startup_voice"))
            self._minimal_mode.setChecked(_ss.get("behavior.minimal_mode"))
        finally:
            self._block(False)

    def _block(self, block: bool) -> None:
        for widget in (
            self._tts_toggle, self._profile_combo, self._output_device_combo,
            self._rate_slider, self._auto_speak_toggle, self._brightness_slider,
            self._reduced_motion, self._dim_idle, self._fullscreen_toggle,
            self._startup_voice, self._minimal_mode,
            self._mic_combo, self._exagg_slider,
        ):
            widget.blockSignals(block)

    # ── Refresh dynamic labels on each open ───────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_live_status()

    def _refresh_live_status(self) -> None:
        # TTS engine mode
        mode = self._tts.get_mode()
        _MODE_DISPLAY = {
            "kokoro":     ("KOKORO NEURAL",     P["green"]),
            "piper":      ("PIPER NEURAL",      P["arc"]),
            "sapi":       ("SAPI FALLBACK",     P["amber"]),
            "chatterbox": ("CHATTERBOX NEURAL", P["green"]),
            "none":       ("UNAVAILABLE",       P["red"]),
        }
        text, col = _MODE_DISPLAY.get(mode, ("UNKNOWN", P["t3"]))
        self._tts_mode_lbl.setText(text)
        self._tts_mode_lbl.setStyleSheet(
            f"color:{col};background:{col}18;border:1px solid {col}40;"
            f"border-radius:3px;padding:1px 6px;"
            f"font-family:'{_MONO}';font-size:9px;font-weight:700;"
        )

        # Sync profile combo
        active_profile = self._tts.get_active_profile()
        self._block(True)
        try:
            idx = self._profile_combo.findText(active_profile)
            if idx >= 0:
                self._profile_combo.setCurrentIndex(idx)

            try:
                live_dev_idx, _live_name = self._tts.get_output_device()
                for i in range(self._output_device_combo.count()):
                    if self._output_device_combo.itemData(i) == live_dev_idx:
                        self._output_device_combo.setCurrentIndex(i)
                        break
            except Exception:
                pass
        finally:
            self._block(False)

        # STT status
        try:
            st = self._stt.status()
            stt_ready    = st.get("ready", False)
            live_mic_idx = st.get("mic_idx")
        except Exception:
            stt_ready    = False
            live_mic_idx = None

        stt_text = "READY" if stt_ready else "OFFLINE"
        stt_col  = P["green"] if stt_ready else P["red"]
        self._stt_lbl.setText(stt_text)
        self._stt_lbl.setStyleSheet(
            f"color:{stt_col};background:{stt_col}18;border:1px solid {stt_col}40;"
            f"border-radius:3px;padding:1px 6px;"
            f"font-family:'{_MONO}';font-size:9px;font-weight:700;"
        )

        # Sync mic combo
        self._block(True)
        try:
            if self._mic_combo.count() <= 1:
                try:
                    for idx, name in self._stt.list_input_devices():
                        self._mic_combo.addItem(name[:48], idx)
                except Exception:
                    pass
            for i in range(self._mic_combo.count()):
                if self._mic_combo.itemData(i) == live_mic_idx:
                    self._mic_combo.setCurrentIndex(i)
                    break
        finally:
            self._block(False)

        # Chatterbox status
        try:
            tts_status = self._tts.status()
            cb_info = tts_status.get("chatterbox", {})
            if isinstance(cb_info, dict):
                cb_ready = cb_info.get("ready", False)
                cb_text  = "READY" if cb_ready else "OFFLINE"
                cb_col   = P["green"] if cb_ready else P["t3"]
            else:
                cb_text, cb_col = "—", P["t3"]
        except Exception:
            cb_text, cb_col = "—", P["t3"]

        self._cb_status_lbl.setText(cb_text)
        self._cb_status_lbl.setStyleSheet(
            f"color:{cb_col};background:{cb_col}18;border:1px solid {cb_col}40;"
            f"border-radius:3px;padding:1px 6px;"
            f"font-family:'{_MONO}';font-size:9px;font-weight:700;"
        )

        # Chatterbox exaggeration sync
        try:
            exagg = self._tts.get_chatterbox_exaggeration()
            if exagg >= 0:
                self._block(True)
                try:
                    self._exagg_slider.setValue(int(exagg * 100))
                    self._exagg_val_lbl.setText(f"{exagg:.2f}")
                finally:
                    self._block(False)
        except Exception:
            pass
