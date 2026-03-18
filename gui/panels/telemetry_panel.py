"""
gui/panels/telemetry_panel.py — Left-sidebar TelemetryPanel.

Self-contained widget: owns its stats timer, project list, quick actions,
and voice toggle UI.  Communicates upward to JARVIS only via Qt Signals.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea,
)

from config import P
import config as _cfg
from storage.db import list_projects
try:
    from gui.widgets.voice_button import VoiceButton as _VoiceButton
except Exception:
    _VoiceButton = None
try:
    from gui.widgets.panel_header import PanelHeader as _PanelHeader
except Exception:
    _PanelHeader = None

log = logging.getLogger(__name__)


class TelemetryPanel(QWidget):
    """Left sidebar — projects, quick actions, system stats, voice toggle."""

    # ── Signals ───────────────────────────────────────────────────────────────
    submit_requested    = Signal(str)   # quick-action button clicked
    new_project_clicked = Signal()      # "New Project" button clicked
    voice_toggled       = Signal(bool)  # voice toggle button toggled

    # ─────────────────────────────────────────────────────────────────────────

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(218)
        self.setStyleSheet(
            f"background:{P['surface']};border-right:1px solid {P['b0']};"
        )

        # Outer layout: just holds the scroll area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll area wraps all content so nothing clips on small windows
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;}"
        )
        outer.addWidget(self._scroll)

        # Inner container for all content
        _inner = QWidget()
        _inner.setStyleSheet("background:transparent;")
        self._scroll.setWidget(_inner)

        v = QVBoxLayout(_inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── Projects ──────────────────────────────────────────────────────────
        if _PanelHeader is not None:
            _ph = _PanelHeader("PROJECTS", action_icon="＋", action_tooltip="New project")
            _ph.action_clicked.connect(self.new_project_clicked.emit)
            v.addWidget(_ph)
        else:
            v.addWidget(self._sec_hdr("PROJECTS"))

        self._proj_box = QWidget()
        self._proj_lay = QVBoxLayout(self._proj_box)
        self._proj_lay.setContentsMargins(10, 4, 10, 4)
        self._proj_lay.setSpacing(2)
        v.addWidget(self._proj_box)

        if _PanelHeader is None:
            add_p = self._sbtn("＋  New Project", P["arc_d"])
            add_p.clicked.connect(self.new_project_clicked)
            v.addWidget(add_p)

        # ── Quick Actions ─────────────────────────────────────────────────────
        if _PanelHeader is not None:
            v.addWidget(_PanelHeader("QUICK ACTIONS"))
        else:
            v.addWidget(self._sec_hdr("QUICK ACTIONS"))
        for label, prompt in [
            ("▶  System Status",    "system_status"),
            ("▶  Network Scan",     "run_subfinder on active program"),
            ("▶  List Programs",    "list_programs"),
            ("▶  Recent Commands",  "recall recent commands"),
            ("▶  Recon Checklist",  "suggest_next_action"),
            ("▶  CVE Quick Hits",   "intel_correlate_now"),
            ("▶  Open Terminal",    "open_app terminal"),
            ("▶  Open VS Code",     "open_app vscode"),
            ("▶  Open Wireshark",   "open_app wireshark"),
        ]:
            btn = self._sbtn(label)
            btn.clicked.connect(lambda _, p=prompt: self.submit_requested.emit(p))
            v.addWidget(btn)

        # ── System Stats ──────────────────────────────────────────────────────
        stats_hdr_btn = QPushButton("SYSTEM STATS  ▾")
        stats_hdr_btn.setCheckable(True)
        stats_hdr_btn.setChecked(True)
        stats_hdr_btn.setFixedHeight(28)
        stats_hdr_btn.setStyleSheet(
            f"QPushButton{{color:{P['t3']};font-family:{_cfg.DISPLAY_CSS};font-size:9px;"
            f"letter-spacing:3px;font-weight:600;"
            f"padding-left:12px;border-top:1px solid {P['b0']};"
            f"border-bottom:1px solid {P['b0']};background:{P['void']};"
            f"text-align:left;border-radius:0;}}"
            f"QPushButton:hover{{color:{P['t1']};}}"
        )
        v.addWidget(stats_hdr_btn)

        self._stats_body = QWidget()
        sb = QVBoxLayout(self._stats_body)
        sb.setContentsMargins(10, 4, 10, 6)
        sb.setSpacing(2)

        cpu_row,  self._cpu_bar,  self._cpu_val  = self._mk_stat_row("CPU",  P["arc"])
        ram_row,  self._ram_bar,  self._ram_val  = self._mk_stat_row("RAM",  P["blue"])
        disk_row, self._disk_bar, self._disk_val = self._mk_stat_row("DISK", P["amber"])
        sb.addWidget(cpu_row)
        sb.addWidget(ram_row)
        sb.addWidget(disk_row)

        self._net_lbl = QLabel("NET  ↑ —  ↓ —")
        self._net_lbl.setWordWrap(True)
        self._net_lbl.setMaximumWidth(260)
        self._net_lbl.setStyleSheet(
            f"color:{P['t2']};font-family:'{_cfg.MONO}';font-size:9px;"
            f"padding:3px 10px 1px 10px;background:transparent;"
        )
        self._proc_lbl = QLabel("—")
        self._proc_lbl.setWordWrap(True)
        self._proc_lbl.setMaximumWidth(260)
        self._proc_lbl.setStyleSheet(
            f"color:{P['t2']};font-family:'{_cfg.MONO}';font-size:9px;"
            f"padding:1px 10px 4px 10px;background:transparent;"
        )

        # Memory record count row
        _mem_row = QWidget()
        _mem_h = QHBoxLayout(_mem_row)
        _mem_h.setContentsMargins(10, 2, 10, 2)
        _mem_h.setSpacing(0)
        _mem_lbl = QLabel("MEMORY")
        _mem_lbl.setStyleSheet(
            f"color:{P['t2']};font-family:{_cfg.DISPLAY_CSS};font-size:10px;"
            f"font-weight:600;letter-spacing:2px;background:transparent;"
        )
        self._mem_val = QLabel("—")
        self._mem_val.setStyleSheet(
            f"color:{P['arc']};font-family:'{_cfg.MONO}';font-size:10px;background:transparent;"
        )
        self._mem_val.setAlignment(Qt.AlignRight)
        _mem_h.addWidget(_mem_lbl)
        _mem_h.addStretch()
        _mem_h.addWidget(self._mem_val)

        sb.addWidget(self._net_lbl)
        sb.addWidget(self._proc_lbl)
        sb.addWidget(_mem_row)
        v.addWidget(self._stats_body)
        stats_hdr_btn.toggled.connect(self._stats_body.setVisible)

        self._net_prev = (0, 0)
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start(5000)
        QTimer.singleShot(1500, self._update_stats)

        self._mem_timer = QTimer(self)
        self._mem_timer.timeout.connect(self._update_mem_stats)
        self._mem_timer.start(30000)
        QTimer.singleShot(3000, self._update_mem_stats)

        v.addStretch()

        # ── Voice Interface ───────────────────────────────────────────────────
        v.addWidget(self._sec_hdr("VOICE INTERFACE"))

        if _VoiceButton is not None:
            self._voice_toggle = _VoiceButton()
        else:
            self._voice_toggle = QPushButton("ENABLE VOICE")
            self._voice_toggle.setCheckable(True)
            self._voice_toggle.setCursor(QCursor(Qt.PointingHandCursor))
            self._voice_toggle.setStyleSheet(f"""
                QPushButton {{
                    background:transparent; color:{P['t2']};
                    border:1px solid {P['b1']}; border-radius:4px;
                    font-family:'{_cfg.MONO}'; font-size:10px; letter-spacing:2px;
                    padding:7px; margin:4px 12px 4px 12px;
                }}
                QPushButton:checked {{
                    color:{P['arc']}; border-color:{P['arc_d']};
                    background:{P['arc_g']};
                }}
                QPushButton:hover:!checked {{
                    border-color:{P['b2']}; color:{P['t1']};
                }}
            """)
        self._voice_toggle.toggled.connect(self.voice_toggled)
        v.addWidget(self._voice_toggle)

        self._voice_status = QLabel("Voice offline")
        self._voice_status.setAlignment(Qt.AlignCenter)
        self._voice_status.setStyleSheet(
            f"color:{P['t2']};font-size:10px;font-family:'{_cfg.MONO}';padding-bottom:10px;"
        )
        v.addWidget(self._voice_status)

        # ── Populate projects on init ─────────────────────────────────────────
        self._refresh_projects()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sec_hdr(self, text: str) -> QLabel:
        w = QLabel(text)
        w.setFixedHeight(28)
        w.setStyleSheet(
            f"color:{P['arc_d']};font-family:{_cfg.DISPLAY_CSS};font-size:9px;"
            f"letter-spacing:4px;font-weight:700;"
            f"padding-left:12px;padding-top:2px;"
            f"border-top:1px solid {P['b0']};"
            f"border-bottom:1px solid {P['b0']};background:{P['void']};"
        )
        return w

    def _sbtn(self, text: str, col: str = None) -> QPushButton:
        btn = QPushButton(text)
        c = col or P["arc"]
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setStyleSheet(f"""
            QPushButton {{
                background:{P['void']}; color:{c};
                border:none; border-bottom:1px solid {P['b0']};
                text-align:left;
                padding:6px 14px;
                font-family:'{_cfg.MONO}'; font-size:10px;
            }}
            QPushButton:hover {{
                background:{P['arc']}14; color:{P['arc']};
            }}
        """)
        return btn

    def _mk_stat_row(self, label: str, color: str):
        row = QWidget()
        v   = QVBoxLayout(row)
        v.setContentsMargins(10, 2, 10, 2)
        v.setSpacing(2)
        header = QHBoxLayout()
        header.setSpacing(0)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color:{P['t2']};font-family:{_cfg.DISPLAY_CSS};font-size:10px;"
            f"font-weight:600;letter-spacing:2px;background:transparent;"
        )
        val = QLabel("—")
        val.setStyleSheet(
            f"color:{color};font-family:'{_cfg.MONO}';font-size:10px;background:transparent;"
        )
        val.setAlignment(Qt.AlignRight)
        header.addWidget(lbl)
        header.addStretch()
        header.addWidget(val)
        bar = QProgressBar()
        bar.setFixedHeight(3)
        bar.setMaximum(100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar{{background:{P['b0']};border-radius:1px;border:none;}}"
            f"QProgressBar::chunk{{background:{color};border-radius:1px;}}"
        )
        v.addLayout(header)
        v.addWidget(bar)
        return row, bar, val

    # ── Stats updater ─────────────────────────────────────────────────────────

    @Slot()
    def _update_stats(self):
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            self._cpu_bar.setValue(int(cpu))
            self._cpu_val.setText(f"{cpu:.0f}%")

            mem = psutil.virtual_memory()
            self._ram_bar.setValue(int(mem.percent))
            self._ram_val.setText(f"{mem.percent:.0f}%  {mem.used//1024**3}G")

            disk = psutil.disk_usage("/")
            self._disk_bar.setValue(int(disk.percent))
            self._disk_val.setText(f"{disk.percent:.0f}%")

            net = psutil.net_io_counters()
            tx  = net.bytes_sent - self._net_prev[0]
            rx  = net.bytes_recv - self._net_prev[1]
            self._net_prev = (net.bytes_sent, net.bytes_recv)
            tx_s = f"{tx/1024:.0f}K" if tx < 1024*1024 else f"{tx/1024/1024:.1f}M"
            rx_s = f"{rx/1024:.0f}K" if rx < 1024*1024 else f"{rx/1024/1024:.1f}M"
            self._net_lbl.setText(f"NET  ↑{tx_s}  ↓{rx_s}")

            procs = sorted(
                psutil.process_iter(["name", "cpu_percent"]),
                key=lambda x: x.info.get("cpu_percent") or 0,
                reverse=True,
            )[:3]
            lines = "  |  ".join(
                f"{(p.info.get('name') or '?')[:9]}  {p.info.get('cpu_percent', 0):.0f}%"
                for p in procs
            )
            self._proc_lbl.setText(lines or "—")
        except Exception:
            pass

    # ── Memory stats ──────────────────────────────────────────────────────────

    @Slot()
    def _update_mem_stats(self):
        try:
            from memory.manager import MemoryManager
            _stats = MemoryManager().get_stats()
            total  = _stats.get("total_active", 0)
            self._mem_val.setText(f"{total} records")
        except Exception:
            self._mem_val.setText("—")

    # ── Projects ──────────────────────────────────────────────────────────────

    def _refresh_projects(self):
        while self._proj_lay.count():
            item = self._proj_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for p in list_projects():
            name   = p["name"]
            active = bool(p["active"])
            marker = "●  " if active else "○  "
            col    = P["arc"] if active else P["t1"]
            bg     = f"{P['arc']}0e" if active else "transparent"
            bl     = f"2px solid {P['arc']}" if active else "2px solid transparent"

            btn = QPushButton(marker + name)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:{bg}; color:{col};
                    border:none; border-left:{bl};
                    text-align:left; padding:7px 12px;
                    font-family:'{_cfg.MONO}'; font-size:11px;
                }}
                QPushButton:hover {{
                    background:{P['arc']}0a; color:{P['arc']};
                }}
            """)
            btn.clicked.connect(
                lambda _, n=name: self.submit_requested.emit(f"Switch to project {n}")
            )
            self._proj_lay.addWidget(btn)

    # ── Public API called by JARVIS ───────────────────────────────────────────

    def set_voice_status(self, text: str, color: str = None):
        """Update the voice status label text and optionally its color."""
        self._voice_status.setText(text)
        if color is not None:
            self._voice_status.setStyleSheet(
                f"color:{color};font-size:10px;"
                f"font-family:'{_cfg.MONO}';padding-bottom:10px;"
            )

    def set_voice_toggle_text(self, text: str) -> None:
        """Update the voice toggle button label (called by JARVIS after toggling)."""
        self._voice_toggle.setText(text)
        if _VoiceButton is not None and isinstance(self._voice_toggle, _VoiceButton):
            state = 'online' if 'ONLINE' in text else 'offline'
            self._voice_toggle.set_state(state)
