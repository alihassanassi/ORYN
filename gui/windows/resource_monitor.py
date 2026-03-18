"""
gui/windows/resource_monitor.py — JARVIS floating resource monitor window.

Shows live GPU, CPU, RAM, process, LLM, and network statistics.
Keyboard shortcut: Ctrl+Shift+R (wired in main_window.py).
Hides on close/Ctrl+W — stays alive for fast re-open.
"""
from __future__ import annotations

import subprocess
import time
from collections import deque
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QProgressBar,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

# ── Theme / config with fallbacks ────────────────────────────────────────────

try:
    from gui.theme import theme as _theme
    def _accent() -> str:        return _theme.accent()
    def _bg(n: int = 1) -> str:  return _theme.bg(n)
    def _text(n: int = 1) -> str: return _theme.text(n)
    def _border() -> str:        return _theme.border(0.18)
    def _border_dim() -> str:    return _theme.border(0.07)
    def _warm() -> str:          return _theme.warm()
    _HAS_THEME = True
except Exception:
    def _accent() -> str:        return "#18e0c1"
    def _bg(n: int = 1) -> str:  return {1: "#060b10", 2: "#0a1018", 3: "#0d1520", 4: "#111e2a"}.get(n, "#060b10")
    def _text(n: int = 1) -> str: return {1: "#c8e6f0", 2: "#6a8fa0", 3: "#3a5566"}.get(n, "#c8e6f0")
    def _border() -> str:        return "rgba(0,212,177,0.18)"
    def _border_dim() -> str:    return "rgba(0,212,177,0.07)"
    def _warm() -> str:          return "#ff6b35"
    _HAS_THEME = False

try:
    import config as _cfg
    _OLLAMA_MODEL  = getattr(_cfg, "OLLAMA_MODEL", "qwen3:14b")
    _OLLAMA_OPTIONS = getattr(_cfg, "OLLAMA_OPTIONS", {})
    _NUM_CTX = _OLLAMA_OPTIONS.get("num_ctx", 4096)
except Exception:
    _OLLAMA_MODEL = "unknown"
    _NUM_CTX      = 4096

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except Exception:
    _HAS_PSUTIL = False

_MONO = "Courier New"


# ── SparklineWidget ───────────────────────────────────────────────────────────

