"""
gui/theme.py — JARVIS Iron Circuit global theme system.

Single source of truth for:
  - All 10 named color themes
  - Current active theme + brightness
  - Persona → theme mapping
  - Stylesheet generation
  - Change notification via callbacks

Usage anywhere in GUI:
    from gui.theme import theme
    accent_color = theme.accent()
    theme.set_theme('EMBER')
    theme.set_brightness(0.85)
    theme.add_change_listener(my_widget.on_theme_changed)

No Qt imports at module level — safe to import from any layer.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable


# ── Theme definitions ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ThemeDef:
    name:    str
    accent:  str   # primary interactive color
    warm:    str   # warnings, mic, hot nodes
    cool:    str   # info, user chat bubbles
    bg1:     str   # darkest background
    bg2:     str   # panel / topbar / bottombar
    bg3:     str   # inputs / inactive areas
    bg4:     str   # bars / tracks / disabled


THEMES: dict[str, ThemeDef] = {
    "CIRCUIT":   ThemeDef("CIRCUIT",   "#00d4b1", "#ff6b35", "#1a9fff", "#060b10", "#0a1018", "#0d1520", "#111e2a"),
    "EMBER":     ThemeDef("EMBER",     "#ff6b35", "#ffd700", "#ff9800", "#100806", "#1a0e08", "#200f08", "#2a1408"),
    "SOVEREIGN": ThemeDef("SOVEREIGN", "#c9933a", "#ff6b35", "#45a5ff", "#0a0804", "#140f06", "#1a1208", "#221808"),
    "VOID":      ThemeDef("VOID",      "#9c27b0", "#ff6b35", "#7b5fff", "#080410", "#0e0618", "#120820", "#18102a"),
    "ARCTIC":    ThemeDef("ARCTIC",    "#45a5ff", "#ff6b35", "#00d4b1", "#040810", "#060e1a", "#081220", "#0a162a"),
    "VENOM":     ThemeDef("VENOM",     "#4caf50", "#ff6b35", "#00d4b1", "#040a04", "#081008", "#0a1408", "#0e1a0e"),
    "CRIMSON":   ThemeDef("CRIMSON",   "#ff3a5a", "#ff9800", "#ff6b35", "#100406", "#1a0608", "#200808", "#2a0a0a"),
    "SAFFRON":   ThemeDef("SAFFRON",   "#ff9800", "#ff6b35", "#ffd700", "#0a0800", "#140e00", "#1a1200", "#201800"),
    "GHOST":     ThemeDef("GHOST",     "#888888", "#ff6b35", "#aaaaaa", "#080808", "#101010", "#141414", "#1a1a1a"),
    "COBALT":    ThemeDef("COBALT",    "#0066ff", "#ff6b35", "#45a5ff", "#040810", "#06101e", "#081428", "#0a1832"),
    "JARJAR":    ThemeDef("JARJAR",    "#FFD700", "#ff8c00", "#d4a800", "#0a0800", "#130f00", "#1c1700", "#261f00"),
}

# Persona → theme mapping
PERSONA_THEMES: dict[str, str] = {
    "jarvis":  "CIRCUIT",
    "india":   "SAFFRON",
    "ct7567":  "VENOM",
    "ct-7567": "VENOM",
    "morgan":  "SOVEREIGN",
    "jarjar":  "JARJAR",
}

# Theme display order for UI
THEME_ORDER = [
    "CIRCUIT", "EMBER", "SOVEREIGN", "VOID", "ARCTIC",
    "VENOM", "CRIMSON", "SAFFRON", "GHOST", "COBALT", "JARJAR",
]


# ── Global theme manager ──────────────────────────────────────────────────────

class ThemeManager:
    """
    Singleton theme manager.
    Import and use the `theme` singleton at bottom of this file.

    brightness: 0.0 (black) → 1.0 (full). Default 1.0.
    Brightness multiplies bg colors toward black when < 1.0.
    Accent, warm, cool colors are not dimmed (they should stay vivid).
    """

    def __init__(self):
        self._theme_name  = "CIRCUIT"
        self._brightness  = 1.0
        self._listeners: list[Callable] = []

    # ── Core accessors ────────────────────────────────────────────────────────

    def current(self) -> ThemeDef:
        return THEMES[self._theme_name]

    def name(self) -> str:
        return self._theme_name

    def brightness(self) -> float:
        return self._brightness

    def accent(self) -> str:
        return self.current().accent

    def warm(self) -> str:
        return self.current().warm

    def cool(self) -> str:
        return self.current().cool

    def bg(self, level: int = 1) -> str:
        """level 1=darkest, 2=panels, 3=inputs, 4=bars"""
        raw = getattr(self.current(), f"bg{level}", self.current().bg1)
        return self._dim(raw)

    def text(self, level: int = 1) -> str:
        """level 1=primary, 2=secondary, 3=dim"""
        colors = ["#c8e6f0", "#6a8fa0", "#3a5566"]
        c = colors[min(level - 1, 2)]
        return self._dim(c, factor=0.4)  # text dims less aggressively

    # ── Mutation ──────────────────────────────────────────────────────────────

    def set_theme(self, name: str) -> None:
        """Switch to a named theme. Notifies all listeners."""
        if name not in THEMES:
            return
        self._theme_name = name
        self._notify()

    def set_persona(self, persona: str) -> None:
        """Switch theme based on persona name."""
        key = persona.lower().replace(" ", "").replace("-", "")
        # Try exact match first, then with hyphen form
        mapped = PERSONA_THEMES.get(key) or PERSONA_THEMES.get(persona.lower())
        if mapped:
            self.set_theme(mapped)

    def set_brightness(self, value: float) -> None:
        """Set brightness 0.0–1.0. Notifies all listeners."""
        self._brightness = max(0.1, min(1.0, value))
        self._notify()

    # ── Listeners ─────────────────────────────────────────────────────────────

    def add_change_listener(self, fn: Callable) -> None:
        """Register fn() to be called when theme or brightness changes."""
        if fn not in self._listeners:
            self._listeners.append(fn)

    def remove_change_listener(self, fn: Callable) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    # ── Brightness helpers ────────────────────────────────────────────────────

    def _dim(self, hex_color: str, factor: float = 1.0) -> str:
        """
        Apply brightness to a hex color.
        factor=1.0 means full brightness scaling.
        factor=0.4 means only 40% as much dimming (for text).
        """
        if self._brightness >= 1.0:
            return hex_color
        try:
            h = hex_color.lstrip("#")
            if len(h) == 6:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                br = 1.0 - (1.0 - self._brightness) * factor
                r2 = int(r * br); g2 = int(g * br); b2 = int(b * br)
                return f"#{r2:02x}{g2:02x}{b2:02x}"
        except Exception:
            pass
        return hex_color

    # ── Stylesheet generators ─────────────────────────────────────────────────

    def border(self, alpha: float = 0.18) -> str:
        """Returns rgba border string using accent color."""
        h = self.accent().lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    def border_dim(self) -> str:
        return self.border(0.07)

    def accent_bg(self) -> str:
        """Accent at 10% opacity for active button backgrounds."""
        h = self.accent().lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},0.10)"

    def master_stylesheet(self) -> str:
        """Full QApplication stylesheet. Call setStyleSheet(theme.master_stylesheet())."""
        ac  = self.accent()
        adm = self._dim(ac, 0.5)
        abg = self.accent_bg()
        ab  = self.border()
        abd = self.border_dim()
        t1  = self.text(1)
        t2  = self.text(2)
        t3  = self.text(3)
        bg1 = self.bg(1)
        bg2 = self.bg(2)
        bg3 = self.bg(3)
        bg4 = self.bg(4)
        wm  = self.warm()
        mono = "Courier New"
        return f"""
