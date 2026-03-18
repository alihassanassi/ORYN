"""
gui/main_window.py — JARVIS QMainWindow.

All GUI construction and event handling. Never calls blocking operations directly —
those are delegated to AgentWorker (QRunnable) or background threads.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QThreadPool, Slot, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from config import P
import config as _cfg
import storage.settings_store as _settings_store
from storage.db import (
    db_init, get_active_project, set_active_project,
    list_projects, create_project, save_message,
)
from llm.client import LLM
from voice.tts import TTS
from voice.stt import STT
from agents.worker import AgentWorker
from agents.autonomous import AutonomousAgent
from agents.monitor import MonitorAgent
from evolution.engine import SelfEvolution
from tools.voice_tools import _TTS_REF, _PERSONA_CB
from gui.widgets import (
    ArcReactor, ThinkDots, WaveformVisualizer, Bubble, ProposalCard,
)
from gui.widgets.audio_meter import AudioMeter
from gui.panels.telemetry_panel import TelemetryPanel
try:
    from audio.sound_engine import play as _play_sound, start as _sound_start, duck as _duck_sound, unduck as _unduck_sound
except Exception:
    def _play_sound(_name: str) -> None: pass   # no-op if sound engine missing
    def _sound_start() -> None: pass
    def _duck_sound() -> None: pass
    def _unduck_sound() -> None: pass
try:
    from gui.mini_window import MiniHUD as _MiniHUD
except Exception:
    _MiniHUD = None
try:
    from gui.panels.scan_graph import ScanGraphPanel as _ScanGraphPanel
except Exception:
    _ScanGraphPanel = None
try:
    from gui.panels.agent_monitor import AgentMonitorPanel as _AgentMonitorPanel
except Exception:
    _AgentMonitorPanel = None
try:
    from gui.panels.pipeline_monitor import PipelineMonitorPanel as _PipelineMonitorPanel
except Exception:
    _PipelineMonitorPanel = None
try:
    from gui.widgets.ai_core_widget import AICoreWidget as _AICoreWidget
except Exception:
    _AICoreWidget = None
try:
    from gui.panels.memory_panel import MemoryPanel as _MemoryPanel
except Exception:
    _MemoryPanel = None
try:
    from gui.panels.intelligence_panel import IntelligencePanel as _IntelligencePanel
except Exception:
    _IntelligencePanel = None
try:
    from gui.windows.resource_monitor import ResourceMonitorWindow as _ResourceMonitorWindow
    _HAS_RESOURCE_MONITOR = True
except ImportError:
    _HAS_RESOURCE_MONITOR = False


class JARVIS(QMainWindow):

    def __init__(self):
        super().__init__()
        db_init()
        # Record session start for context predictor learning
        try:
            from intelligence.context_predictor import get_context_predictor
            get_context_predictor().record_session_start()
        except Exception:
            pass
        self._mini_hud = _MiniHUD() if _MiniHUD is not None else None
        self.setWindowTitle("J.A.R.V.I.S. — Cybersecurity Operations Center")
        self.resize(1460, 900)
        self.setMinimumSize(1080, 660)

        # ── Systems
        self._llm     = LLM()
        self._tts     = TTS()
        self._stt     = STT()
        self._auto    = AutonomousAgent(self._llm)
        self._monitor = MonitorAgent()
        self._evo     = SelfEvolution(self._llm, Path(__file__).resolve())
        _TTS_REF.clear(); _TTS_REF.append(self._tts)
        self._pool    = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(4)

        # ── State
        self._voice_on         : bool                  = getattr(_cfg, 'ALWAYS_SPEAK', False)
        self._busy             : bool                  = False
        self._pending_w        : Optional[AgentWorker] = None
        self._pending_patch    : Optional[str]         = None
        self._pending_summary  : Optional[str]         = None
        self._history          : list[dict]            = []
        self._streaming_bubble : Optional[Bubble]      = None

        self._settings_win = None   # SettingsPanel (lazy-init)

        # Resource monitor — lazy init
        self._resource_monitor: object = None

        # Keyboard shortcut: Ctrl+Shift+R opens resource monitor
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+Shift+R"), self,
                  activated=self._open_resource_monitor)

        _settings_store.load()
        # Load saved theme/brightness before building UI
        try:
            from gui.theme import theme as _theme_mgr
            _theme_mgr.load()
        except Exception:
            pass
        self._apply_stylesheet()
        self._build_ui()
        _PERSONA_CB.clear(); _PERSONA_CB.append(self._on_persona_switch)
        # Register theme change listener so stylesheet reapplies on every switch
        try:
            from gui.theme import theme as _theme_mgr
            _theme_mgr.add_change_listener(self._on_theme_changed)
            self._on_theme_changed()  # apply saved theme immediately at boot
        except Exception:
            pass
        self._wire_signals()
        self._wire_evolution()

        # Restore last used persona (theme already restored via theme.load() above)
        # Refresh button state + voice profile silently — no TTS announcement on boot
        try:
            _saved_persona = _settings_store.get("active_persona") or "jarvis"
            _cfg.ACTIVE_PERSONA = _saved_persona
            self._refresh_persona_btn_states(_saved_persona)
            if _saved_persona != "jarvis":
                from voice.profiles import get_profile_for_persona as _gp
                self._tts.set_profile(_gp(_saved_persona).name)
        except Exception:
            self._refresh_persona_btn_states("jarvis")

        QTimer.singleShot(500, self._boot)

    # ─────────────────────────────────────────────────────────────────────────
    #  Stylesheet
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_stylesheet(self):
        mc = _cfg.MONO_CSS
        self.setStyleSheet(f"""
        * {{ font-family:{mc}; }}
        QMainWindow, QWidget {{
            background:{P['base']}; color:{P['t0']}; border:none; outline:none;
        }}
        QScrollArea  {{ border:none; background:transparent; }}
        QScrollBar:vertical {{
            background:transparent; width:4px; border-radius:2px; margin:0;
        }}
        QScrollBar::handle:vertical {{
            background:{P['b1']}; border-radius:2px; min-height:24px;
        }}
        QScrollBar::handle:vertical:hover {{ background:{P['arc_d']}; }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{ height:0; border:none; }}
        QScrollBar:horizontal {{ height:0; border:none; }}
        QSplitter::handle {{ background:{P['b0']}; }}
        QTextEdit {{
            background:{P['input']}; color:{P['t0']};
            border:1px solid {P['b1']}; border-radius:7px;
            font-size:12px; padding:8px 12px;
        }}
        QTextEdit:focus {{ border-color:{P['arc_d']}; }}
        QToolTip {{
            background:{P['card']}; color:{P['t0']};
            border:1px solid {P['b2']}; border-radius:4px;
            padding:5px 10px; font-size:11px;
        }}
        QInputDialog QLineEdit {{
            background:{P['input']}; color:{P['t0']};
            border:1px solid {P['b2']}; border-radius:5px;
            padding:6px 10px; font-size:12px;
        }}
        """)

    # ─────────────────────────────────────────────────────────────────────────
    #  Layout construction
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root   = QWidget(); self.setCentralWidget(root)
        root_v = QVBoxLayout(root)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)

        root_v.addWidget(self._mk_topbar())

        mid = QSplitter(Qt.Horizontal)
        mid.setHandleWidth(1)
        self._telemetry = TelemetryPanel(self)
        self._telemetry.submit_requested.connect(self._submit)
        self._telemetry.new_project_clicked.connect(self._new_project)
        self._telemetry.voice_toggled.connect(self._on_voice_toggle)
        mid.addWidget(self._telemetry)
        mid.addWidget(self._mk_chat())
        mid.addWidget(self._mk_right())
        mid.setSizes([218, 960, 282])
        mid.setStretchFactor(1, 1)
        root_v.addWidget(mid, 1)

        root_v.addWidget(self._mk_wave_row())
        self._input_bar = self._mk_input_bar()
        root_v.addWidget(self._input_bar)
        root_v.addWidget(self._mk_statusbar())

        # ── Sync voice toggle visual state with _voice_on (ALWAYS_SPEAK) ──
        if self._voice_on:
            self._telemetry._voice_toggle.blockSignals(True)
            self._telemetry._voice_toggle.setChecked(True)
            self._telemetry._voice_toggle.blockSignals(False)
            self._telemetry.set_voice_toggle_text("VOICE  ONLINE")
            self._telemetry.set_voice_status("Hold mic to speak", P["arc"])
            self._mic_btn.setEnabled(True)

        # ── Emergency kill switch hotkey ──────────────────────────────────
        self._kill_shortcut = QShortcut(QKeySequence("Ctrl+Alt+Shift+K"), self)
        self._kill_shortcut.activated.connect(self._on_kill_switch)

        if self._mini_hud is not None:
            _mini_shortcut = QShortcut(QKeySequence("Ctrl+Shift+J"), self)
            _mini_shortcut.activated.connect(self._mini_hud.toggle)

    # ── Top bar ───────────────────────────────────────────────────────────────

    def _mk_topbar(self) -> QWidget:
        bar = QWidget(); bar.setFixedHeight(62)
        bar.setStyleSheet(
            f"background:{P['surface']};border-bottom:1px solid {P['b0']};"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 0, 16, 0); row.setSpacing(12)

        self._arc = ArcReactor(50)
        row.addWidget(self._arc)

        tb = QVBoxLayout(); tb.setSpacing(2)
        self._title_lbl = QLabel("J.A.R.V.I.S.")
        self._title_lbl.setStyleSheet(
            f"color:{P['arc']};font-family:{_cfg.DISPLAY_CSS};font-size:26px;"
            f"font-weight:700;letter-spacing:7px;background:transparent;"
        )
        t2 = QLabel("CYBERSECURITY OPERATIONS CENTER")
        t2.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;"
            f"letter-spacing:4px;background:transparent;"
        )
        tb.addWidget(self._title_lbl); tb.addWidget(t2)
        row.addLayout(tb)
        row.addStretch()

        # ── Persona switcher buttons ──────────────────────────────────────
        _PERSONA_DEFS = [
            ("jarvis",  "JARVIS",   "#18e0c1"),
            ("india",   "INDIA",    "#ffa020"),
            ("morgan",  "MORGAN",   "#b060ff"),
            ("ct7567",  "CT-7567",  "#39d353"),
            ("jarjar",  "⬤",        "#FFD700"),   # hidden easter egg — gold dot
        ]
        self._persona_btns: dict[str, QPushButton] = {}
        for _pk, _plabel, _pcol in _PERSONA_DEFS:
            _pb = QPushButton(_plabel)
            _pb.setFixedHeight(26)
            _pb.setCursor(QCursor(Qt.PointingHandCursor))
            _pb.setToolTip(f"Switch to {_plabel} persona")
            _pb.clicked.connect(lambda checked=False, k=_pk: self._on_persona_btn_click(k))
            self._persona_btns[_pk] = _pb
            row.addWidget(_pb)

        _psep = QFrame()
        _psep.setFrameShape(QFrame.VLine)
        _psep.setFixedHeight(30)
        _psep.setStyleSheet(f"background:{P['b1']};margin:0 4px;")
        row.addWidget(_psep)

        self._b_proj  = self._badge("PROJECT",   "—",       P["blue"])
        self._b_llm   = self._badge("LLM",       "OFFLINE", P["red"])
        self._b_clock = self._badge("LOCAL TIME", "",        P["arc"])
        row.addWidget(self._b_proj)
        row.addWidget(self._b_llm)
        row.addWidget(self._b_clock)

        self._clock_t = QTimer(self)
        self._clock_t.timeout.connect(self._tick_clock)
        self._clock_t.start(1000)
        self._tick_clock()

        _settings_btn = QPushButton("⚙")
        _settings_btn.setFixedSize(32, 32)
        _settings_btn.setCursor(QCursor(Qt.PointingHandCursor))
        _settings_btn.setToolTip("Settings")
        _settings_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{P['t2']};"
            f"border:1px solid {P['b1']};border-radius:4px;font-size:15px;}}"
            f"QPushButton:hover{{color:{P['arc']};border-color:{P['arc']}66;}}"
        )
        _settings_btn.clicked.connect(self._on_settings_toggled)
        row.addWidget(_settings_btn)

        return bar

    def _badge(self, key: str, val: str, col: str) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background:{col}0a;border:1px solid {col}22;border-radius:5px;")
        v = QVBoxLayout(w); v.setContentsMargins(10, 5, 10, 5); v.setSpacing(1)
        k = QLabel(key)
        k.setStyleSheet(
            f"color:{col}66;font-size:8px;letter-spacing:2px;background:transparent;border:none;"
        )
        vl = QLabel(val); vl.setObjectName("val")
        vl.setStyleSheet(
            f"color:{col};font-size:10px;font-weight:700;background:transparent;border:none;"
        )
        v.addWidget(k); v.addWidget(vl)
        return w

    def _set_badge(self, badge: QWidget, val: str, col: str):
        badge.setStyleSheet(f"background:{col}0a;border:1px solid {col}22;border-radius:5px;")
        lbl = badge.findChild(QLabel, "val")
        if lbl:
            lbl.setText(val)
            lbl.setStyleSheet(
                f"color:{col};font-size:10px;font-weight:700;background:transparent;border:none;"
            )

    def _tick_clock(self):
        lbl = self._b_clock.findChild(QLabel, "val")
        if lbl: lbl.setText(datetime.now().strftime("%H:%M:%S"))

    def _on_settings_toggled(self):
        if self._settings_win is None:
            from gui.settings_panel import SettingsPanel
            self._settings_win = SettingsPanel(self._tts, self._stt, parent=self)
            self._settings_win.hud_brightness_changed.connect(
                lambda v: None  # placeholder — no CenterPanel in this layout
            )
        if self._settings_win.isVisible():
            self._settings_win.hide()
            return
        # Position flush against right edge of main window
        geo   = self.geometry()
        h     = geo.height()
        x     = geo.x() + geo.width() - self._settings_win.width()
        y     = geo.y()
        self._settings_win.setGeometry(x, y, self._settings_win.width(), h)
        self._settings_win.show()
        self._settings_win.raise_()


    def _sec_hdr(self, text: str) -> QLabel:
        w = QLabel(text); w.setFixedHeight(28)
        w.setStyleSheet(
            f"color:{P['t3']};font-family:{_cfg.DISPLAY_CSS};font-size:9px;"
            f"letter-spacing:3px;font-weight:600;"
            f"padding-left:12px;border-top:1px solid {P['b0']};"
            f"border-bottom:1px solid {P['b0']};background:{P['void']};"
        )
        return w

    def _sbtn(self, text: str, col: str = None) -> QPushButton:
        btn = QPushButton(text); c = col or P["t1"]
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{c};
                border:none; text-align:left;
                padding:7px 16px;
                font-family:'{_cfg.MONO}'; font-size:11px;
            }}
            QPushButton:hover {{
                background:{P['arc']}0a; color:{P['arc']};
            }}
        """)
        return btn

    # ── Chat area ─────────────────────────────────────────────────────────────

    def _mk_chat(self) -> QWidget:
        container = QWidget()
        container_v = QVBoxLayout(container)
        container_v.setContentsMargins(0, 0, 0, 0)
        container_v.setSpacing(0)

        # ── Tab strip ──────────────────────────────────────────────────────────
        tab_bar = QWidget(); tab_bar.setFixedHeight(32)
        tab_bar.setStyleSheet(f"background:{P['void']};border-bottom:1px solid {P['b0']};")
        tab_row = QHBoxLayout(tab_bar)
        tab_row.setContentsMargins(12, 0, 12, 0); tab_row.setSpacing(0)

        self._tab_btns: list[QPushButton] = []
        for i, label in enumerate(["AI CORE", "CHAT", "SCAN", "RESEARCH", "AGENTS", "PIPELINES", "MEMORY", "INTEL"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            btn.setStyleSheet(self._tab_style(False))
            btn.clicked.connect(lambda _, idx=i: self._switch_view(idx))
            tab_row.addWidget(btn)
            self._tab_btns.append(btn)
        tab_row.addStretch()
        self._tab_btns[0].setChecked(True)
        self._tab_btns[0].setStyleSheet(self._tab_style(True))
        container_v.addWidget(tab_bar)

        # ── Stacked views ──────────────────────────────────────────────────────
        self._center_stack = QStackedWidget()
        container_v.addWidget(self._center_stack, 1)

        # View 0: AI CORE — 3D OPS graph via QWebEngineView; OrbWidget as fallback
        self._orb = None
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEngineSettings
            from PySide6.QtCore import QUrl as _QUrl

            _web_view = QWebEngineView()
            _ws = _web_view.settings()
            _ws.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            # Allow file:// page to open ws:// connections to the bridge when it's running
            _ws.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

            # setHtml injects content directly into the already-sized widget so
            # window.innerWidth/innerHeight are valid when the script runs.
            # Base URL = bridge origin so ws:// and fetch() resolve against it.
            _html_path = Path(__file__).parent.parent / "bridge" / "static" / "index.html"
            _web_view.setHtml(
                _html_path.read_text(encoding="utf-8"),
                _QUrl("http://127.0.0.1:5000/"),
            )
            self._ai_core_view = _web_view

            _ac_container = QWidget()
            _ac_layout = QVBoxLayout(_ac_container)
            _ac_layout.setContentsMargins(0, 0, 0, 0)
            _ac_layout.addWidget(_web_view)
            self._center_stack.addWidget(_ac_container)

            # Also create OrbWidget hidden — used for state animations
            try:
                from gui.widgets.orb_widget import OrbWidget as _OrbWidget
                self._orb = _OrbWidget()
                self._orb.hide()
            except Exception:
                pass

        except ImportError:
            # QWebEngineWidgets not available — fall back to OrbWidget
            import logging as _lg
            _lg.getLogger(__name__).warning(
                "[AiCore] PySide6-WebEngine not installed — using OrbWidget. "
                "Install: pip install PySide6-WebEngine"
            )
            try:
                from gui.widgets.orb_widget import OrbWidget as _OrbWidget
                self._orb = _OrbWidget()
                self._orb.setStyleSheet("background: transparent; border: none;")
                self._center_stack.addWidget(self._orb)
            except Exception:
                _ac_fallback = QLabel("AI Core unavailable")
                _ac_fallback.setAlignment(Qt.AlignCenter)
                _ac_fallback.setStyleSheet(
                    f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:10px;"
                )
                self._center_stack.addWidget(_ac_fallback)

        # View 1: Chat (existing content)
        chat_page = QWidget(); chat_page.setStyleSheet(f"background:{P['base']};")
        chat_v = QVBoxLayout(chat_page)
        chat_v.setContentsMargins(0, 0, 0, 0); chat_v.setSpacing(0)

        ch = QWidget(); ch.setFixedHeight(34)
        ch.setStyleSheet(f"background:{P['surface']};border-bottom:1px solid {P['b0']};")
        chr_ = QHBoxLayout(ch); chr_.setContentsMargins(16, 0, 16, 0)
        op = QLabel("OPERATIONS LOG")
        op.setStyleSheet(f"color:{P['t3']};font-size:8px;letter-spacing:3px;")
        self._log_count = QLabel("READY")
        self._log_count.setStyleSheet(
            f"color:{P['arc']};font-size:8px;letter-spacing:2px;font-weight:700;"
        )
        chr_.addWidget(op); chr_.addStretch(); chr_.addWidget(self._log_count)
        chat_v.addWidget(ch)

        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._chat_w = QWidget()
        self._chat_w.setStyleSheet(f"background:{P['base']};")
        self._chat_vbox = QVBoxLayout(self._chat_w)
        self._chat_vbox.setContentsMargins(16, 16, 16, 16)
        self._chat_vbox.setSpacing(8)
        self._chat_vbox.addStretch()

        self._dots = ThinkDots(); self._dots.hide()
        self._chat_vbox.addWidget(self._dots)

        self._scroll.setWidget(self._chat_w)
        chat_v.addWidget(self._scroll, 1)

        self._confirm_bar = self._mk_confirm_bar()
        self._confirm_bar.hide()
        chat_v.addWidget(self._confirm_bar)
        self._center_stack.addWidget(chat_page)

        # View 2: Scan Graph
        if _ScanGraphPanel is not None:
            self._scan_panel = _ScanGraphPanel()
            self._center_stack.addWidget(self._scan_panel)
        else:
            _sp = QLabel("Scan graph unavailable")
            _sp.setAlignment(Qt.AlignCenter)
            _sp.setStyleSheet(f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:10px;")
            self._center_stack.addWidget(_sp)

        # View 3: Research
        self._research_view = QTextEdit()
        self._research_view.setReadOnly(True)
        self._research_view.setStyleSheet(
            f"QTextEdit{{background:{P['void']};color:{P['t1']};"
            f"border:none;font-family:'{_cfg.MONO}';font-size:9px;padding:12px;}}"
        )
        self._research_view.setPlaceholderText(
            "Research intelligence will appear here.\nAsk JARVIS: 'show research digest'"
        )
        self._center_stack.addWidget(self._research_view)

        # View 4: Agent task monitor
        if _AgentMonitorPanel is not None:
            self._agent_panel = _AgentMonitorPanel()
            self._center_stack.addWidget(self._agent_panel)
        else:
            _ap = QLabel("Agent monitor unavailable")
            _ap.setAlignment(Qt.AlignCenter)
            _ap.setStyleSheet(f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:10px;")
            self._center_stack.addWidget(_ap)

        # View 5: Pipeline monitor
        if _PipelineMonitorPanel is not None:
            self._pipeline_panel = _PipelineMonitorPanel()
            self._center_stack.addWidget(self._pipeline_panel)
        else:
            _pp = QLabel("Pipeline monitor unavailable")
            _pp.setAlignment(Qt.AlignCenter)
            _pp.setStyleSheet(f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:10px;")
            self._center_stack.addWidget(_pp)

        # View 6: Memory Bank
        if _MemoryPanel is not None:
            self._memory_panel = _MemoryPanel()
            self._center_stack.addWidget(self._memory_panel)
        else:
            _mp = QLabel("Memory subsystem unavailable")
            _mp.setAlignment(Qt.AlignCenter)
            _mp.setStyleSheet(f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:10px;")
            self._center_stack.addWidget(_mp)

        # View 7: Intelligence Panel
        if _IntelligencePanel is not None:
            self._intel_panel = _IntelligencePanel()
            self._center_stack.addWidget(self._intel_panel)
        else:
            _ip = QLabel("Intelligence panel unavailable")
            _ip.setAlignment(Qt.AlignCenter)
            _ip.setStyleSheet(f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:10px;")
            self._center_stack.addWidget(_ip)

        return container

    def _mk_confirm_bar(self) -> QWidget:
        bar = QWidget(); bar.setFixedHeight(54)
        bar.setStyleSheet(
            f"background:{P['amber']}12;border-top:1px solid {P['amber']}33;"
        )
        row = QHBoxLayout(bar); row.setContentsMargins(16, 0, 16, 0); row.setSpacing(8)
        self._confirm_lbl = QLabel("Execute command?")
        self._confirm_lbl.setStyleSheet(
            f"color:{P['amber']};font-family:'{_cfg.MONO}';font-size:11px;font-weight:700;"
        )
        yes = QPushButton("✓  Execute")
        yes.setCursor(QCursor(Qt.PointingHandCursor))
        yes.setStyleSheet(
            f"QPushButton{{background:{P['green']}1a;color:{P['green']};"
            f"border:1px solid {P['green']}44;border-radius:4px;"
            f"font-family:'{_cfg.MONO}';font-size:11px;font-weight:700;padding:6px 18px;}}"
            f"QPushButton:hover{{background:{P['green']}33;}}"
        )
        no = QPushButton("✗  Decline")
        no.setCursor(QCursor(Qt.PointingHandCursor))
        no.setStyleSheet(
            f"QPushButton{{background:transparent;color:{P['t2']};"
            f"border:1px solid {P['b1']};border-radius:4px;"
            f"font-family:'{_cfg.MONO}';font-size:11px;padding:6px 18px;}}"
            f"QPushButton:hover{{color:{P['red']};border-color:{P['red']}33;}}"
        )
        yes.clicked.connect(self._confirm_yes)
        no.clicked.connect(self._confirm_no)
        row.addWidget(self._confirm_lbl, 1)
        row.addWidget(yes); row.addWidget(no)
        return bar

    # ── Center view switcher helpers ──────────────────────────────────────────

    def _tab_style(self, active: bool) -> str:
        if active:
            return (
                f"QPushButton{{background:transparent;color:{P['arc']};"
                f"border:none;border-bottom:2px solid {P['arc']};"
                f"font-family:'{_cfg.MONO}';font-size:9px;letter-spacing:2px;"
                f"font-weight:600;padding:0 16px;border-radius:0;}}"
            )
        return (
            f"QPushButton{{background:transparent;color:{P['t3']};"
            f"border:none;border-bottom:2px solid transparent;"
            f"font-family:'{_cfg.MONO}';font-size:9px;letter-spacing:2px;"
            f"padding:0 16px;border-radius:0;}}"
            f"QPushButton:hover{{color:{P['t2']};}}"
        )

    def _switch_view(self, idx: int) -> None:
        for i, btn in enumerate(self._tab_btns):
            btn.setStyleSheet(self._tab_style(i == idx))
            btn.setChecked(i == idx)
        self._center_stack.setCurrentIndex(idx)
        # Hide the main input bar on AI CORE tab — it has its own chat bar
        if hasattr(self, '_input_bar'):
            self._input_bar.setVisible(idx != 0)
        # idx 0 = AI CORE  (no refresh needed — animates continuously)
        # idx 1 = CHAT
        # idx 2 = SCAN
        # idx 3 = RESEARCH
        # idx 4 = AGENTS
        # idx 5 = PIPELINES
        # idx 6 = MEMORY
        if idx == 2 and hasattr(self, '_scan_panel'):
            self._scan_panel.refresh()
        elif idx == 3:
            self._load_research_view()
        elif idx == 4 and hasattr(self, '_agent_panel'):
            self._agent_panel.refresh()
        elif idx == 5 and hasattr(self, '_pipeline_panel'):
            self._pipeline_panel.refresh()
        elif idx == 6 and hasattr(self, '_memory_panel'):
            self._memory_panel.refresh()

    def _load_research_view(self) -> None:
        try:
            from storage.db import get_db
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT severity, title, source, created_at "
                    "FROM research_items WHERE actioned=0 "
                    "ORDER BY severity DESC, created_at DESC LIMIT 50"
                ).fetchall()
            if not rows:
                self._research_view.setPlainText("No unactioned research items.")
                return
            lines = []
            for r in rows:
                sev = (r[0] or 'info').upper()
                lines.append(f"[{sev}] {r[1] or 'Unknown'}\n  Source: {r[2]}  •  {r[3][:10]}\n")
            self._research_view.setPlainText("\n".join(lines))
        except Exception as exc:
            self._research_view.setPlainText(f"Research unavailable: {exc}")

    # ── Right rail ────────────────────────────────────────────────────────────

    def _mk_right(self) -> QWidget:
        panel = QWidget(); panel.setFixedWidth(282)
        panel.setStyleSheet(
            f"background:{P['surface']};border-left:1px solid {P['b0']};"
        )
        v = QVBoxLayout(panel); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        v.addWidget(self._sec_hdr("AUTONOMOUS AGENT"))

        self._auto_btn = QPushButton("ACTIVATE AUTO AGENT")
        self._auto_btn.setCheckable(True)
        self._auto_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._auto_btn.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{P['amber']};
                border:1px solid {P['amber_d']}; border-radius:4px;
                font-family:'{_cfg.MONO}'; font-size:10px; letter-spacing:1px;
                padding:8px; margin:8px;
            }}
            QPushButton:checked {{
                background:{P['amber']}14; border-color:{P['amber']};
            }}
            QPushButton:hover {{ border-color:{P['amber']}; }}
        """)
        self._auto_btn.toggled.connect(self._on_auto_toggle)
        v.addWidget(self._auto_btn)

        self._think_btn = QPushButton(">>  THINK NOW")
        self._think_btn.setEnabled(False)
        self._think_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._think_btn.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{P['t3']};
                border:1px solid {P['b0']}; border-radius:4px;
                font-family:'{_cfg.MONO}'; font-size:10px; letter-spacing:1px;
                padding:6px; margin:0 8px 8px 8px;
            }}
            QPushButton:enabled {{
                color:{P['amber']}; border-color:{P['amber_d']};
            }}
            QPushButton:enabled:hover {{
                background:{P['amber']}0a; border-color:{P['amber']};
            }}
        """)
        self._think_btn.clicked.connect(lambda: self._auto.think_now())
        v.addWidget(self._think_btn)

        v.addWidget(self._sec_hdr("PENDING APPROVALS"))
        prop_scroll = QScrollArea(); prop_scroll.setWidgetResizable(True)
        prop_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._prop_w = QWidget(); self._prop_w.setStyleSheet("background:transparent;")
        self._prop_vbox = QVBoxLayout(self._prop_w)
        self._prop_vbox.setContentsMargins(10, 8, 10, 8); self._prop_vbox.setSpacing(8)
        self._prop_vbox.addStretch()
        prop_scroll.setWidget(self._prop_w)
        v.addWidget(prop_scroll, 1)

        v.addWidget(self._sec_hdr("NEURAL PATHWAYS"))
        self._ticker_widget = QWidget()
        self._ticker_widget.setFixedHeight(160)
        self._ticker_widget.setStyleSheet(
            f"background:{P['void']};border-top:1px solid {P['b0']};"
        )
        self._ticker_vbox = QVBoxLayout(self._ticker_widget)
        self._ticker_vbox.setContentsMargins(0, 0, 0, 0); self._ticker_vbox.setSpacing(0)
        self._ticker_vbox.addStretch()
        self._tool_log = QTextEdit(); self._tool_log.hide()
        v.addWidget(self._ticker_widget)

        # Self-Evolution panel
        v.addWidget(self._sec_hdr("EVO  SELF-EVOLUTION"))

        self._evo_analyze_btn = QPushButton("DNA  ANALYSE & EVOLVE")
        self._evo_analyze_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._evo_analyze_btn.setStyleSheet(f"""
            QPushButton {{
                background:{P['purple']}14; color:{P['purple']};
                border:1px solid {P['purple']}44; border-radius:4px;
                font-family:'{_cfg.MONO}'; font-size:10px; letter-spacing:1px;
                padding:7px; margin:7px 8px 3px 8px;
            }}
            QPushButton:hover {{
                background:{P['purple']}28; border-color:{P['purple']}88;
            }}
            QPushButton:disabled {{
                color:{P['t3']}; border-color:{P['b0']}; background:transparent;
            }}
        """)
        self._evo_analyze_btn.clicked.connect(self._start_evolution)
        v.addWidget(self._evo_analyze_btn)

        evo_btns = QHBoxLayout()
        evo_btns.setContentsMargins(10, 0, 10, 4); evo_btns.setSpacing(8)

        self._evo_approve_btn = QPushButton("✓  Apply")
        self._evo_approve_btn.setEnabled(False)
        self._evo_approve_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._evo_approve_btn.setStyleSheet(f"""
            QPushButton {{
                background:{P['green']}1a; color:{P['green']};
                border:1px solid {P['green']}44; border-radius:4px;
                font-family:'{_cfg.MONO}'; font-size:10px; padding:5px 8px;
            }}
            QPushButton:hover {{ background:{P['green']}33; }}
            QPushButton:disabled {{
                color:{P['t3']}; border-color:{P['b0']}; background:transparent;
            }}
        """)
        self._evo_approve_btn.clicked.connect(self._approve_evolution)

        self._evo_reject_btn = QPushButton("✗  Discard")
        self._evo_reject_btn.setEnabled(False)
        self._evo_reject_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._evo_reject_btn.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{P['t2']};
                border:1px solid {P['b1']}; border-radius:4px;
                font-family:'{_cfg.MONO}'; font-size:10px; padding:5px 8px;
            }}
            QPushButton:hover {{ color:{P['red']}; border-color:{P['red']}44; }}
            QPushButton:disabled {{ color:{P['t3']}; border-color:{P['b0']}; }}
        """)
        self._evo_reject_btn.clicked.connect(self._reject_evolution)

        evo_btns.addWidget(self._evo_approve_btn)
        evo_btns.addWidget(self._evo_reject_btn)
        v.addLayout(evo_btns)

        self._evo_status_lbl = QLabel("Standing by")
        self._evo_status_lbl.setWordWrap(True)
        self._evo_status_lbl.setStyleSheet(
            f"color:{P['purple']};font-size:9px;font-family:'{_cfg.MONO}';"
            f"letter-spacing:0.5px;padding:2px 10px 4px 10px;"
        )
        v.addWidget(self._evo_status_lbl)

        self._evo_diff = QTextEdit()
        self._evo_diff.setReadOnly(True)
        self._evo_diff.setFixedHeight(130)
        self._evo_diff.setPlaceholderText("Proposed changes will appear here…")
        self._evo_diff.setStyleSheet(
            f"QTextEdit{{background:{P['void']};color:{P['t1']};"
            f"border:1px solid {P['b0']};"
            f"border-left:3px solid {P['purple']}55;"
            f"font-family:'{_cfg.MONO}';font-size:9px;"
            f"padding:6px;border-radius:0;}}"
        )
        v.addWidget(self._evo_diff)
        return panel

    # ── Waveform row ──────────────────────────────────────────────────────────

    def _mk_wave_row(self) -> QWidget:
        bar = QWidget(); bar.setFixedHeight(60)
        bar.setStyleSheet(f"background:{P['void']};border-top:1px solid {P['b0']};")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 8, 16, 8); row.setSpacing(8)

        # Real audio-reactive waveform replaces the static WaveformVisualizer
        self._wave = WaveformVisualizer()  # kept hidden; legacy set_state() calls still work
        self._wave.hide()
        self._audio_meter = AudioMeter()
        row.addWidget(self._audio_meter, 1)

        # Mic icon removed — voice state is shown in left panel and orb
        # Keep self._mic_btn as a hidden no-op so existing references do not crash
        self._mic_btn = QPushButton()
        self._mic_btn.hide()
        self._mic_btn.setCheckable(True)
        self._mic_btn.toggled.connect(self._on_mic_btn)
        return bar

    def _on_mic_btn(self, on: bool):
        if on:
            self._ptt_start()

    # ── Input bar ─────────────────────────────────────────────────────────────

    def _mk_input_bar(self) -> QWidget:
        bar = QWidget(); bar.setFixedHeight(52)
        bar.setStyleSheet(f"background:{P['surface']};border-top:1px solid {P['b0']};")
        row = QHBoxLayout(bar); row.setContentsMargins(16, 8, 16, 8); row.setSpacing(8)

        prompt = QLabel(">_")
        prompt.setStyleSheet(
            f"color:{P['arc']};font-family:{_cfg.MONO_CSS};font-size:16px;font-weight:700;"
        )
        row.addWidget(prompt)

        self._input = QTextEdit()
        self._input.setFixedHeight(36)
        self._input.setStyleSheet(
            f"background:{P['input']};color:{P['t0']};"
            f"border:1px solid {P['b1']};border-radius:6px;"
            f"font-family:{_cfg.MONO_CSS};font-size:12px;padding:5px 10px;"
        )
        self._input.setPlaceholderText(
            "Issue a command to J.A.R.V.I.S.    "
            "(Enter to send  ·  Shift+Enter for newline)"
        )
        self._input.installEventFilter(self)
        row.addWidget(self._input, 1)

        send = QPushButton("TRANSMIT")
        send.setFixedSize(96, 36)
        send.setCursor(QCursor(Qt.PointingHandCursor))
        send.setStyleSheet(f"""
            QPushButton {{
                background:{P['arc_d']}; color:{P['void']};
                border:none; border-radius:6px;
                font-family:{_cfg.MONO_CSS}; font-size:10px;
                font-weight:700; letter-spacing:2px;
            }}
            QPushButton:hover {{ background:{P['arc']}; }}
            QPushButton:pressed {{ background:{P['arc_m']}; }}
        """)
        send.clicked.connect(self._on_send)
        row.addWidget(send)
        return bar

    # ── Status bar ────────────────────────────────────────────────────────────

    def _mk_statusbar(self) -> QWidget:
        bar = QWidget(); bar.setFixedHeight(22)
        bar.setStyleSheet(f"background:{P['void']};border-top:1px solid {P['b0']};")
        row = QHBoxLayout(bar); row.setContentsMargins(16, 0, 16, 0)
        self._status = QLabel("All systems nominal")
        self._status.setStyleSheet(f"color:{P['t3']};font-size:9px;letter-spacing:1px;")
        credits = QLabel("HUNT IN-SCOPE ONLY  ·  NO DAMAGE  ·  RESPONSIBLE DISCLOSURE")
        credits.setStyleSheet(f"color:{P['t3']};font-size:9px;letter-spacing:1px;")
        row.addWidget(self._status); row.addStretch(); row.addWidget(credits)
        return bar

    # ─────────────────────────────────────────────────────────────────────────
    #  Signal wiring
    # ─────────────────────────────────────────────────────────────────────────

    def _wire_signals(self):
        self._auto.signals.proposals_ready.connect(self._on_proposals)
        self._auto.signals.task_done.connect(self._on_auto_task_done)
        self._auto.signals.observation.connect(
            lambda s: self._set_status(s, clear_ms=8000)
        )
        self._monitor.signals.alert.connect(self._on_monitor_alert)
        self._monitor.signals.ticker.connect(self._tool_ticker_add)

    @Slot(str)
    def _on_monitor_alert(self, msg: str):
        self._add_msg("assistant", msg)
        if self._voice_on:
            self._tts.speak(msg[:120])

    def _wire_evolution(self):
        self._evo.signals.status.connect(self._on_evo_status)
        self._evo.signals.proposal_ready.connect(self._on_evo_proposal)
        self._evo.signals.auto_apply.connect(self._on_evo_auto_apply)
        self._evo.signals.applied.connect(self._on_evo_applied)
        self._evo.signals.error.connect(self._on_evo_error)

    # ─────────────────────────────────────────────────────────────────────────
    #  Kill switch
    # ─────────────────────────────────────────────────────────────────────────

    def _on_kill_switch(self) -> None:
        """Ctrl+Alt+Shift+K — triggers emergency stop on all autonomous ops."""
        _play_sound("ui_kill_switch")
        try:
            from runtime.kill_switch import get_kill_switch
            get_kill_switch().trigger("hotkey")
        except Exception:
            pass
        QApplication.quit()

    # ─────────────────────────────────────────────────────────────────────────
    #  Event filter — Enter key
    # ─────────────────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self._input and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key_Return and not event.modifiers() & Qt.ShiftModifier:
                self._on_send()
                return True
            if event.key() == Qt.Key_Up and event.modifiers() & Qt.ControlModifier:
                user_msgs = [m["content"] for m in self._history if m["role"] == "user"]
                if user_msgs:
                    self._input.setPlainText(user_msgs[-1])
                return True
        return super().eventFilter(obj, event)
    def _boot(self):
        _sound_start()
        _play_sound("ui_startup")

        # ── Restore window geometry from previous session ─────────────────────
        try:
            import storage.settings_store as _ss
            _geo_b64 = _ss.get("window.geometry")
            if _geo_b64:
                from PySide6.QtCore import QByteArray
                geo = QByteArray.fromBase64(_geo_b64.encode())
                self.restoreGeometry(geo)
        except Exception:
            pass

        proj = get_active_project()
        self._set_badge(self._b_proj, proj.upper()[:16], P["blue"])
        self._add_msg(
            "assistant",
            f"Good day, sir. J.A.R.V.I.S. online.\n\n"
            f"All primary systems are operational. "
            f"Active project: {proj}. "
            f"Monitoring loop engaged — standing by.",
        )
        self._monitor.start()

        # Wake word listener (ambient intelligence — additive, won't crash if unavailable)
        try:
            import config as _wc
            if getattr(_wc, "AMBIENT_LISTENING_ENABLED", False):
                from voice.wake_listener import WakeListener
                self._wake_listener = WakeListener(
                    response_callback=lambda t: QTimer.singleShot(
                        0, lambda txt=t: self._submit(txt)
                    )
                )
                self._wake_listener.start()
        except Exception as _we:
            import logging
            logging.getLogger(__name__).warning(
                "WakeListener unavailable (non-fatal): %s", _we
            )

        # Speak greeting after a fixed delay so Chatterbox (6-8s load) is ready.
        # Polling _tts._ready fires too early — _ready=True before GPU warmup completes.
        _wake_phrase_boot = os.environ.get("JARVIS_WAKE_PHRASE", "") == "1"
        if _wake_phrase_boot:
            _greeting = "Daddy's home. Welcome back. All systems online."
        else:
            _greeting = (
                f"Good day, sir. J.A.R.V.I.S. online. "
                f"Active project: {proj}. Standing by."
            )
        QTimer.singleShot(10000, lambda: self._tts.speak(_greeting))

        def _check_llm_online():
            if self._llm.online:
                self._set_badge(self._b_llm, "ONLINE", P["green"])
                _t.stop()
        _t = QTimer(self)
        _t.timeout.connect(_check_llm_online)
        _t.start(500)

        # Research engine background poll (runs once on boot if enabled)
        try:
            import config as _rec
            if getattr(_rec, 'RESEARCH_ENGINE_ENABLED', False):
                import threading
                from research.engine import ResearchEngine
                def _research_boot():
                    try:
                        targets = []
                        from storage.db import get_db
                        with get_db() as _rconn:
                            rows = _rconn.execute(
                                "SELECT DISTINCT target FROM scan_targets LIMIT 10"
                            ).fetchall()
                            targets = [r[0] for r in rows if r and r[0]]
                        n = ResearchEngine().run(targets=targets or None)
                        if n > 0:
                            logging.getLogger(__name__).info(
                                "[Research] %d new items fetched on boot", n)
                    except Exception as _re:
                        logging.getLogger(__name__).debug("[Research] boot fetch: %s", _re)
                threading.Thread(target=_research_boot, daemon=True, name="research-boot").start()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Chat helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _add_msg(self, role: str, content: str):
        ts     = datetime.now().strftime("%H:%M:%S")
        bubble = Bubble(role, content, ts)
        insert_at = max(0, self._chat_vbox.count() - 2)
        self._chat_vbox.insertWidget(insert_at, bubble)
        save_message(role, content, get_active_project())
        count = self._chat_vbox.count() - 2
        self._log_count.setText(f"{count} ENTRIES")
        QTimer.singleShot(40, self._scroll_bottom)

    def _scroll_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_thinking(self, v: bool):
        self._dots.setVisible(v)
        if v:
            self._arc.set_state("speaking")
            self._wave.set_state("speak")
            self._audio_meter.set_state("speaking")
            QTimer.singleShot(40, self._scroll_bottom)
            if hasattr(self, '_orb') and self._orb is not None:
                self._orb.set_state("SPEAKING", "TRANSMITTING")
        else:
            self._arc.set_state("idle")
            self._wave.set_state("idle")
            self._audio_meter.set_state("idle")
            if hasattr(self, '_orb') and self._orb is not None:
                self._orb.set_state("NEURAL CORE ACTIVE", "STANDING BY")
        if self._mini_hud is not None:
            self._mini_hud.update_status("THINKING" if v else "IDLE")

    def _set_status(self, text: str, clear_ms: int = 0):
        self._status.setText(text)
        if clear_ms:
            QTimer.singleShot(clear_ms, lambda: self._status.setText("All systems nominal"))

    def _log_tool(self, text: str, col: str):
        self._set_status(text, 3000)

    def _tool_ticker_add(self, name: str, output: str):
        ts  = datetime.now().strftime("%H:%M:%S")
        row = QWidget(); row.setFixedHeight(26)
        row.setStyleSheet(
            f"background:transparent;border-bottom:1px solid {P['b0']}11;"
        )
        hl = QHBoxLayout(row)
        hl.setContentsMargins(10, 0, 10, 0); hl.setSpacing(6)

        dot = QLabel("●"); dot.setFixedWidth(12)
        dot.setStyleSheet(f"color:{P['arc']};font-size:7px;background:transparent;")
        lbl_name = QLabel(name)
        lbl_name.setStyleSheet(
            f"color:{P['arc_d']};font-family:'{_cfg.MONO}';"
            f"font-size:9px;font-weight:700;letter-spacing:1px;background:transparent;"
        )
        lbl_ts = QLabel(ts)
        lbl_ts.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;background:transparent;"
        )
        preview = output.replace("\n", " ").strip()[:40]
        lbl_out = QLabel(preview)
        lbl_out.setStyleSheet(
            f"color:{P['t2']};font-family:'{_cfg.MONO}';font-size:8px;background:transparent;"
        )
        lbl_out.setToolTip(output[:600])

        hl.addWidget(dot); hl.addWidget(lbl_name)
        hl.addWidget(lbl_out, 1); hl.addWidget(lbl_ts)

        self._ticker_vbox.insertWidget(max(0, self._ticker_vbox.count() - 1), row)
        while self._ticker_vbox.count() > 10:
            item = self._ticker_vbox.itemAt(0)
            if item and item.widget():
                item.widget().deleteLater()
            self._ticker_vbox.removeItem(item)

    # ─────────────────────────────────────────────────────────────────────────
    #  Input & submission
    # ─────────────────────────────────────────────────────────────────────────

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if text and not self._busy:
            self._input.clear()
            self._submit(text)

    # ── Interrupt patterns (natural language stop commands) ───────────────────
    _INTERRUPT_PATTERNS = [
        'shut up', 'stop talking', 'stop', 'be quiet', 'cancel',
        'enough', 'shut the fuck up', 'hold on', 'wait',
        'jarvis stop', "that's enough", 'ok stop', 'silence',
    ]

    def _submit(self, text: str):
        # Interrupt speech regardless of busy state — operator always wins
        if self._tts.is_speaking:
            self._tts.interrupt()

        # Natural-language interrupt: if the ONLY intent is to stop speech,
        # don't route to LLM — just stop and wait for next input
        lower = text.lower().strip()
        if any(p in lower for p in self._INTERRUPT_PATTERNS) and len(text.split()) <= 5:
            return

        # Jar Jar easter egg — "jar jar mode" in input activates Jar Jar persona
        if "jar jar" in lower or lower in ("jar jar mode", "meesa", "mesa jar jar"):
            self._on_persona_btn_click("jarjar")
            return

        # "JARVIS resume" exits Jar Jar (or any non-JARVIS persona) back to JARVIS
        if lower in ("jarvis resume", "resume jarvis", "exit jar jar", "jarvis mode"):
            if getattr(_cfg, 'ACTIVE_PERSONA', 'jarvis') != 'jarvis':
                self._on_persona_btn_click("jarvis")
                return

        if self._busy:
            return
        _unduck_sound()
        _play_sound("ui_transmit")
        self._busy = True
        self._add_msg("user", text)
        self._set_thinking(True)
        self._set_status("Processing…")

        history_snapshot = list(self._history[-16:])  # send last 16 msgs; 40 kept in memory for display
        worker = AgentWorker(
            llm=self._llm,
            project=get_active_project(),
            user_input=text,
            prior_history=history_snapshot,
        )
        worker.signals.reply.connect(self._on_reply)
        worker.signals.token.connect(self._on_token)
        worker.signals.tool_start.connect(self._on_tool_start)
        worker.signals.tool_end.connect(self._on_tool_end)
        worker.signals.need_confirm.connect(self._on_need_confirm)
        worker.signals.done.connect(self._on_agent_done)
        worker.signals.error.connect(self._on_agent_error)
        self._pending_w = worker
        self._pool.start(worker)

    # ── Agent callbacks ───────────────────────────────────────────────────────

    @Slot(str)
    def _on_token(self, chunk: str):
        if self._streaming_bubble is None:
            ts = datetime.now().strftime("%H:%M:%S")
            self._streaming_bubble = Bubble("assistant", "", ts)
            insert_at = max(0, self._chat_vbox.count() - 2)
            self._chat_vbox.insertWidget(insert_at, self._streaming_bubble)
            count = self._chat_vbox.count() - 2
            self._log_count.setText(f"{count} ENTRIES")
        self._streaming_bubble.append_text(chunk)
        QTimer.singleShot(40, self._scroll_bottom)

    @Slot(str)
    def _on_reply(self, reply: str):
        _play_sound("ui_receive")
        self._set_thinking(False)
        if self._streaming_bubble is not None:
            save_message("assistant", reply, get_active_project())
            self._streaming_bubble = None
        else:
            self._add_msg("assistant", reply)
        self._history.append({"role": "user",      "content": "[prior turn]"})
        self._history.append({"role": "assistant",  "content": reply})
        if len(self._history) > 40:
            self._history = self._history[-40:]
        if self._voice_on or getattr(_cfg, 'ALWAYS_SPEAK', False):
            _duck_sound()
            self._tts.speak(reply)
        if self._mini_hud is not None:
            self._mini_hud.update_response(reply)

    @Slot(str, str)
    def _on_tool_start(self, name: str, args: str):
        _play_sound("ui_tool_start")
        self._log_tool(f"▶ {name}", P["arc_d"])
        self._set_status(f"Running tool: {name}…")
        if self._mini_hud is not None:
            self._mini_hud.update_status("EXECUTING")
            self._mini_hud.update_tool(name)

    @Slot(str, str)
    def _on_tool_end(self, name: str, output: str):
        self._log_tool(f"✓ {name}", P["t1"])
        self._tool_ticker_add(name, output)
        if self._mini_hud is not None:
            self._mini_hud.update_tool(name)
        # Refresh project list when project-state tools complete
        if name in ("create_project", "switch_project", "list_projects"):
            self._refresh_projects()

    @Slot(str, str)
    def _on_need_confirm(self, tool_name: str, command: str):
        disp = command[:90] + ("…" if len(command) > 90 else "")
        self._confirm_lbl.setText(f"Execute:  {disp}")
        self._confirm_bar.show()
        QTimer.singleShot(40, self._scroll_bottom)

    def _confirm_yes(self):
        self._confirm_bar.hide()
        if self._pending_w:
            self._pending_w.confirm(True)

    def _confirm_no(self):
        self._confirm_bar.hide()
        if self._pending_w:
            self._pending_w.confirm(False)

    @Slot()
    def _on_agent_done(self):
        self._busy = False
        self._set_thinking(False)
        self._pending_w = None
        self._set_status("Ready", clear_ms=0)

    @Slot(str)
    def _on_agent_error(self, err: str):
        _play_sound("ui_error")
        self._busy = False
        self._set_thinking(False)
        self._pending_w = None
        self._add_msg("assistant", f"I encountered an error, sir. {err}")
        self._set_status("Error — see log", clear_ms=8000)

    # ─────────────────────────────────────────────────────────────────────────
    #  Projects
    # ─────────────────────────────────────────────────────────────────────────

    def _refresh_projects(self):
        self._telemetry._refresh_projects()

    def _select_project(self, name: str):
        set_active_project(name)
        self._set_badge(self._b_proj, name.upper()[:16], P["blue"])
        self._refresh_projects()
        self._add_msg("assistant", f"Active project switched to '{name}', sir.")

    def _clear_chat(self):
        for i in reversed(range(self._chat_vbox.count())):
            w = self._chat_vbox.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._history.clear()
        self._add_msg("assistant", "Chat cleared, sir.")

    def _open_palette(self):
        from PySide6.QtWidgets import QInputDialog
        items = ["System Status", "Network Scan", "List Projects", "Recent Commands", "Clear Chat"]
        item, ok = QInputDialog.getItem(self, "Command Palette", "Quick action:", items, 0, False)
        if ok and item:
            if item == "Clear Chat":
                if hasattr(self, "_clear_chat"): self._clear_chat()
            else:
                prompts = {
                    "System Status":   "What is my current system status?",
                    "Network Scan":    "Show me my network interfaces and active connections.",
                    "List Projects":   "List all my projects.",
                    "Recent Commands": "Show my most recent commands.",
                }
                self._input.setPlainText(prompts.get(item, item))
                self._on_send()

    def _new_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if ok and name.strip():
            create_project(name.strip())
            self._refresh_projects()
            self._add_msg("assistant", f"Project '{name.strip()}' created, sir.")
    def _on_theme_changed(self) -> None:
        """Called when theme or brightness changes — repaints entire UI."""
        try:
            from gui.theme import theme as _t
            self.setStyleSheet(_t.master_stylesheet())
            if self._mini_hud is not None:
                self._mini_hud.setStyleSheet(_t.master_stylesheet())
                self._mini_hud.update()
            # Polish all children so QSS picks up new values
            for child in self.findChildren(QWidget):
                child.style().unpolish(child)
                child.style().polish(child)
            self.update()
            # Write theme state for OPS graph to pick up
            import pathlib as _pl, json as _json
            try:
                _pl.Path("jarvis_ops_state.json").write_text(
                    _json.dumps({"theme": _t.name(), "brightness": _t.brightness()}))
            except Exception:
                pass
        except Exception:
            pass

    def _on_persona_btn_click(self, key: str) -> None:
        """
        Persona button clicked by operator.
        Switches: config + theme + TTS voice + orb + button states + persists + speaks.
        """
        _play_sound("ui_persona_switch")
        import config as _cfg
        _cfg.ACTIVE_PERSONA = key

        # Theme + title + orb (reuse existing handler)
        self._on_persona_switch(key)

        # TTS voice profile
        try:
            from voice.profiles import get_profile_for_persona as _gp
            import logging as _logging
            _profile = _gp(key)
            self._tts.set_profile(_profile.name)
            _logging.getLogger(__name__).info(
                f"[Persona] Switched to {key} – "
                f"profile: {_profile.name}, voice: {_profile.voice_id}"
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[Persona] TTS switch failed: {e}")

        # Persist
        _settings_store.set("active_persona", key)

        # Speak confirmation in the new voice
        _LINES = {
            "jarvis":  "JARVIS online. Systems nominal.",
            "india":   "India protocol active. Ready, sir.",
            "morgan":  "Morgan online. Standing by.",
            "ct7567":  "CT-7567 Rex. Locked and loaded.",
            "jarjar":  "Meesa JARVIS! Ohh mooie mooie — all systems okeeday!",
        }
        try:
            self._tts.speak(_LINES.get(key, "Persona switched."))
        except Exception:
            pass

    def _refresh_persona_btn_states(self, active_key: str) -> None:
        """Apply active/inactive styling to all persona buttons."""
        _COLORS = {
            "jarvis":  "#18e0c1",
            "india":   "#ffa020",
            "morgan":  "#b060ff",
            "ct7567":  "#39d353",
            "jarjar":  "#FFD700",
        }
        for key, btn in self._persona_btns.items():
            col = _COLORS.get(key, P["arc"])
            mono = _cfg.MONO
            if key == active_key:
                btn.setStyleSheet(
                    f"QPushButton{{color:{col};background:{col}15;"
                    f"border:1px solid {col}55;border-radius:4px;"
                    f"font-family:'{mono}';font-size:8px;letter-spacing:2px;"
                    f"font-weight:800;padding:0 10px;}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton{{color:{P['t3']};background:transparent;"
                    f"border:1px solid transparent;border-radius:4px;"
                    f"font-family:'{mono}';font-size:8px;letter-spacing:2px;"
                    f"padding:0 10px;}}"
                    f"QPushButton:hover{{color:{col};border-color:{col}40;"
                    f"background:{col}08;}}"
                )

    def _on_persona_switch(self, persona_key: str) -> None:
        """Update topbar title label when persona changes via tool call."""
        from tools.voice_tools import PERSONA_META
        meta = PERSONA_META.get(persona_key)
        if meta is None:
            return
        self._title_lbl.setText(meta["display"])
        self._title_lbl.setStyleSheet(
            f"color:{meta['color']};font-family:{_cfg.DISPLAY_CSS};font-size:26px;"
            f"font-weight:700;letter-spacing:7px;background:transparent;"
        )
        # Switch theme to match persona
        try:
            from gui.theme import theme as _t
            _t.set_persona(persona_key)
            _t.save()
        except Exception:
            pass
        if hasattr(self, '_orb') and self._orb is not None:
            self._orb.set_persona(meta["display"])
            _ORB_LABELS: dict[str, str] = {
                "jarvis":  "NEURAL CORE ACTIVE",
                "india":   "INDIA PROTOCOL ACTIVE",
                "morgan":  "MORGAN SYSTEM ACTIVE",
                "ct7567":  "CT-7567 ENGAGED",
                "jarjar":  "MEESA ONLINE — OKEEDAY?",
            }
            _orb_label = _ORB_LABELS.get(persona_key, f"{meta['display'].upper()} PROTOCOL ACTIVE")
            self._orb.set_state(_orb_label, "SYSTEM RECONFIGURED")
        # Refresh button active states
        if hasattr(self, '_persona_btns'):
            self._refresh_persona_btn_states(persona_key)

    def _on_voice_toggle(self, on: bool):
        _play_sound("ui_click_primary")
        self._voice_on = on
        self._mic_btn.setEnabled(on)
        if on:
            self._telemetry.set_voice_toggle_text("VOICE  ONLINE")
            self._telemetry.set_voice_status("Hold mic to speak", P["arc"])
            self._tts.speak("Voice interface online, sir. I'm listening.")
        else:
            self._telemetry.set_voice_toggle_text("ENABLE VOICE")
            self._telemetry.set_voice_status("Voice offline", P["t2"])

    def _ptt_start(self):
        if not self._stt.ready:
            QMessageBox.information(
                self, "Voice Not Available",
                "Install voice support:\n\n"
                "pip install faster-whisper sounddevice numpy\n\n"
                "Then restart JARVIS."
            )
            self._mic_btn.setChecked(False)
            return
        _play_sound("ui_mic_on")
        self._arc.set_state("listening")
        self._wave.set_state("mic")
        self._audio_meter.set_state("listening")
        self._telemetry.set_voice_status("[ REC ]  Listening...", P["arc"])
        if hasattr(self, '_orb') and self._orb is not None:
            self._orb.set_state("LISTENING", "AWAITING INPUT")
        if self._mini_hud is not None:
            self._mini_hud.update_status("LISTENING")
            self._mini_hud.set_mic_status(True)
        self._stt.listen(
            on_result=lambda t: QTimer.singleShot(0, lambda: self._on_stt_result(t)),
            on_start=None,
        )

    def _ptt_stop(self):
        pass   # STT auto-stops after RECORD_SECS

    def _on_stt_result(self, text: Optional[str]):
        self._mic_btn.setChecked(False)
        self._arc.set_state("idle")
        self._wave.set_state("idle")
        self._audio_meter.set_state("idle")
        if hasattr(self, '_orb') and self._orb is not None:
            self._orb.set_state("NEURAL CORE ACTIVE", "STANDING BY")
        if self._mini_hud is not None:
            self._mini_hud.set_mic_status(False)
            self._mini_hud.update_status("IDLE")
        if text and text.strip():
            disp = f'"{text[:32]}…"' if len(text) > 32 else f'"{text}"'
            self._telemetry.set_voice_status(disp, P["arc"])
            QTimer.singleShot(3000, lambda: self._telemetry.set_voice_status("Hold mic to speak", P["arc"]))
            # Log PTT transcript to ambient context buffer (non-blocking, non-fatal)
            if hasattr(self, '_wake_listener'):
                try:
                    self._wake_listener.push_transcript(text)
                except Exception:
                    pass
            self._submit(text)
        else:
            self._telemetry.set_voice_status("Didn't catch that — try again", P["t2"])
            self._tts.speak("I didn't catch that, sir.")
            QTimer.singleShot(3000, lambda: self._telemetry.set_voice_status("Hold mic to speak", P["arc"]))

    # ─────────────────────────────────────────────────────────────────────────
    #  Autonomous agent
    # ─────────────────────────────────────────────────────────────────────────

    def _on_auto_toggle(self, on: bool):
        import config as _acfg
        _acfg.AUTO_AGENT_ENABLED = on
        if on:
            self._auto_btn.setText("AUTO AGENT  ●  ACTIVE")
            self._think_btn.setEnabled(True)
            self._auto.start()
            self._add_msg(
                "assistant",
                "Autonomous mode engaged, sir.\n\n"
                "Shell confirmations are auto-approved. "
                "I'll execute tool calls without waiting for your click."
            )
        else:
            self._auto_btn.setText("ACTIVATE AUTO AGENT")
            self._think_btn.setEnabled(False)
            self._auto.stop()
            self._add_msg("assistant", "Autonomous mode disengaged. Confirmation gate restored.")

    @Slot(list)
    def _on_proposals(self, proposals: list):
        _play_sound("ui_finding")
        while self._prop_vbox.count() > 1:
            item = self._prop_vbox.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        for p in proposals:
            card = ProposalCard(p)
            card.approved.connect(self._approve_task)
            card.rejected.connect(self._reject_task)
            self._prop_vbox.insertWidget(0, card)

        n   = len(proposals)
        msg = f"I have {n} suggestion{'s' if n != 1 else ''} for your review, sir."
        self._add_msg("assistant", msg)
        if self._voice_on:
            self._tts.speak(msg)

    @Slot(str)
    def _approve_task(self, task_id: str):
        card = self.sender()
        if card: card.setParent(None)
        self._auto.approve(task_id)
        # Signal autonomous agent to generate next proposal immediately
        if hasattr(self._auto, 'request_next_proposal'):
            self._auto.request_next_proposal()

    @Slot(str)
    def _reject_task(self, task_id: str):
        card = self.sender()
        if card: card.setParent(None)
        self._auto.reject(task_id)
        # Signal autonomous agent to generate next proposal immediately
        if hasattr(self._auto, 'request_next_proposal'):
            self._auto.request_next_proposal()

    @staticmethod
    def _clean_ps_output(text: str) -> str:
        if not text:
            return "(no output)"
        lines = text.splitlines()
        noise = re.compile(r"^\s*(At \w+.*|[\+~\s]+$|CategoryInfo\s*:|FullyQualifiedErrorId\s*:)")
        clean = [l.rstrip() for l in lines if not noise.match(l) and l.strip()]
        result = "\n".join(clean).strip()
        return result if result else lines[0].strip()

    @Slot(str, str)
    def _on_auto_task_done(self, title: str, result: str):
        clean  = self._clean_ps_output(result)
        is_err = any(w in result for w in ("Exception", "not recognized", "cannot be found",
                                           "Missing argument", "Error"))
        prefix = "⚠ Failed" if is_err else "✓ Completed"
        self._add_msg("assistant", f"{prefix}: {title}\n\n{clean}")

    # ─────────────────────────────────────────────────────────────────────────
    #  Self-Evolution handlers
    # ─────────────────────────────────────────────────────────────────────────

    @Slot(str)
    def _on_evo_status(self, msg: str):
        self._evo_status_lbl.setText(msg)

    @Slot(str, str, str)
    def _on_evo_proposal(self, summary: str, diff_preview: str, patch_path: str):
        self._evo_approve_btn.setEnabled(True)
        self._evo_reject_btn.setEnabled(True)
        self._evo_analyze_btn.setEnabled(True)
        self._evo_status_lbl.setText("Upgrade ready — awaiting authorisation")
        self._evo_diff.setPlainText(diff_preview)
        self._pending_patch   = patch_path
        self._pending_summary = summary

        lines = [
            "I've analysed my own source code, sir, and drafted an upgrade.\n",
            f"Proposed change: {summary}\n",
            "The diff is visible in the SELF-EVOLUTION panel. "
            "Authorise when ready — I'll back up the current version first, "
            "then apply the patch and restart.",
        ]
        self._add_msg("assistant", "\n".join(lines))
        if self._voice_on:
            self._tts.speak(
                f"Upgrade drafted, sir. {summary}. "
                "Awaiting your authorisation to apply."
            )

    @Slot(str)
    def _on_evo_applied(self, backup_path: str):
        self._evo_approve_btn.setEnabled(False)
        self._evo_reject_btn.setEnabled(False)
        self._evo_status_lbl.setText("Upgrade applied — restarting…")
        self._pending_patch = None
        msg = (
            f"Upgrade applied, sir. Previous version backed up to:\n{backup_path}\n\n"
            "Restarting now to instantiate the new build."
        )
        self._add_msg("assistant", msg)
        if self._voice_on:
            self._tts.speak("Upgrade applied. Restarting now, sir.")
        QTimer.singleShot(1800, self._restart_self)

    @Slot(str)
    def _on_evo_error(self, err: str):
        self._evo_approve_btn.setEnabled(False)
        self._evo_reject_btn.setEnabled(False)
        self._evo_analyze_btn.setEnabled(True)
        self._evo_status_lbl.setText("Evolution failed — original intact")
        self._pending_patch = None
        self._add_msg("assistant",
            f"The upgrade attempt failed validation, sir. "
            f"Original source is intact.\n\nReason: {err}"
        )

    @Slot(str, str)
    def _on_evo_auto_apply(self, summary: str, patch_path: str):
        self._evo_status_lbl.setText(f"Auto-applying: {summary[:40]}…")
        self._add_msg(
            "assistant",
            f"Small upgrade detected, sir — {summary}.\n\n"
            f"Fewer than 20 lines changed. Applying automatically and restarting.",
        )
        if self._voice_on:
            self._tts.speak("Auto-applying upgrade, sir.")
        self._evo.apply(patch_path)

    def _start_evolution(self):
        self._evo_analyze_btn.setEnabled(False)
        self._evo_approve_btn.setEnabled(False)
        self._evo_reject_btn.setEnabled(False)
        self._evo_status_lbl.setText("Analysing own source code…")
        self._evo_diff.setPlainText("")
        self._pending_patch = None
        self._add_msg("assistant",
            "Initiating self-analysis, sir. I'll read my own source, "
            "identify the highest-value improvement, write and validate a patch, "
            "then present it to you for authorisation."
        )
        if self._voice_on:
            self._tts.speak("Initiating self-analysis, sir.")
        self._evo.analyse()

    def _approve_evolution(self):
        if self._pending_patch:
            self._evo_approve_btn.setEnabled(False)
            self._evo_reject_btn.setEnabled(False)
            self._evo_status_lbl.setText("Applying upgrade…")
            self._evo.apply(self._pending_patch)

    def _reject_evolution(self):
        if self._pending_patch:
            Path(self._pending_patch).unlink(missing_ok=True)
        if self._pending_summary:
            self._evo.mark_rejected(self._pending_summary)
        self._pending_patch   = None
        self._pending_summary = None
        self._evo_approve_btn.setEnabled(False)
        self._evo_reject_btn.setEnabled(False)
        self._evo_analyze_btn.setEnabled(True)
        self._evo_status_lbl.setText("Upgrade declined — standing by")
        self._evo_diff.setPlainText("")
        self._add_msg("assistant",
            "Understood, sir. Proposal discarded — "
            "I'll bring a different upgrade next cycle."
        )

    def _restart_self(self):
        import subprocess as _sp
        _sp.Popen([sys.executable, str(Path(__file__).resolve().parent.parent / "main.py")])
        QApplication.instance().quit()

    # ─────────────────────────────────────────────────────────────────────────
    #  Resource monitor
    # ─────────────────────────────────────────────────────────────────────────

    def _open_resource_monitor(self) -> None:
        """Open the floating resource monitor window (Ctrl+Shift+R)."""
        if not _HAS_RESOURCE_MONITOR:
            return
        if self._resource_monitor is None:
            try:
                self._resource_monitor = _ResourceMonitorWindow(parent=None)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "[JARVIS] Resource monitor init failed: %s", exc)
                return
        try:
            from gui.theme import theme
            self._resource_monitor.setStyleSheet(theme.master_stylesheet())
        except Exception:
            pass
        self._resource_monitor.show()
        self._resource_monitor.raise_()
        self._resource_monitor.activateWindow()

    # ─────────────────────────────────────────────────────────────────────────
    #  Window lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        try:
            geo = self.saveGeometry()
            import storage.settings_store as _ss
            _ss.set("window.geometry", geo.toBase64().data().decode())
        except Exception:
            pass
        super().closeEvent(event)


    def _build_shortcuts(self):
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._clear_chat if hasattr(self, "_clear_chat") else lambda: None)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._on_send)
        try:
            from PySide6.QtWidgets import QSystemTrayIcon, QMenu
            tray = QSystemTrayIcon(self)
            tray.setToolTip("J.A.R.V.I.S.")
            menu = QMenu()
            menu.addAction("Show", self.show)
            menu.addAction("Quit", QApplication.instance().quit)
            tray.setContextMenu(menu)
            tray.activated.connect(lambda r: self.show() if r == QSystemTrayIcon.Trigger else None)
            tray.show()
            self._tray = tray
        except Exception:
            pass

