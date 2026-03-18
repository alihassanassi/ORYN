"""
agents/monitor.py — MonitorAgent: passive psutil watcher.

Runs every 5 minutes. No LLM calls — pure system metrics.
Emits Qt signals so all GUI updates route to the main thread.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from storage.db import append_note, get_active_project


class MonitorSignals(QObject):
    alert  = Signal(str)        # high-priority message → main chat
    ticker = Signal(str, str)   # (label, text) → Neural Pathways feed


class MonitorAgent(QObject):
    """Passive watcher: CPU, RAM, disk, process list, network change detection."""

    INTERVAL_S = 300

    def __init__(self):
        super().__init__()
        self.signals   = MonitorSignals()
        self._running  = False
        self._last_net : dict = {}

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _loop(self):
        time.sleep(20)
        while self._running:
            self._cycle()
            for _ in range(self.INTERVAL_S):
                if not self._running:
                    return
                time.sleep(1)

    def _cycle(self):
        try:
            import psutil
        except ImportError:
            return

        proj       = get_active_project()
        ts         = datetime.now().strftime("%H:%M")
        note_parts : list = []

        # CPU
        try:
            cpu = psutil.cpu_percent(interval=2.0)
            note_parts.append(f"CPU {cpu:.0f}%")
            if cpu > 80:
                self.signals.alert.emit(
                    f"One item of note, sir — CPU at {cpu:.0f}% sustained "
                    f"across {psutil.cpu_count()} cores."
                )
        except Exception:
            pass

        # Top 5 CPU hogs → ticker
        try:
            procs = sorted(
                psutil.process_iter(["name", "cpu_percent", "memory_info"]),
                key=lambda p: p.info.get("cpu_percent") or 0,
                reverse=True,
            )[:5]
            rows = []
            for p in procs:
                mi     = p.info.get("memory_info")
                mem_mb = round(mi.rss / 1024 ** 2, 1) if mi else 0.0
                rows.append(
                    f"{(p.info.get('name') or '?')[:22]:22s}"
                    f"  cpu={p.info.get('cpu_percent', 0):5.1f}%"
                    f"  mem={mem_mb} MB"
                )
            if rows:
                self.signals.ticker.emit("top-procs", "\n".join(rows))
        except Exception:
            pass

        # Disk
        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    note_parts.append(f"{part.device} {usage.percent:.0f}%")
                    if usage.percent > 90:
                        free_gb = round(usage.free / 1024 ** 3, 1)
                        self.signals.alert.emit(
                            f"Disk {part.device} at {usage.percent:.0f}% capacity, sir. "
                            f"{free_gb} GB remaining — cleanup recommended."
                        )
                except PermissionError:
                    pass
        except Exception:
            pass

        # Network change detection
        try:
            current: dict = {}
            for name, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if a.family == 2:   # AF_INET
                        current[name] = a.address
            if self._last_net:
                added   = {k: v for k, v in current.items() if k not in self._last_net}
                removed = {k     for k in self._last_net     if k not in current}
                changed = {k: v for k, v in current.items()
                           if k in self._last_net and self._last_net[k] != v}
                parts: list = []
                for k, v in added.items():   parts.append(f"{k} online ({v})")
                for k in removed:            parts.append(f"{k} offline")
                for k, v in changed.items(): parts.append(f"{k} → {v}")
                if parts:
                    msg = "; ".join(parts)
                    self.signals.alert.emit(f"Network change detected, sir — {msg}.")
                    self.signals.ticker.emit("net-change", msg)
            self._last_net = current
        except Exception:
            pass

        # Cycle summary → notes
        try:
            if note_parts:
                append_note(proj, f"[Monitor {ts}] " + "  |  ".join(note_parts))
        except Exception:
            pass
