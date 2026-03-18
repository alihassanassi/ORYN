"""
gui/panels/memory_panel.py — MemoryPanel: real-time memory bank viewer.

Displays JARVIS memory records grouped by layer with search, filter tabs,
per-card PIN/FORGET actions, and auto-refresh every 10 seconds.

Self-contained: no imports from agents/ or tools/.
Gracefully degrades if the memory subsystem is unavailable.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from config import P
import config as _cfg

log = logging.getLogger(__name__)

# ── Optional memory import ────────────────────────────────────────────────────
try:
    from memory.manager import MemoryManager as _MemoryManager
    _MEMORY_OK = True
except Exception:
    _MemoryManager = None
    _MEMORY_OK = False

# ── Layer definitions ─────────────────────────────────────────────────────────
_ALL_LAYERS = ["semantic", "preference", "project", "episodic", "system", "working"]

_LAYER_COLORS: dict[str, str] = {
    "semantic":   P["arc"],
    "preference": P["purple"],
    "project":    P["blue"],
    "episodic":   P["amber"],
    "system":     P["t2"],
    "working":    P["green"],
}

_LAYER_LABELS: dict[str, str] = {
    "semantic":   "SEM",
    "preference": "PREF",
    "project":    "PROJ",
    "episodic":   "EPI",
    "system":     "SYS",
    "working":    "WORK",
}


def _conf_bar_html(confidence: float) -> str:
    """Return an inline HTML confidence bar."""
    val = max(0.0, min(1.0, float(confidence or 0.0)))
    if val <= 0.4:
        color = P["red"]
    elif val <= 0.7:
        color = P["amber"]
    else:
        color = P["arc"]

    filled = int(val * 5)   # 0–5 blocks
    empty  = 5 - filled
    bar    = "█" * filled + "░" * empty
    pct    = f"{val:.1f}"
    return (
        f'<span style="color:{color};font-family:monospace;">{bar}</span>'
        f'&nbsp;<span style="color:{color};">{pct}</span>'
    )


class MemoryPanel(QWidget):
    """
    Full-height memory bank panel.

    Tab bar  → filter by layer (ALL / SEMANTIC / PREFERENCE / PROJECT / EPISODIC / SYSTEM)
    Search   → substring match on key + value
    Card list → scrollable list of memory records with PIN / FORGET buttons
    Header   → total count + layer breakdown + REFRESH button
    """

    REFRESH_INTERVAL_MS = 10_000   # 10 seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{P['base']};")

        self._current_layer: str | None = None   # None = ALL

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header_bar())
        root.addWidget(self._build_filter_bar())
        root.addWidget(self._build_search_bar())
        root.addWidget(self._build_list(), 1)

        if not _MEMORY_OK:
            self._show_placeholder()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(self.REFRESH_INTERVAL_MS)

        QTimer.singleShot(500, self.refresh)

    # ── Layout builders ───────────────────────────────────────────────────────

    def _build_header_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet(
            f"background:{P['surface']};"
            f"border-bottom:1px solid {P['b0']};"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(8)

        title = QLabel("MEMORY BANK")
        title.setStyleSheet(
            f"color:{P['t3']};font-family:{_cfg.DISPLAY_CSS};"
            f"font-size:9px;letter-spacing:3px;font-weight:600;"
            f"background:transparent;"
        )

        self._count_lbl = QLabel("— records")
        self._count_lbl.setStyleSheet(
            f"color:{P['arc']};font-family:'{_cfg.MONO}';"
            f"font-size:9px;background:transparent;"
        )

        refresh_btn = QPushButton("REFRESH")
        refresh_btn.setFixedHeight(22)
        refresh_btn.setCursor(QCursor(Qt.PointingHandCursor))
        refresh_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{P['t3']};"
            f"border:1px solid {P['b1']};border-radius:3px;"
            f"font-family:{_cfg.DISPLAY_CSS};font-size:8px;letter-spacing:2px;"
            f"padding:0 8px;}}"
            f"QPushButton:hover{{color:{P['arc']};border-color:{P['arc_d']};}}"
        )
        refresh_btn.clicked.connect(self.refresh)

        row.addWidget(title)
        row.addStretch()
        row.addWidget(self._count_lbl)
        row.addWidget(refresh_btn)
        return bar

    def _build_filter_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(32)
        bar.setStyleSheet(
            f"background:{P['void']};"
            f"border-bottom:1px solid {P['b0']};"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 0, 8, 0)
        row.setSpacing(0)

        self._filter_btns: dict[str | None, QPushButton] = {}

        tabs = [("ALL", None)] + [(lbl.upper(), lbl) for lbl in _ALL_LAYERS]
        for label, layer_val in tabs:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(self._tab_style(layer_val is None))  # ALL selected initially
            btn.clicked.connect(lambda _, lv=layer_val: self._on_filter_tab(lv))
            row.addWidget(btn)
            self._filter_btns[layer_val] = btn

        row.addStretch()
        return bar

    def _build_search_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet(
            f"background:{P['void']};"
            f"border-bottom:1px solid {P['b0']};"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 4, 12, 4)
        row.setSpacing(6)

        icon = QLabel("⌕")
        icon.setStyleSheet(
            f"color:{P['t3']};font-size:14px;background:transparent;"
        )

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search memories…")
        self._search_box.setStyleSheet(
            f"QLineEdit{{background:{P['input']};color:{P['t1']};"
            f"border:1px solid {P['b1']};border-radius:3px;"
            f"font-family:'{_cfg.MONO}';font-size:10px;padding:2px 6px;}}"
            f"QLineEdit:focus{{border-color:{P['arc_d']};}}"
        )
        self._search_box.textChanged.connect(self._on_search_changed)

        row.addWidget(icon)
        row.addWidget(self._search_box, 1)
        return bar

    def _build_list(self) -> QScrollArea:
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{P['base']};}}"
        )

        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet(f"background:{P['base']};")
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(12, 10, 12, 10)
        self._cards_layout.setSpacing(6)
        self._cards_layout.addStretch()

        self._scroll.setWidget(self._cards_widget)
        return self._scroll

    # ── Refresh logic ─────────────────────────────────────────────────────────

    @Slot()
    def refresh(self) -> None:
        """Clear and rebuild all cards from the current filter/search state."""
        search_text = self._search_box.text().strip() if hasattr(self, '_search_box') else ""
        self._rebuild_cards(self._current_layer, search_text)

    def _rebuild_cards(self, layer_filter: str | None, search_text: str) -> None:
        # Remove existing cards (keep the trailing stretch)
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not _MEMORY_OK:
            self._show_placeholder()
            return

        records = self._load_records(layer_filter, search_text)

        if not records:
            placeholder = QLabel("No memory records found.")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(
                f"color:{P['t3']};font-family:'{_cfg.MONO}';"
                f"font-size:10px;padding:24px;background:transparent;"
            )
            self._cards_layout.insertWidget(0, placeholder)
            self._update_count_label(0)
            return

        for i, rec in enumerate(records):
            card = self._build_card(rec)
            self._cards_layout.insertWidget(i, card)

        self._update_count_label(len(records))

    def _load_records(
        self,
        layer_filter: str | None,
        search_text: str,
    ) -> list[dict]:
        """Query MemoryManager and return a filtered list of record dicts."""
        try:
            mm = _MemoryManager()
            records = mm.inspect(layer=layer_filter, limit=200)
            if search_text:
                lo = search_text.lower()
                records = [
                    r for r in records
                    if lo in (r.get("key") or "").lower()
                    or lo in (r.get("value") or "").lower()
                ]
            return records
        except Exception as exc:
            log.debug("[MemoryPanel] _load_records error: %s", exc)
            return []

    def _update_count_label(self, visible: int) -> None:
        try:
            mm = _MemoryManager()
            stats = mm.get_stats()
            total = stats.get("total_active", visible)
            parts = []
            for lyr in _ALL_LAYERS:
                n = stats.get(f"layer.{lyr}", 0)
                if n:
                    col = _LAYER_COLORS.get(lyr, P["t2"])
                    parts.append(
                        f'<span style="color:{col};">{_LAYER_LABELS.get(lyr, lyr)}:{n}</span>'
                    )
            breakdown = "  ".join(parts)
            self._count_lbl.setText(
                f'<span style="color:{P["arc"]};">{total} records</span>'
                + (f"  {breakdown}" if breakdown else "")
            )
            self._count_lbl.setTextFormat(Qt.RichText)
        except Exception:
            self._count_lbl.setText(f"{visible} records")

    # ── Card builder ──────────────────────────────────────────────────────────

    def _build_card(self, rec: dict) -> QFrame:
        mem_id     = rec.get("id")
        layer      = rec.get("layer", "")
        category   = rec.get("category", "")
        key        = rec.get("key", "")
        value      = rec.get("value", "")
        confidence = float(rec.get("confidence") or 0.0)
        source     = rec.get("source", "")
        pinned     = bool(rec.get("pinned"))
        created_at = (rec.get("created_at") or "")[:10]

        layer_color = _LAYER_COLORS.get(layer, P["t2"])
        layer_badge = _LAYER_LABELS.get(layer, layer.upper()[:4])

        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet(
            f"QFrame{{background:{P['card']};border:1px solid {P['b1']};"
            f"border-radius:5px;}}"
            f"QFrame:hover{{border-color:{P['b2']};}}"
        )
        card_v = QVBoxLayout(card)
        card_v.setContentsMargins(10, 8, 10, 8)
        card_v.setSpacing(4)

        # ── Row 1: badge + key ────────────────────────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        badge = QLabel(layer_badge)
        badge.setFixedWidth(38)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background:{layer_color}22;color:{layer_color};"
            f"border:1px solid {layer_color}55;border-radius:3px;"
            f"font-family:{_cfg.DISPLAY_CSS};font-size:8px;"
            f"letter-spacing:1px;font-weight:700;padding:1px 0;"
        )

        cat_lbl = QLabel(category)
        cat_lbl.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;"
            f"background:transparent;"
        )

        key_lbl = QLabel(key)
        key_lbl.setStyleSheet(
            f"color:{P['t1']};font-family:'{_cfg.MONO}';font-size:10px;"
            f"font-weight:600;background:transparent;"
        )
        key_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        if pinned:
            pin_icon = QLabel("📌")
            pin_icon.setStyleSheet("background:transparent;font-size:10px;")
        else:
            pin_icon = None

        top_row.addWidget(badge)
        top_row.addWidget(cat_lbl)
        top_row.addWidget(key_lbl, 1)
        if pin_icon:
            top_row.addWidget(pin_icon)
        card_v.addLayout(top_row)

        # ── Row 2: value ──────────────────────────────────────────────────────
        val_display = value[:160] + ("…" if len(value) > 160 else "")
        val_lbl = QLabel(f'"{val_display}"')
        val_lbl.setWordWrap(True)
        val_lbl.setStyleSheet(
            f"color:{P['t0']};font-family:'{_cfg.MONO}';font-size:10px;"
            f"background:transparent;padding-left:46px;"
        )
        card_v.addWidget(val_lbl)

        # ── Row 3: confidence bar + source + date + actions ───────────────────
        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)

        conf_lbl = QLabel()
        conf_lbl.setText(f'conf {_conf_bar_html(confidence)}')
        conf_lbl.setTextFormat(Qt.RichText)
        conf_lbl.setStyleSheet(
            f"font-family:'{_cfg.MONO}';font-size:9px;background:transparent;"
        )

        src_lbl = QLabel(f"source: {source}  ·  {created_at}")
        src_lbl.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';font-size:8px;"
            f"background:transparent;"
        )

        meta_row.addWidget(conf_lbl)
        meta_row.addWidget(src_lbl, 1)

        # Action buttons
        pin_btn  = self._action_btn("PIN",    P["arc"])
        fgt_btn  = self._action_btn("FORGET", P["red"])
        copy_btn = self._action_btn("COPY",   P["t2"])

        if mem_id is not None:
            pin_btn.clicked.connect(lambda _, mid=mem_id: self._on_pin(mid))
            fgt_btn.clicked.connect(lambda _, mid=mem_id: self._on_forget(mid))
        copy_btn.clicked.connect(lambda _, v=value: self._on_copy(v))

        meta_row.addWidget(copy_btn)
        meta_row.addWidget(pin_btn)
        meta_row.addWidget(fgt_btn)
        card_v.addLayout(meta_row)

        return card

    def _action_btn(self, label: str, color: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(18)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{color};"
            f"border:1px solid {color}44;border-radius:2px;"
            f"font-family:{_cfg.DISPLAY_CSS};font-size:7px;letter-spacing:1px;"
            f"padding:0 6px;}}"
            f"QPushButton:hover{{background:{color}22;border-color:{color};}}"
        )
        return btn

    # ── Slot handlers ─────────────────────────────────────────────────────────

    @Slot(int)
    def _on_pin(self, memory_id: int) -> None:
        try:
            mm = _MemoryManager()
            mm.pin(memory_id)
        except Exception as exc:
            log.debug("[MemoryPanel] pin error: %s", exc)
        self.refresh()

    @Slot(int)
    def _on_forget(self, memory_id: int) -> None:
        try:
            mm = _MemoryManager()
            mm.forget(memory_id)
        except Exception as exc:
            log.debug("[MemoryPanel] forget error: %s", exc)
        self.refresh()

    @Slot(str)
    def _on_copy(self, value: str) -> None:
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(value)
        except Exception:
            pass

    @Slot(object)
    def _on_filter_tab(self, layer: str | None) -> None:
        self._current_layer = layer
        # Update button styles
        for lv, btn in self._filter_btns.items():
            btn.setStyleSheet(self._tab_style(lv == layer))
            btn.setChecked(lv == layer)
        self.refresh()

    @Slot(str)
    def _on_search_changed(self, _text: str) -> None:
        self.refresh()

    # ── Placeholder (memory unavailable) ─────────────────────────────────────

    def _show_placeholder(self) -> None:
        ph = QLabel("Memory subsystem unavailable")
        ph.setAlignment(Qt.AlignCenter)
        ph.setStyleSheet(
            f"color:{P['t3']};font-family:'{_cfg.MONO}';"
            f"font-size:10px;padding:32px;background:transparent;"
        )
        self._cards_layout.insertWidget(0, ph)

    # ── Style helper ──────────────────────────────────────────────────────────

    @staticmethod
    def _tab_style(active: bool) -> str:
        if active:
            return (
                f"QPushButton{{background:{P['arc']}14;color:{P['arc']};"
                f"border:none;border-bottom:2px solid {P['arc']};"
                f"font-family:{_cfg.DISPLAY_CSS};font-size:8px;letter-spacing:2px;"
                f"font-weight:700;padding:0 10px;border-radius:0;}}"
            )
        return (
            f"QPushButton{{background:transparent;color:{P['t3']};"
            f"border:none;border-bottom:2px solid transparent;"
            f"font-family:{_cfg.DISPLAY_CSS};font-size:8px;letter-spacing:2px;"
            f"font-weight:600;padding:0 10px;border-radius:0;}}"
            f"QPushButton:hover{{color:{P['t1']};}}"
        )
