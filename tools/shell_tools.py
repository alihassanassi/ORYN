"""
tools/shell_tools.py — Shell command execution and app launcher.
"""
from __future__ import annotations
import re
import subprocess

from config import BLOCKED_COMMANDS, APP_MAP

# Allowlist of read-only / non-destructive commands that run without confirmation.
# Everything else requires the caller to pass confirmed=True.
_SAFE_COMMANDS = re.compile(
    r'^(?:'
    r'Get-Date|whoami|hostname|ipconfig(?:\s+/all)?|'
    r'Get-Process|Get-Service|Get-NetIPAddress|Get-NetAdapter|'
    r'systeminfo|ver|echo\s+|pwd|ls\b|dir\b|'
    r'Get-ChildItem|Get-Item|Get-Content|Test-Path|'
    r'python(?:\.exe)?\s+--version|pip\s+list|'
    r'git\s+(?:status|log|diff|branch)'
    r')(?:\s.*)?$',
    re.IGNORECASE,
)

# Error phrases that indicate failure even when PowerShell exits with code 0.
_FAIL_PHRASES = (
    "is not recognized as an internal or external command",  # cmd.exe
    "is not recognized as the name of a cmdlet",             # powershell
    "cannot be found",                                       # path not found
    "the system cannot find the path",
    "the system cannot find the file",
    "access is denied",
    "command not found",
    "no such file or directory",
)


def tool_run_command(command: str, confirmed: bool = False) -> str:
    for b in BLOCKED_COMMANDS:
        if b.lower() in command.lower():
            return f"BLOCKED: '{b}' is prohibited."
    if not confirmed and not _SAFE_COMMANDS.match(command.strip()):
        return f"CONFIRM:{command}"
    try:
        wrapped = f"$ErrorActionPreference='Stop'; {command}"
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", wrapped],
            capture_output=True, text=True, timeout=120,
        )
        stdout = r.stdout.strip()
        stderr = r.stderr.strip()

        if r.returncode != 0:
            detail = "\n".join(filter(None, [stdout, stderr]))
            if detail:
                return f"[FAILED — exit code {r.returncode}]\n{detail[:4000]}"
            return f"[FAILED — exit code {r.returncode}] Command produced no output."

        if stderr:
            sl = stderr.lower()
            if any(phrase in sl for phrase in _FAIL_PHRASES):
                detail = "\n".join(filter(None, [stdout, stderr]))
                return f"[FAILED — command error]\n{detail[:4000]}"

        out = stdout or stderr
        return out[:4000] if out else "(command completed, no output)"

    except subprocess.TimeoutExpired:
        return "Command timed out after 120 seconds."
    except Exception as e:
        return f"Execution error: {e}"


def tool_open_app(app: str) -> str:
    key = app.lower().strip()
    exe = APP_MAP.get(key)

    # Reject any app name not in APP_MAP — prevents arbitrary executable injection
    if exe is None:
        return (
            f"Application '{app}' is not in the approved APP_MAP. "
            f"Add it to config.APP_MAP to allow launching it."
        )

    # exe is from APP_MAP (trusted config) — split into list for safe Popen (no shell=True)
    # Paths with spaces are passed as a single element; no shell quoting needed.
    cmd_list = [exe]

    try:
        proc = subprocess.Popen(
            cmd_list,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            _, stderr_bytes = proc.communicate(timeout=0.6)
            err = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
            if proc.returncode != 0:
                return (
                    f"Failed to launch {app} (exit {proc.returncode})"
                    + (f": {err}" if err else ".")
                )
            return f"{app} launched."
        except subprocess.TimeoutExpired:
            try:
                proc.stderr.close()
            except Exception:
                pass
            return f"{app} launched."

    except FileNotFoundError:
        return (
            f"Could not launch {app}: executable not found. "
            f"Verify it is installed and the path in APP_MAP is correct."
        )
    except Exception as e:
        return f"Could not launch {app}: {e}"