class SparklineWidget(QWidget):
    """60-point rolling history sparkline with filled area and line."""

    def __init__(self, color: Optional[str] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = color or _accent()
        self._data: deque[float] = deque([0.0] * 60, maxlen=60)
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def push(self, value: float) -> None:
        self._data.append(max(0.0, float(value)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # Background
        try:
            bg = _bg(3)
        except Exception:
            bg = "#0d1520"
        painter.fillRect(0, 0, w, h, QColor(bg))

        data = list(self._data)
        if not data:
            return

        max_v = max(data) if max(data) > 0 else 1.0
        n     = len(data)
        step  = w / max(n - 1, 1)

        def _px(i: int) -> tuple[float, float]:
            x = i * step
            y = h - (data[i] / max_v) * (h - 2) - 1
            return x, y

        # Parse accent color for fill with alpha
        try:
            ac = _accent()
            hx = ac.lstrip("#")
            r2, g2, b2 = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        except Exception:
            r2, g2, b2 = 0, 212, 177

        # Filled polygon (area under curve)
        from PySide6.QtGui import QPolygonF
        from PySide6.QtCore import QPointF
        poly = QPolygonF()
        poly.append(QPointF(0, h))
        for i in range(n):
            x, y = _px(i)
            poly.append(QPointF(x, y))
        poly.append(QPointF((n - 1) * step, h))

        fill_color = QColor(r2, g2, b2, 30)
        painter.setBrush(fill_color)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(poly)

        # Line
        line_color = QColor(r2, g2, b2, 200)
        pen = QPen(line_color, 1.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for i in range(1, n):
            x0, y0 = _px(i - 1)
            x1, y1 = _px(i)
            painter.drawLine(int(x0), int(y0), int(x1), int(y1))

        painter.end()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _section_header(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setStyleSheet(
        f"font-family:'{_MONO}';"
        f"font-size:9px;"
        f"letter-spacing:2px;"
        f"color:{_text(2)};"
        f"background:transparent;"
        f"padding:4px 0 4px 0;"
        f"border-bottom:1px solid {_border_dim()};"
    )
    return lbl


def _stat_row(key: str) -> tuple[QWidget, QLabel]:
    """Returns (row_widget, value_label). Key is left-aligned, value right-aligned."""
    row = QWidget()
    row.setStyleSheet("background:transparent;")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 1, 0, 1)
    layout.setSpacing(4)

    key_lbl = QLabel(key)
    key_lbl.setStyleSheet(
        f"font-family:'{_MONO}';"
        f"font-size:9px;"
        f"color:{_text(2)};"
        f"background:transparent;"
    )
    key_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    val_lbl = QLabel("—")
    val_lbl.setStyleSheet(
        f"font-family:'{_MONO}';"
        f"font-size:9px;"
        f"color:{_accent()};"
        f"background:transparent;"
    )
    val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    layout.addWidget(key_lbl, 1)
    layout.addWidget(val_lbl, 0)
    return row, val_lbl


def _section_container() -> tuple[QWidget, QVBoxLayout]:
    """A padded container widget for a section."""
    w = QWidget()
    w.setStyleSheet(
        f"background:{_bg(2)};"
        f"border:1px solid {_border_dim()};"
        f"border-radius:3px;"
    )
    v = QVBoxLayout(w)
    v.setContentsMargins(10, 6, 10, 8)
    v.setSpacing(2)
    return w, v


# ── Main window ───────────────────────────────────────────────────────────────

class ResourceMonitorWindow(QMainWindow):
    """
    Floating resource monitor for JARVIS.
    Open with Ctrl+Shift+R. Close button hides (does not destroy).
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS — RESOURCE MONITOR")
        self.setMinimumSize(520, 720)
        self.resize(560, 820)
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowStaysOnTopHint |
            Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint |
            Qt.WindowMinimizeButtonHint
        )

        # Apply theme stylesheet
        try:
            from gui.theme import theme as _t
            self.setStyleSheet(_t.master_stylesheet())
        except Exception:
            pass

        # Internal state
        self._net_prev_sent: int = 0
        self._net_prev_recv: int = 0
        self._net_prev_time: float = time.monotonic()

        # Sparklines
        self._spark_gpu  = SparklineWidget()
        self._spark_cpu  = SparklineWidget()
        self._spark_ram  = SparklineWidget()
        self._spark_net  = SparklineWidget(color=_warm())

        # Value labels — populated in _build_ui, referenced in _refresh_*
        self._lbl_gpu_util   : Optional[QLabel] = None
        self._lbl_gpu_vram_u : Optional[QLabel] = None
        self._lbl_gpu_vram_f : Optional[QLabel] = None
        self._lbl_gpu_temp   : Optional[QLabel] = None
        self._lbl_gpu_power  : Optional[QLabel] = None
        self._lbl_gpu_clock  : Optional[QLabel] = None

        self._lbl_cpu_total  : Optional[QLabel] = None
        self._lbl_cpu_freq   : Optional[QLabel] = None
        self._lbl_cpu_phys   : Optional[QLabel] = None
        self._lbl_cpu_logic  : Optional[QLabel] = None

        self._lbl_ram_used   : Optional[QLabel] = None
        self._lbl_ram_free   : Optional[QLabel] = None
        self._lbl_ram_pct    : Optional[QLabel] = None
        self._ram_bar        : Optional[QProgressBar] = None

        self._lbl_proc_cpu   : Optional[QLabel] = None
        self._lbl_proc_ram   : Optional[QLabel] = None
        self._lbl_proc_thrd  : Optional[QLabel] = None
        self._lbl_proc_fds   : Optional[QLabel] = None

        self._lbl_llm_model  : Optional[QLabel] = None
        self._lbl_llm_ctx    : Optional[QLabel] = None
        self._lbl_llm_cache  : Optional[QLabel] = None

        self._lbl_net_send   : Optional[QLabel] = None
        self._lbl_net_recv   : Optional[QLabel] = None

        self._build_ui()

        # Auto-refresh timer — 1000ms
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)

        # Seed the first refresh immediately
        QTimer.singleShot(0, self._refresh)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Central scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical {"
            f"  background: transparent; width: 6px; border: none; margin: 0;"
            "}"
            "QScrollBar::handle:vertical {"
            f"  background: {_border()}; border-radius: 3px; min-height: 16px;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            "  height: 0; background: none;"
            "}"
        )
        self.setCentralWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background: {_bg(1)};")
        scroll.setWidget(content)

        outer = QVBoxLayout(content)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # ── GPU section ───────────────────────────────────────────────────────
        gpu_sec, gpu_v = _section_container()
        gpu_v.addWidget(_section_header("◈  GPU — RTX 4070 Ti Super"))

        rows_gpu = [
            ("COMPUTE UTIL",  "_lbl_gpu_util"),
            ("VRAM USED",     "_lbl_gpu_vram_u"),
            ("VRAM FREE",     "_lbl_gpu_vram_f"),
            ("TEMPERATURE",   "_lbl_gpu_temp"),
            ("POWER DRAW",    "_lbl_gpu_power"),
            ("CLOCK SPEED",   "_lbl_gpu_clock"),
        ]
        for key, attr in rows_gpu:
            row_w, val_lbl = _stat_row(key)
            setattr(self, attr, val_lbl)
            gpu_v.addWidget(row_w)

        gpu_v.addWidget(self._spark_gpu)
        outer.addWidget(gpu_sec)

        # ── CPU section ───────────────────────────────────────────────────────
        cpu_sec, cpu_v = _section_container()
        cpu_v.addWidget(_section_header("◈  CPU — i7-14700F"))

        rows_cpu = [
            ("TOTAL USAGE",      "_lbl_cpu_total"),
            ("FREQUENCY",        "_lbl_cpu_freq"),
            ("PHYSICAL CORES",   "_lbl_cpu_phys"),
            ("LOGICAL THREADS",  "_lbl_cpu_logic"),
        ]
        for key, attr in rows_cpu:
            row_w, val_lbl = _stat_row(key)
            setattr(self, attr, val_lbl)
            cpu_v.addWidget(row_w)

        cpu_v.addWidget(self._spark_cpu)
        outer.addWidget(cpu_sec)

        # ── RAM section ───────────────────────────────────────────────────────
        ram_sec, ram_v = _section_container()
        ram_v.addWidget(_section_header("◈  RAM — DDR5"))

        rows_ram = [
            ("USED",     "_lbl_ram_used"),
            ("FREE",     "_lbl_ram_free"),
            ("PERCENT",  "_lbl_ram_pct"),
        ]
        for key, attr in rows_ram:
            row_w, val_lbl = _stat_row(key)
            setattr(self, attr, val_lbl)
            ram_v.addWidget(row_w)

        self._ram_bar = QProgressBar()
        self._ram_bar.setFixedHeight(6)
        self._ram_bar.setTextVisible(False)
        self._ram_bar.setRange(0, 100)
        self._ram_bar.setValue(0)
        self._ram_bar.setStyleSheet(
            f"QProgressBar {{ background: {_bg(4)}; border: none; border-radius: 1px; }}"
            f"QProgressBar::chunk {{ background: {_accent()}; border-radius: 1px; }}"
        )
        ram_v.addWidget(self._ram_bar)
        ram_v.addWidget(self._spark_ram)
        outer.addWidget(ram_sec)

        # ── JARVIS Process section ─────────────────────────────────────────────
        proc_sec, proc_v = _section_container()
        proc_v.addWidget(_section_header("◈  JARVIS PROCESS"))

        rows_proc = [
            ("PROCESS CPU",  "_lbl_proc_cpu"),
            ("PROCESS RAM",  "_lbl_proc_ram"),
            ("THREADS",      "_lbl_proc_thrd"),
            ("OPEN HANDLES", "_lbl_proc_fds"),
        ]
        for key, attr in rows_proc:
            row_w, val_lbl = _stat_row(key)
            setattr(self, attr, val_lbl)
            proc_v.addWidget(row_w)

        outer.addWidget(proc_sec)

        # ── LLM Performance section ────────────────────────────────────────────
        llm_sec, llm_v = _section_container()
        llm_v.addWidget(_section_header("◈  LLM PERFORMANCE"))

        rows_llm = [
            ("MODEL",         "_lbl_llm_model"),
            ("CONTEXT SIZE",  "_lbl_llm_ctx"),
            ("CACHE HIT RATE","_lbl_llm_cache"),
        ]
        for key, attr in rows_llm:
            row_w, val_lbl = _stat_row(key)
            setattr(self, attr, val_lbl)
            llm_v.addWidget(row_w)

        outer.addWidget(llm_sec)

        # ── Network section ────────────────────────────────────────────────────
        net_sec, net_v = _section_container()
        net_v.addWidget(_section_header("◈  NETWORK I/O"))

        rows_net = [
            ("SEND KB/s", "_lbl_net_send"),
            ("RECV KB/s", "_lbl_net_recv"),
        ]
        for key, attr in rows_net:
            row_w, val_lbl = _stat_row(key)
            setattr(self, attr, val_lbl)
            net_v.addWidget(row_w)

        net_v.addWidget(self._spark_net)
        outer.addWidget(net_sec)

        outer.addStretch()

    # ── Refresh dispatcher ────────────────────────────────────────────────────

    def _refresh(self) -> None:
        try:
            self._refresh_gpu()
        except Exception:
            pass
        try:
            self._refresh_cpu()
        except Exception:
            pass
        try:
            self._refresh_ram()
        except Exception:
            pass
        try:
            self._refresh_process()
        except Exception:
            pass
        try:
            self._refresh_llm()
        except Exception:
            pass
        try:
            self._refresh_net()
        except Exception:
            pass

    # ── GPU ───────────────────────────────────────────────────────────────────

    def _refresh_gpu(self) -> None:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total,"
                    "temperature.gpu,power.draw,clocks.gr",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode != 0:
                raise RuntimeError("nvidia-smi non-zero exit")

            line = result.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 6:
                raise ValueError("unexpected nvidia-smi output")

            util, vram_used, vram_total, temp, power, clock = parts

            try:
                vram_u_mb = float(vram_used)
                vram_t_mb = float(vram_total)
                vram_f_mb = vram_t_mb - vram_u_mb
            except (ValueError, TypeError):
                vram_u_mb = vram_f_mb = 0.0

            if self._lbl_gpu_util   is not None: self._lbl_gpu_util.setText(f"{util} %")
            if self._lbl_gpu_vram_u is not None: self._lbl_gpu_vram_u.setText(f"{vram_u_mb:.0f} MB")
            if self._lbl_gpu_vram_f is not None: self._lbl_gpu_vram_f.setText(f"{vram_f_mb:.0f} MB")
            if self._lbl_gpu_temp   is not None: self._lbl_gpu_temp.setText(f"{temp} °C")
            if self._lbl_gpu_power  is not None: self._lbl_gpu_power.setText(f"{power} W")
            if self._lbl_gpu_clock  is not None: self._lbl_gpu_clock.setText(f"{clock} MHz")

            try:
                self._spark_gpu.push(float(util))
            except Exception:
                pass

        except FileNotFoundError:
            self._gpu_unavailable("nvidia-smi not found")
        except subprocess.TimeoutExpired:
            self._gpu_unavailable("nvidia-smi timeout")
        except Exception as exc:
            self._gpu_unavailable(f"unavailable ({type(exc).__name__})")

    def _gpu_unavailable(self, reason: str) -> None:
        for lbl in (
            self._lbl_gpu_util, self._lbl_gpu_vram_u, self._lbl_gpu_vram_f,
            self._lbl_gpu_temp, self._lbl_gpu_power, self._lbl_gpu_clock,
        ):
            if lbl is not None:
                lbl.setText(reason if lbl is self._lbl_gpu_util else "—")

    # ── CPU ───────────────────────────────────────────────────────────────────

    def _refresh_cpu(self) -> None:
        if not _HAS_PSUTIL:
            return

        import psutil
        cpu_pct = psutil.cpu_percent(interval=None)

        try:
            freq = psutil.cpu_freq()
            freq_str = f"{freq.current:.0f} MHz" if freq else "—"
        except Exception:
            freq_str = "—"

        try:
            phys = psutil.cpu_count(logical=False) or 0
            logi = psutil.cpu_count(logical=True)  or 0
        except Exception:
            phys = logi = 0

        if self._lbl_cpu_total  is not None: self._lbl_cpu_total.setText(f"{cpu_pct:.1f} %")
        if self._lbl_cpu_freq   is not None: self._lbl_cpu_freq.setText(freq_str)
        if self._lbl_cpu_phys   is not None: self._lbl_cpu_phys.setText(str(phys))
        if self._lbl_cpu_logic  is not None: self._lbl_cpu_logic.setText(str(logi))

        self._spark_cpu.push(cpu_pct)

    # ── RAM ───────────────────────────────────────────────────────────────────

    def _refresh_ram(self) -> None:
        if not _HAS_PSUTIL:
            return

        import psutil
        vm = psutil.virtual_memory()

        used_gb = vm.used  / (1024 ** 3)
        free_gb = vm.available / (1024 ** 3)
        pct     = vm.percent

        if self._lbl_ram_used is not None: self._lbl_ram_used.setText(f"{used_gb:.1f} GB")
        if self._lbl_ram_free is not None: self._lbl_ram_free.setText(f"{free_gb:.1f} GB")
        if self._lbl_ram_pct  is not None: self._lbl_ram_pct.setText(f"{pct:.1f} %")

        if self._ram_bar is not None:
            self._ram_bar.setValue(int(pct))

        self._spark_ram.push(pct)

    # ── Process ───────────────────────────────────────────────────────────────

    def _refresh_process(self) -> None:
        if not _HAS_PSUTIL:
            return

        import psutil
        try:
            proc = psutil.Process()

            # CPU — non-blocking (interval=None uses cached value from last call)
            proc_cpu = proc.cpu_percent(interval=None)

            # RAM in MB
            mem_info = proc.memory_info()
            proc_ram_mb = mem_info.rss / (1024 ** 2)

            # Thread count
            num_threads = proc.num_threads()

            # Open handles (Windows) / fds (POSIX)
            try:
                num_fds = proc.num_handles()
            except AttributeError:
                try:
                    num_fds = proc.num_fds()
                except Exception:
                    num_fds = 0

            if self._lbl_proc_cpu  is not None: self._lbl_proc_cpu.setText(f"{proc_cpu:.1f} %")
            if self._lbl_proc_ram  is not None: self._lbl_proc_ram.setText(f"{proc_ram_mb:.1f} MB")
            if self._lbl_proc_thrd is not None: self._lbl_proc_thrd.setText(str(num_threads))
            if self._lbl_proc_fds  is not None: self._lbl_proc_fds.setText(str(num_fds))

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # ── LLM ───────────────────────────────────────────────────────────────────

    def _refresh_llm(self) -> None:
        if self._lbl_llm_model is not None:
            self._lbl_llm_model.setText(_OLLAMA_MODEL)

        if self._lbl_llm_ctx is not None:
            self._lbl_llm_ctx.setText(f"{_NUM_CTX:,}")

        if self._lbl_llm_cache is not None:
            try:
                from llm.response_cache import response_cache
                st = response_cache.stats()
                self._lbl_llm_cache.setText(st.get("hit_rate", "—"))
            except Exception:
                self._lbl_llm_cache.setText("—")

    # ── Network ───────────────────────────────────────────────────────────────

    def _refresh_net(self) -> None:
        if not _HAS_PSUTIL:
            return

        import psutil
        try:
            counters = psutil.net_io_counters()
            now   = time.monotonic()
            dt    = now - self._net_prev_time
            if dt <= 0:
                return

            sent_delta = counters.bytes_sent - self._net_prev_sent
            recv_delta = counters.bytes_recv - self._net_prev_recv

            # Guard against counter resets / first call
            if sent_delta < 0: sent_delta = 0
            if recv_delta < 0: recv_delta = 0

            send_kbs = (sent_delta / 1024.0) / dt
            recv_kbs = (recv_delta / 1024.0) / dt

            self._net_prev_sent = counters.bytes_sent
            self._net_prev_recv = counters.bytes_recv
            self._net_prev_time = now

            if self._lbl_net_send is not None: self._lbl_net_send.setText(f"{send_kbs:.1f}")
            if self._lbl_net_recv is not None: self._lbl_net_recv.setText(f"{recv_kbs:.1f}")

            self._spark_net.push(recv_kbs + send_kbs)

        except Exception:
            pass

    # ── Window lifecycle ──────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802
        """Hide instead of close — keeps timer alive for fast re-open."""
        self.hide()
        event.ignore()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Ctrl+W hides the monitor."""
        if (event.key() == Qt.Key_W and
                event.modifiers() & Qt.ControlModifier):
            self.hide()
        else:
            super().keyPressEvent(event)
