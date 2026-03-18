"""
tools/system_tools.py — System health and disk tools.
"""
from __future__ import annotations
from datetime import datetime


def _safe_path(raw_path: str, base_dir: str = None) -> str:
    """Resolve path and verify it stays within allowed base directory."""
    import pathlib
    from config import ROOT_DIR
    base = pathlib.Path(base_dir).resolve() if base_dir else ROOT_DIR.resolve()
    resolved = (base / raw_path).resolve()
    if not str(resolved).startswith(str(base)):
        raise ValueError(f"path traversal attempt: {raw_path!r} escapes {base}")
    return str(resolved)


def tool_system_status() -> str:
    try:
        import psutil
        cpu  = psutil.cpu_percent(interval=0.3)
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        boot = datetime.fromtimestamp(psutil.boot_time())
        up   = datetime.now() - boot
        hrs, mins = int(up.total_seconds() // 3600), int((up.total_seconds() % 3600) // 60)
        nets = []
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == 2:
                    nets.append(f"  {name}: {a.address}")
        return (
            f"CPU: {cpu}% ({psutil.cpu_count(logical=True)} logical cores)\n"
            f"Memory: {mem.percent:.1f}% used  "
            f"({mem.used // 1024**3} GB / {mem.total // 1024**3} GB)\n"
            f"Disk:   {disk.percent:.1f}% used  "
            f"({disk.used // 1024**3} GB / {disk.total // 1024**3} GB)\n"
            f"Uptime: {hrs}h {mins}m\n"
            f"Network:\n" + "\n".join(nets[:8])
        )
    except ImportError:
        return "psutil not installed — run: pip install psutil"
    except Exception as e:
        return f"Status error: {e}"


def tool_cleanup_disk() -> str:
    """Delete temp files and empty Recycle Bin. Returns before/after disk report."""
    from tools.shell_tools import tool_run_command
    steps = []

    before = tool_run_command(
        r"(Get-PSDrive C).Free / 1GB | ForEach-Object { [math]::Round($_, 2) }",
        confirmed=True,
    )
    steps.append(f"Free before: {before.strip()} GB")

    r1 = tool_run_command(
        r'Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue; "ok"',
        confirmed=True,
    )
    steps.append(f"User temp: {'cleared' if 'ok' in r1 else r1[:120]}")

    r2 = tool_run_command(
        r'Remove-Item "C:\Windows\Temp\*" -Recurse -Force -ErrorAction SilentlyContinue; "ok"',
        confirmed=True,
    )
    steps.append(f"Windows temp: {'cleared' if 'ok' in r2 else r2[:120]}")

    r3 = tool_run_command(
        r'Clear-RecycleBin -Force -ErrorAction SilentlyContinue; "ok"',
        confirmed=True,
    )
    steps.append(f"Recycle Bin: {'emptied' if 'ok' in r3 else r3[:120]}")

    after = tool_run_command(
        r"(Get-PSDrive C).Free / 1GB | ForEach-Object { [math]::Round($_, 2) }",
        confirmed=True,
    )
    steps.append(f"Free after:  {after.strip()} GB")

    return "\n".join(steps)


def tool_get_network_interfaces() -> str:
    try:
        import psutil
        lines = []
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == 2:  # AF_INET
                    lines.append(f"  {name}: {a.address}")
        return "Network interfaces:\n" + ("\n".join(lines) or "  (none)")
    except ImportError:
        return "psutil not installed."
    except Exception as e:
        return f"Error: {e}"


def tool_get_active_connections() -> str:
    try:
        import psutil
        conns = psutil.net_connections(kind="inet")
        lines = []
        for c in conns[:20]:
            laddr = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "-"
            raddr = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "-"
            lines.append(f"  {c.status:12s} {laddr:22s} → {raddr}")
        return "Active connections:\n" + ("\n".join(lines) or "  (none)")
    except ImportError:
        return "psutil not installed."
    except Exception as e:
        return f"Error: {e}"


def tool_get_processes() -> str:
    try:
        import psutil
        procs = sorted(
            psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]),
            key=lambda p: (p.info.get("cpu_percent") or 0),
            reverse=True,
        )[:15]
        lines = []
        for p in procs:
            mi  = p.info.get("memory_info")
            mem = round(mi.rss / 1024**2, 1) if mi else 0
            lines.append(
                f"  [{p.info['pid']:6d}] {(p.info.get('name') or '?')[:30]:30s}"
                f"  cpu={p.info.get('cpu_percent', 0):5.1f}%  mem={mem}MB"
            )
        return "Top processes:\n" + "\n".join(lines)
    except ImportError:
        return "psutil not installed."
    except Exception as e:
        return f"Error: {e}"


