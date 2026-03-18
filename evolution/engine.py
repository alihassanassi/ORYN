"""
evolution/engine.py — SelfEvolution engine.

JARVIS reads its own source, selects the next queued improvement from a
pre-written patch library, validates it (syntax + structural markers + size
sanity), saves a patch file, then signals the GUI for operator approval.

On approval: backup current source → overwrite → signal for process restart.
Small patches (<20 changed lines) auto-apply without approval.
"""
from __future__ import annotations

import ast
import difflib
import json
import re
import shutil
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from llm.client import LLM
from config import BACKUP_DIR, PATCH_DIR, EVO_STATE


# ── Phase 1 / Phase 2 system prompts (kept for reference — not used by queue)
EVO_PHASE1 = """\
Output ONLY a JSON object. No other text whatsoever.
First char: {   Last char: }   Nothing else.

{"summary":"Added/Improved/Extended/Refactored X to do Y","reasoning":"one sentence","target":"ClassName","change":"exact description of what code to write"}

Do not touch self-evolution safety checks.
Do not write any words outside the JSON object.
"""

EVO_PHASE2 = """\
You are JARVIS's self-improvement coding module.

You will be given:
1. The complete current source code
2. An exact description of ONE change to make

Your job: output the COMPLETE updated file with that change applied.

RULES — non-negotiable:
- Output RAW PYTHON CODE ONLY. Not JSON. Not markdown. No backticks. No prose.
- The very first character of your output must be the very first character of the file.
- The very last character must be the last line of the file.
- Preserve every existing feature. Do not remove anything.
- The result must pass ast.parse() with no errors.
- Do not change the self-evolution engine safety checks.
"""

# Alias kept for structural integrity check
_EVO_SYSTEM = "_EVO_SYSTEM"

# ── Curated patch queue (pre-written; no LLM codegen needed) ─────────────────
_EVO_QUEUE = [
    {
        "summary":       "Add Ctrl+L shortcut to clear chat history",
        "reasoning":     "Quick clear improves workflow during long sessions",
        "target":        "JARVIS",
        "target_method": "_new_project",
        "new_code": """    def _clear_chat(self):
        for i in reversed(range(self._chat_vbox.count())):
            w = self._chat_vbox.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._history.clear()
        self._add_msg("assistant", "Chat cleared, sir.")

    def _new_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if ok and name.strip():
            create_project(name.strip())
            self._refresh_projects()
            self._add_msg("assistant", f"Project \'{name.strip()}\' created, sir.")
""",
    },
    {
        "summary":       "Add Ctrl+Up to recall last sent message",
        "reasoning":     "Shell-like history recall saves retyping",
        "target":        "JARVIS",
        "target_method": "eventFilter",
        "new_code": """    def eventFilter(self, obj, event):
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
""",
    },
    {
        "summary":       "Show system tray icon with quick-access menu",
        "reasoning":     "Minimise to tray instead of closing",
        "target":        "JARVIS",
        "target_method": "_build_shortcuts",
        "new_code": """    def _build_shortcuts(self):
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
""",
    },
    {
        "summary":       "Add Ctrl+K command palette for quick actions",
        "reasoning":     "Power-user shortcut to trigger any quick action by name",
        "target":        "JARVIS",
        "target_method": "_new_project",
        "new_code": """    def _open_palette(self):
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
            self._add_msg("assistant", f"Project \'{name.strip()}\' created, sir.")
""",
    },
]


class EvoSignals(QObject):
    status         = Signal(str)
    proposal_ready = Signal(str, str, str)   # summary, diff_preview, patch_path
    auto_apply     = Signal(str, str)        # summary, patch_path (<20 changed lines)
    applied        = Signal(str)             # backup_path
    error          = Signal(str)


