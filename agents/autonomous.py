"""
agents/autonomous.py — AutonomousAgent: periodic LLM-driven task proposals.

Runs on a 5-minute daemon loop. Emits Qt signals — all GUI updates queue to main thread.
Proposals require explicit operator approval before any command is executed.
"""
from __future__ import annotations

import json
import re
import time
import threading
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal

from llm.client import LLM
from llm.prompts import AUTO_SYSTEM
from storage.db import (
    get_active_project, get_notes, get_recent_commands, log_command,
)
from tools.system_tools import tool_system_status
from tools.shell_tools import tool_run_command


class AutoSignals(QObject):
    proposals_ready = Signal(list)   # list[dict]
    task_done       = Signal(str, str)
    observation     = Signal(str)


class AutonomousAgent(QObject):
    INTERVAL_S = 300  # 5 minutes

    def __init__(self, llm: LLM):
        super().__init__()
        self.signals  = AutoSignals()
        self._llm     = llm
        self._running = False
        self._pending : dict[str, dict] = {}
        self._next_proposal_requested: bool = False

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def think_now(self):
        threading.Thread(target=self._think, daemon=True).start()

    def request_next_proposal(self):
        """Signal the agent to generate the next proposal immediately, skipping the wait interval."""
        self._next_proposal_requested = True

    def _loop(self):
        time.sleep(15)
        while self._running:
            self._think()
            for _ in range(self.INTERVAL_S):
                if not self._running:
                    return
                if self._next_proposal_requested:
                    self._next_proposal_requested = False
                    break  # skip remaining wait, generate next proposal now
                time.sleep(1)

    def _think(self):
        if not self._llm.online:
            return
        proj   = get_active_project()
        status = tool_system_status()
        notes  = get_notes(proj)
        cmds   = get_recent_commands(proj, 5)

        ctx = (
            f"Project: {proj}\n"
            f"Time: {datetime.now().strftime('%H:%M')}\n"
            f"System:\n{status[:400]}\n"
        )
        if notes:
            ctx += f"Notes: {notes[-300:].replace(chr(10),' | ')}\n"
        if cmds:
            ctx += f"Recent commands: {', '.join(cmds[:3])}\n"

        # Strategy context — tell the LLM what recon stage we're at
        try:
            from autonomy.strategy import StrategyEngine
            _se = StrategyEngine()
            _state = _se.get_current_mission(proj)
            if _state:
                ctx += (
                    f"Recon stage: {_state.stage.value}\n"
                    f"Subdomains: {_state.subdomains}, Live hosts: {_state.live_hosts}, "
                    f"Findings: {_state.findings}\n"
                    f"Recommended action: {_se.recommend_next_action(_state)}\n"
                )
        except Exception:
            pass  # strategy engine optional — never block _think()

        resp = self._llm.complete(
            messages=[{"role": "user", "content": f"Analyze and propose:\n\n{ctx}"}],
            system=AUTO_SYSTEM,
            temperature=0.2,
            max_tokens=512,
        )
        raw  = resp.get("content", "")
        data = self._parse(raw)
        if not data:
            return

        obs   = data.get("observation", "")
        props = data.get("proposals", [])
        valid = []
        for p in props:
            if not isinstance(p, dict) or "title" not in p:
                continue
            pid = f"task_{int(time.time()*1000)}_{len(valid)}"
            d   = {
                "id":          pid,
                "title":       str(p.get("title", "Task")),
                "description": str(p.get("description", "")),
                "command":     p.get("command") if p.get("command") not in (None, "null", "") else None,
                "priority":    str(p.get("priority", "medium")),
            }
            valid.append(d)
            self._pending[pid] = d

        if valid:
            self.signals.observation.emit(obs)
            self.signals.proposals_ready.emit(valid)

    @staticmethod
    def _parse(text: str) -> Optional[dict]:
        text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = text[start:i+1]
                    chunk = re.sub(r",\s*([}\]])", r"\1", chunk)
                    try:
                        return json.loads(chunk)
                    except Exception:
                        return None
        return None

    def approve(self, task_id: str):
        p = self._pending.pop(task_id, None)
        if not p:
            return
        if p.get("command"):
            out = tool_run_command(p["command"], confirmed=True)
            log_command(get_active_project(), p["command"], out)
            self.signals.task_done.emit(p["title"], out)
        else:
            self.signals.task_done.emit(p["title"], p["description"])

    def reject(self, task_id: str):
        self._pending.pop(task_id, None)