def tool_get_disk_usage() -> str:
    try:
        import psutil
        lines = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(
                    f"  {part.device:10s}  {usage.percent:5.1f}% used  "
                    f"({usage.used // 1024**3}GB / {usage.total // 1024**3}GB)"
                )
            except PermissionError:
                pass
        return "Disk usage:\n" + ("\n".join(lines) or "  (none)")
    except ImportError:
        return "psutil not installed."
    except Exception as e:
        return f"Error: {e}"


def tool_get_system_summary() -> str:
    return tool_system_status()


def tool_list_directory(path: str = ".") -> str:
    import os
    try:
        path = _safe_path(path)
        entries = os.listdir(path)
        lines = []
        for e in sorted(entries)[:50]:
            full = os.path.join(path, e)
            marker = "/" if os.path.isdir(full) else ""
            lines.append(f"  {e}{marker}")
        return f"Directory: {path}\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing {path}: {e}"


def tool_kill_process(pid: int) -> str:
    try:
        import psutil
        p = psutil.Process(int(pid))
        name = p.name()
        p.terminate()
        return f"Process {pid} ({name}) terminated."
    except Exception as e:
        return f"Could not kill {pid}: {e}"


def tool_write_file(path: str, content: str) -> str:
    try:
        path = _safe_path(path)
        if len(str(content)) > 1_000_000:  # 1MB max
            return {"error": "content too large (max 1MB)"}
        from pathlib import Path
        Path(path).write_text(content, encoding="utf-8")
        return f"File written: {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


def tool_delete_file(path: str) -> str:
    try:
        path = _safe_path(path)
        import os
        os.remove(path)
        return f"File deleted: {path}"
    except Exception as e:
        return f"Error deleting {path}: {e}"


def tool_read_file(path: str) -> str:
    try:
        path = _safe_path(path)
        from pathlib import Path
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return content[:4000]
    except Exception as e:
        return f"Error reading {path}: {e}"


def tool_self_reflect(aspect: str = "capabilities") -> str:
    """
    JARVIS reflects honestly on his own capabilities and limitations.
    Called when operator asks what JARVIS can/can't do.
    """
    a = aspect.lower()
    if any(w in a for w in ("can't", "cannot", "not", "limit", "missing", "what can't")):
        return (
            "What I cannot do yet, sir:\n"
            "  1. See the room — camera module exists but VISION_ENABLED is False\n"
            "  2. Browse the web autonomously — Playwright integration not fully wired\n"
            "  3. Submit reports without your review — by design, this is permanent\n"
            "  4. Access your email — requires OAuth setup in Settings\n"
            "  5. Learn during our conversation — memory updates after, not during\n"
            "  6. Run on another machine — requires this GPU and audio stack on Windows\n"
            "  7. Self-modify without your approval — by design, permanent\n\n"
            "What's coming:\n"
            "  - Room vision (camera dispatch ready to wire)\n"
            "  - Full internet access (Playwright dispatch ready)\n"
            "  - Presentation mode on second monitor\n"
            "  - Voice cloning with reference clips you record"
        )
    else:
        return (
            "What I can do right now, sir:\n"
            "  1. Hunt bug bounties within authorized scope — autonomously\n"
            "  2. Remember everything across sessions — 6-layer persistent memory\n"
            "  3. Run full recon pipelines — subfinder → httpx → nuclei\n"
            "  4. Draft H1-ready reports from confirmed findings\n"
            "  5. Monitor CVE feeds and correlate against your targets\n"
            "  6. Speak in 4 distinct voices — JARVIS, India, Morgan, Rex\n"
            "  7. Monitor system health every 60 seconds\n"
            "  8. Wake from sleep when you call me\n"
            "  9. Open and control your applications\n"
            " 10. Give morning briefings — weather, intel, findings"
        )


def tool_get_open_ports() -> str:
    from tools.shell_tools import tool_run_command
    return tool_run_command(
        "Get-NetTCPConnection -State Listen | Select-Object LocalPort,OwningProcess | Sort-Object LocalPort | Format-Table -AutoSize",
        confirmed=True,
    )


def tool_get_services() -> str:
    from tools.shell_tools import tool_run_command
    return tool_run_command(
        "Get-Service | Where-Object {$_.Status -eq 'Running'} | Select-Object Name,DisplayName | Format-Table -AutoSize",
        confirmed=True,
    )