class SelfEvolution(QObject):
    """
    Reads source, picks next queued patch, validates, saves, waits for approval.
    On approval: backup → overwrite → signal for restart.
    """

    def __init__(self, llm: LLM, source_path: Path):
        super().__init__()
        self.signals     = EvoSignals()
        self._llm        = llm
        self._src        = source_path
        self._backup_dir = BACKUP_DIR
        self._patch_dir  = PATCH_DIR
        self._state_file = EVO_STATE
        self._backup_dir.mkdir(exist_ok=True)
        self._patch_dir.mkdir(exist_ok=True)
        self._rejected  : set = set()
        self._queue_idx : int = 0
        self._load_state()

    def analyse(self):
        threading.Thread(target=self._run, daemon=True).start()

    def mark_rejected(self, summary: str):
        self._rejected.add(summary)
        self._queue_idx += 1
        self._save_state()

    def _run(self):
        try:
            self._emit_status("Reading source code…")
            src        = self._src.read_text(encoding="utf-8")
            line_count = src.count("\n")
            self._emit_status(f"Analysing {line_count:,} lines…")

            # Pick next non-rejected item
            available = [q for q in _EVO_QUEUE if q["summary"] not in self._rejected]
            if not available:
                self._rejected.clear()
                available = _EVO_QUEUE
            idx  = self._queue_idx % len(available)
            plan = available[idx]
            self._queue_idx += 1
            self._save_state()

            summary       = str(plan.get("summary", "Improvement"))
            reasoning     = str(plan.get("reasoning", ""))
            target        = str(plan.get("target", "JARVIS"))
            target_method = str(plan.get("target_method", ""))
            new_code      = plan.get("new_code", "")

            self._emit_status(f"Applying patch: {summary[:40]}…")

            if not new_code:
                self.signals.error.emit("No new_code in plan — nothing to apply.")
                return

            snippet, start_line, end_line = self._extract_method(src, target, target_method)

            if snippet and start_line > 0:
                src_lines  = src.splitlines(keepends=True)
                new_source = (
                    "".join(src_lines[:start_line - 1])
                    + new_code.rstrip() + "\n"
                    + "".join(src_lines[end_line:])
                )
            else:
                target_pos = src.find(f"class {target}(")
                next_class = re.search(r"^class ", src[target_pos+1:], re.MULTILINE)
                if next_class:
                    insert_pos = target_pos + 1 + next_class.start()
                else:
                    insert_pos = len(src)
                new_source = src[:insert_pos] + "\n\n" + new_code.rstrip() + "\n\n" + src[insert_pos:]

            if not new_source.strip():
                self.signals.error.emit("New source empty after splice.")
                return

            # Validation 1: syntax
            self._emit_status("Validating syntax…")
            try:
                ast.parse(new_source)
            except SyntaxError as e:
                self.signals.error.emit(
                    f"Syntax error at line {e.lineno}: {e.msg}\n\nIn splice for: {summary}"
                )
                return

            # Validation 2: critical markers (must survive the splice in main_window.py)
            required = ["class JARVIS(", "def _boot(", "def _build_ui(", "def _wire_signals("]
            missing  = [m for m in required if m not in new_source]
            if missing:
                self.signals.error.emit(f"Critical sections missing after splice: {missing}")
                return

            # Validation 3: size sanity
            if len(new_source) < len(src) * 0.85:
                self.signals.error.emit(
                    f"New source too short ({len(new_source):,} vs {len(src):,}). Refusing."
                )
                return

            # Count changed lines
            diff_lines    = list(difflib.unified_diff(
                src.splitlines(), new_source.splitlines(), n=0
            ))
            changed_count = sum(
                1 for l in diff_lines
                if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
            )

            # Save patch
            self._emit_status("Saving patch…")
            ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
            patch_path = self._patch_dir / f"jarvis_patch_{ts}.py"
            patch_path.write_text(new_source, encoding="utf-8")

            diff_preview = self._make_diff(src, new_source, summary, reasoning)

            if changed_count < 20:
                self._emit_status(f"Small patch ({changed_count} lines) — auto-applying…")
                self.signals.auto_apply.emit(summary, str(patch_path))
            else:
                self._emit_status(f"Ready ({changed_count} lines changed): {summary[:40]}")
                self.signals.proposal_ready.emit(summary, diff_preview, str(patch_path))

        except Exception as e:
            self.signals.error.emit(f"{e}\n\n{traceback.format_exc()[:500]}")

    def apply(self, patch_path: str):
        try:
            ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = self._backup_dir / f"jarvis_v{ts}.py"
            shutil.copy2(self._src, backup)
            new_source = Path(patch_path).read_text(encoding="utf-8")
            self._src.write_text(new_source, encoding="utf-8")
            Path(patch_path).unlink(missing_ok=True)
            self.signals.applied.emit(str(backup))
        except Exception as e:
            self.signals.error.emit(f"Apply failed: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_state(self):
        try:
            if self._state_file.exists():
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                self._queue_idx = int(data.get("queue_idx", 0))
                self._rejected  = set(data.get("rejected", []))
        except Exception:
            pass

    def _save_state(self):
        try:
            data = {"queue_idx": self._queue_idx, "rejected": list(self._rejected)}
            self._state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _emit_status(self, msg: str):
        self.signals.status.emit(msg)

    @staticmethod
    def _extract_method(src: str, class_name: str, method_name: str):
        """Extract method by AST. Returns (snippet, start_line, end_line) or ("", 0, 0)."""
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return "", 0, 0

        lines = src.splitlines(keepends=True)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if class_name and node.name != class_name:
                continue
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if method_name and item.name != method_name:
                    continue
                start    = item.lineno
                siblings = [n for n in node.body if hasattr(n, "lineno") and n.lineno > start]
                end      = siblings[0].lineno if siblings else len(lines) + 1
                snippet  = "".join(lines[start - 1:end - 1])
                return snippet, start, end - 1
        return "", 0, 0

    @staticmethod
    def _make_diff(old: str, new: str, summary: str, reasoning: str) -> str:
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff      = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile="jarvis (current)",
            tofile="jarvis (proposed)",
            n=2,
        ))
        changed = len([l for l in diff if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))])
        header  = [
            f"SUMMARY:   {summary}\n",
            f"REASONING: {reasoning}\n",
            f"{'─'*60}\n",
            f"CHANGED LINES ({changed} total):\n",
            f"{'─'*60}\n",
        ]
        body   = diff[:80]
        suffix = [f"\n… ({len(diff)-80} more diff lines)"] if len(diff) > 80 else []
        return "".join(header + body + suffix)
