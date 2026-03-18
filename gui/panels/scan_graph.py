from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, QThread, QObject
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton,
)

from config import P
import config as _cfg
import logging

log = logging.getLogger(__name__)

_SEV_COLOR = {
    "critical": P["red"],
    "high":     P["amber"],
    "medium":   P["blue"],
    "info":     P["t3"],
    "low":      P["t3"],
}


class _FetchWorker(QObject):
    done = Signal(list, list)  # targets: list[str], findings: list[tuple[str,str,str]]

    def run(self):
        targets: list[str] = []
        findings: list[tuple[str, str, str]] = []
        try:
            from storage.db import get_db
            with get_db() as conn:
                cur = conn.execute(
                    "SELECT DISTINCT target FROM scan_targets ORDER BY target LIMIT 100"
                )
                targets = [row[0] for row in cur.fetchall()]
        except Exception as exc:
            log.warning("scan_graph: targets query failed: %s", exc)

        try:
            from storage.db import get_db
            with get_db() as conn:
                cur = conn.execute(
                    "SELECT target, severity, title FROM findings "
                    "ORDER BY severity DESC LIMIT 200"
                )
                findings = [(row[0], row[1], row[2]) for row in cur.fetchall()]
        except Exception as exc:
            log.warning("scan_graph: findings query failed: %s", exc)

        self.done.emit(targets, findings)


class ScanGraphPanel(QWidget):
    """
    Live scan results tree: targets → subdomains → findings.
    Polls DB on refresh(). Never blocks the UI thread.
    """

    target_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _FetchWorker | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header bar
        hdr = QWidget()
        hdr.setFixedHeight(28)
        hdr.setStyleSheet(f"background:{P['void']};")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(8, 0, 4, 0)
        hdr_lay.setSpacing(0)

        lbl = QLabel("SCAN INTELLIGENCE")
        lbl.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:9px;"
            f"font-weight:700;letter-spacing:2px;background:transparent;"
        )

        self._refresh_btn = QPushButton("⟳")
        self._refresh_btn.setFixedSize(24, 24)
        self._refresh_btn.setStyleSheet(
            f"QPushButton{{color:{P['arc']};background:transparent;border:none;"
            f"font-size:14px;padding:0;}}"
            f"QPushButton:hover{{color:{P['arc_m']};}}"
        )
        self._refresh_btn.clicked.connect(self.refresh)

        hdr_lay.addWidget(lbl)
        hdr_lay.addStretch()
        hdr_lay.addWidget(self._refresh_btn)
        root_layout.addWidget(hdr)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setColumnCount(1)
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setAlternatingRowColors(False)
        self._tree.setStyleSheet(
            f"QTreeWidget{{"
            f"  background:{P['void']};border:1px solid {P['b0']};"
            f"  color:{P['t1']};font-family:'{_cfg.MONO}';font-size:9px;"
            f"  outline:none;"
            f"}}"
            f"QTreeWidget::item{{padding:2px 0;}}"
            f"QTreeWidget::item:selected{{"
            f"  background:{P['b1']};color:{P['arc']};"
            f"}}"
            f"QTreeWidget::item:hover{{"
            f"  background:{P['b0']};"
            f"}}"
            f"QTreeWidget::branch{{background:{P['void']};}}"
        )
        font = QFont(_cfg.MONO, 9)
        self._tree.setFont(font)
        self._tree.itemClicked.connect(self._on_item_clicked)
        root_layout.addWidget(self._tree, 1)

        # Status label
        self._status = QLabel("Not loaded")
        self._status.setFixedHeight(18)
        self._status.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;"
            f"background:{P['void']};padding:0 8px;"
        )
        root_layout.addWidget(self._status)

        # Auto-refresh timer
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self.refresh)
        self._auto_timer.start(30_000)

        # First load
        QTimer.singleShot(500, self.refresh)

    def refresh(self) -> None:
        if self._thread and self._thread.isRunning():
            return

        self._thread = QThread(self)
        self._worker = _FetchWorker()
        self._worker.moveToThread(self._thread)
        self._worker.done.connect(self._on_data)
        self._thread.started.connect(self._worker.run)
        self._thread.start()
        self._status.setText("Refreshing…")

    def _on_data(self, targets: list[str], findings: list[tuple[str, str, str]]) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()

        self._tree.clear()

        if not targets:
            placeholder = QTreeWidgetItem(
                ["No scan targets. Add targets with: save_target <domain>"]
            )
            placeholder.setForeground(0, QColor(P["t3"]))
            placeholder.setFont(0, QFont(_cfg.MONO, 9))
            self._tree.addTopLevelItem(placeholder)
            self._status.setText("No targets in DB")
            return

        # Group findings by target
        findings_map: dict[str, list[tuple[str, str]]] = {}
        for f_target, f_sev, f_title in findings:
            findings_map.setdefault(f_target, []).append((f_sev, f_title))

        for target in targets:
            top = QTreeWidgetItem([target])
            top.setForeground(0, QColor(P["arc"]))
            top.setFont(0, QFont(_cfg.MONO, 9))
            top.setData(0, Qt.UserRole, target)

            for sev, title in findings_map.get(target, []):
                sev_lower = (sev or "info").lower()
                color = _SEV_COLOR.get(sev_lower, P["t3"])
                prefix = {
                    "critical": "!! ",
                    "high":     "!  ",
                    "medium":   "·  ",
                }.get(sev_lower, "   ")
                child = QTreeWidgetItem([f"{prefix}{title}"])
                child.setForeground(0, QColor(color))
                child.setFont(0, QFont(_cfg.MONO, 9))
                child.setData(0, Qt.UserRole, target)
                top.addChild(child)

            self._tree.addTopLevelItem(top)
            top.setExpanded(True)

        ts = datetime.now().strftime("%H:%M:%S")
        self._status.setText(
            f"Updated {ts} — {len(targets)} targets, "
            f"{sum(len(v) for v in findings_map.values())} findings"
        )

    def _on_item_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        target = item.data(0, Qt.UserRole)
        if target:
            self.target_selected.emit(str(target))