QMainWindow, QDialog, QWidget {{
    background-color: {bg1};
    color: {t1};
    font-family: '{mono}';
    font-size: 10px;
}}
QFrame {{
    background-color: transparent;
    border: none;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background-color: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 3px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {ab};
    border-radius: 1px;
    min-height: 16px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}
QScrollBar:horizontal {{ height: 3px; background: transparent; border: none; }}
QScrollBar::handle:horizontal {{ background: {ab}; border-radius: 1px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; background: none; }}
QToolTip {{
    background-color: {bg2};
    color: {t1};
    border: 1px solid {ab};
    font-family: '{mono}';
    font-size: 9px;
    padding: 3px 6px;
}}
QLabel {{
    background: transparent;
    color: {t1};
    font-family: '{mono}';
    border: none;
}}
QPushButton {{
    background-color: transparent;
    color: {t2};
    border: none;
    font-family: '{mono}';
    font-size: 9px;
    letter-spacing: 1px;
    padding: 0 10px;
}}
QPushButton:hover {{
    color: {ac};
    background-color: {abg};
}}
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {bg3};
    color: {t1};
    border: 1px solid {ab};
    font-family: '{mono}';
    font-size: 10px;
    padding: 0 10px;
    selection-background-color: {abg};
}}
QComboBox {{
    background-color: {bg3};
    color: {t1};
    border: 1px solid {ab};
    font-family: '{mono}';
    font-size: 9px;
    padding: 0 8px;
    height: 28px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background: {bg2};
    color: {t1};
    border: 1px solid {ab};
    selection-background-color: {abg};
    selection-color: {ac};
    outline: none;
}}
QSlider::groove:horizontal {{
    height: 3px;
    background: {bg4};
    border-radius: 1px;
}}
QSlider::handle:horizontal {{
    background: {ac};
    border: none;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::sub-page:horizontal {{
    background: {ac};
    border-radius: 1px;
}}
QProgressBar {{
    background: {bg4};
    border: none;
    border-radius: 1px;
    height: 3px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {ac};
    border-radius: 1px;
}}
QGroupBox {{
    background: transparent;
    border: 1px solid {ab};
    border-radius: 4px;
    margin-top: 8px;
    font-family: '{mono}';
    font-size: 8px;
    color: {t2};
    letter-spacing: 2px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: {t2};
}}
QCheckBox {{
    color: {t1};
    font-family: '{mono}';
    font-size: 9px;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {ab};
    background: {bg3};
    border-radius: 2px;
}}
QCheckBox::indicator:checked {{
    background: {ac};
    border-color: {ac};
}}
QSplitter::handle {{
    background: {ab};
    width: 1px;
    height: 1px;
}}
"""

    def panel_style(self) -> str:
        """Stylesheet for a standard side panel."""
        return (f"background:{self.bg(2)};"
                f"border-right:1px solid {self.border()};")

    def section_header_style(self) -> str:
        return (f"font-family:'Courier New';font-size:8px;"
                f"letter-spacing:2px;color:{self.text(2)};"
                f"background:transparent;")

    def kv_key_style(self) -> str:
        return f"font-family:'Courier New';font-size:9px;color:{self.text(2)};background:transparent;"

    def kv_val_style(self, state: str = "normal") -> str:
        col = {
            "ok":   self.accent(),
            "warn": self.warm(),
            "err":  "#ff3a5a",
        }.get(state, self.text(1))
        return f"font-family:'Courier New';font-size:9px;color:{col};background:transparent;"

    def save(self) -> None:
        """Persist theme and brightness to settings store."""
        try:
            from storage.settings_store import SettingsStore
            s = SettingsStore()
            s.set("gui.theme",      self._theme_name)
            s.set("gui.brightness", str(self._brightness))
        except Exception:
            pass

    def load(self) -> None:
        """Restore theme and brightness from settings store."""
        try:
            from storage.settings_store import SettingsStore
            s = SettingsStore()
            saved_theme = s.get("gui.theme", "CIRCUIT")
            saved_bright = float(s.get("gui.brightness", "1.0"))
            if saved_theme in THEMES:
                self._theme_name = saved_theme
            self._brightness = max(0.1, min(1.0, saved_bright))
        except Exception:
            pass


# ── Singleton ────────────────────────────────────────────────────────────────
theme = ThemeManager()
