"""
bridge/server.py — JARVIS FastAPI bridge server.

Provides:
  GET  /health              — watchdog health probe
  GET  /ops                 — OPS graph HTML page
  GET  /api/ops/graph       — live graph data (programs → domains → targets)
  GET  /ops-state           — current theme for browser sync
  GET  /api/jobs/pending    — Parrot VM polls for pending recon jobs (auth)
  POST /api/jobs/{id}/result — Parrot VM submits job results (auth)
  POST /api/findings        — Parrot VM submits new findings (auth)

Binds to 0.0.0.0:5000 — accessible from all lab machines.
Watchdog health check: http://127.0.0.1:5000/health
Parrot VM + laptop: http://192.168.0.111:5000
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
import time

# ── FastAPI import with clear error if missing ─────────────────────────────────
try:
    from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    print(
        "ERROR: fastapi is not installed.\n"
        "  Run: pip install fastapi uvicorn\n"
    )
    sys.exit(1)

logger = logging.getLogger(__name__)

# ── Path resolution ────────────────────────────────────────────────────────────
_HERE    = pathlib.Path(__file__).parent
_ROOT    = _HERE.parent
_STATIC  = _HERE / "static"
_INDEX   = _STATIC / "index.html"

# Add project root to sys.path so storage.db etc. are importable
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="JARVIS Bridge", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # S-02 fix: restricted to localhost only (server is local-only)
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_BOOT_TIME = time.time()


# ── Auth helper ────────────────────────────────────────────────────────────────

def _check_token(authorization: str | None) -> None:
    """Raises HTTP 401 if token is configured and doesn't match."""
    try:
        from config import _get_jarvis_token
        expected = _get_jarvis_token()
    except Exception:
        expected = os.environ.get("JARVIS_TOKEN")

    if not expected:
        return   # token not configured — open access (LAN-only server)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    if authorization.split(" ", 1)[1].strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "uptime_s": round(time.time() - _BOOT_TIME, 1)}


# ── OPS graph HTML page ────────────────────────────────────────────────────────

@app.get("/")
async def root():
    if _INDEX.exists():
        return FileResponse(str(_INDEX), media_type="text/html")
    return HTMLResponse("<h1>JARVIS Bridge Online</h1>", status_code=200)


@app.get("/ops")
async def ops_page():
    if _INDEX.exists():
        return FileResponse(str(_INDEX), media_type="text/html")
    return HTMLResponse("<h1>OPS graph page not found</h1>", status_code=404)


# ── Theme sync for browser ────────────────────────────────────────────────────

@app.get("/ops-state")
async def ops_state():
    try:
        from storage.settings_store import get as _get_setting
        theme = _get_setting("gui.theme") or "CIRCUIT"
    except Exception:
        theme = "CIRCUIT"
    return {"theme": theme, "status": "online"}


# ── OPS graph data ─────────────────────────────────────────────────────────────

@app.get("/api/ops/graph")
async def ops_graph():
    """Build a force-directed graph from the JARVIS DB for the ops page."""
    # Served localhost-only — same-origin as the AI CORE WebView, no token needed
    nodes: list[dict] = []
    edges: list[dict] = []
    finding_count = 0
    scanning = False

    try:
        from storage.db import get_db

        with get_db() as conn:
            # Programs → program nodes
            progs = conn.execute(
                "SELECT id, name, status, scope_domains FROM programs"
            ).fetchall()
            for pid, pname, pstatus, scope_json in progs:
                pnode_id = f"prog_{pid}"
                nodes.append({
                    "id":     pnode_id,
                    "type":   "program",
                    "label":  pname or f"Program {pid}",
                    "status": pstatus or "unknown",
                    "url":    "",
                })
                # Scope domains → domain nodes
                try:
                    domains = json.loads(scope_json or "[]")
                except Exception:
                    domains = []
                for dom in domains:
                    dom_clean = dom.lstrip("*.")
                    dnode_id  = f"dom_{dom_clean.replace('.', '_')}"
                    if not any(n["id"] == dnode_id for n in nodes):
                        nodes.append({
                            "id":     dnode_id,
                            "type":   "domain",
                            "label":  dom_clean,
                            "status": "scoped",
                            "url":    "",
                        })
                    edges.append({"source": pnode_id, "target": dnode_id})

            # Scan targets → subdomain/IP nodes
            targets = conn.execute(
                "SELECT DISTINCT target, project FROM scan_targets"
            ).fetchall()
            for target, project in targets:
                if not target:
                    continue
                import re as _re
                is_ip = bool(_re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", target))
                ttype = "ip" if is_ip else "subdomain"
                tnode_id = f"tgt_{target.replace('.', '_').replace(':', '_')}"
                if not any(n["id"] == tnode_id for n in nodes):
                    nodes.append({
                        "id":     tnode_id,
                        "type":   ttype,
                        "label":  target,
                        "status": "discovered",
                        "url":    "" if is_ip else f"https://{target}",
                    })
                # Try to link to matching domain node
                linked = False
                for n in nodes:
                    if n["type"] == "domain" and (
                        target.endswith("." + n["label"]) or target == n["label"]
                    ):
                        edges.append({"source": n["id"], "target": tnode_id})
                        linked = True
                        break
                if not linked and project:
                    # Link to any program node (fallback)
                    for n in nodes:
                        if n["type"] == "program":
                            edges.append({"source": n["id"], "target": tnode_id})
                            break

            # Finding count
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM findings_canonical"
                ).fetchone()
                finding_count = row[0] if row else 0
            except Exception:
                finding_count = 0

            # Scanning status — any job currently running?
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status='running'"
                ).fetchone()
                scanning = (row[0] or 0) > 0
            except Exception:
                scanning = False

    except Exception as exc:
        logger.warning("[Bridge] graph query failed: %s", exc)

    return {
        "nodes":         nodes,
        "edges":         edges,
        "finding_count": finding_count,
        "scanning":      scanning,
    }


# ── Parrot VM job dispatch ─────────────────────────────────────────────────────

@app.get("/api/jobs/pending")
async def get_pending_jobs(
    limit: int = 5,
    authorization: str | None = Header(default=None),
):
    """Parrot VM polls this to get pending recon jobs."""
    _check_token(authorization)
    try:
        from scheduler.recon_scheduler import get_pending_jobs
        jobs = get_pending_jobs(limit=limit)
        return {"jobs": jobs}
    except Exception as exc:
        logger.error("[Bridge] get_pending_jobs error: %s", exc)
        return {"jobs": []}


@app.post("/api/jobs/{job_id}/result")
async def submit_job_result(
    job_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Parrot VM posts tool output (subdomains, services, etc.) for a job."""
    _check_token(authorization)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    status   = body.get("status", "completed")   # "completed" or "failed"
    output   = body.get("output", {})            # tool results dict

    try:
        from scheduler.recon_scheduler import mark_job_complete
        from storage.db import get_db

        # Save raw output as scan targets if subdomains returned
        subdomains = output.get("subdomains") or []
        if subdomains:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT program_id, domain FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
                if row:
                    prog_id, domain = row
                    for sub in subdomains[:200]:   # cap at 200 per job
                        sub = sub.strip()
                        if sub:
                            conn.execute(
                                "INSERT OR IGNORE INTO scan_targets "
                                "(project, target, notes, created_at) "
                                "VALUES (?, ?, ?, datetime('now'))",
                                (f"prog_{prog_id}", sub, f"discovered via subfinder job {job_id}")
                            )

        mark_job_complete(job_id, status)
        logger.info("[Bridge] job %d marked %s — %d subdomains saved",
                    job_id, status, len(subdomains))
        return {"ok": True}
    except Exception as exc:
        logger.error("[Bridge] submit_job_result error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/findings")
async def submit_finding(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Parrot VM submits a raw finding for triage by FindingEngine."""
    _check_token(authorization)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    try:
        from autonomy.finding_engine import FindingEngine
        fe = FindingEngine()
        result = fe.process_raw_finding(body)
        return {"ok": True, "result": result}
    except Exception as exc:
        logger.error("[Bridge] submit_finding error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── WebSocket chat ─────────────────────────────────────────────────────────────

from typing import List as _List
_ws_clients: _List[WebSocket] = []


def _route_to_jarvis(text: str) -> None:
    """Write a user message to the DB for JARVIS to pick up."""
    try:
        from storage.db import get_db
        with get_db() as conn:
            conn.execute(
                "INSERT INTO messages (project, role, content, ts) "
                "VALUES (?, 'user', ?, datetime('now'))",
                ("ops_bridge", text),
            )
    except Exception as exc:
        logger.warning("[Bridge] chat route failed: %s", exc)


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket, token: str = ""):
    """WebSocket endpoint for the neural-map chat panel."""
    try:
        from config import _get_jarvis_token
        expected = _get_jarvis_token()
    except Exception:
        expected = os.environ.get("JARVIS_TOKEN")

    if expected and token != expected:
        await ws.close(code=4001)
        return

    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            data = await ws.receive_text()
            try:
                import json as _json
                msg = _json.loads(data)
                _route_to_jarvis(msg.get("text", ""))
            except Exception as exc:
                logger.warning("[Bridge] ws_chat parse error: %s", exc)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("[Bridge] ws_chat error: %s", exc)
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


@app.websocket("/ws")
async def ws_alias(ws: WebSocket):
    """
    Token-free alias for the local OPS-graph UI.
    The page is served from this same localhost server so it is inherently trusted.
    Full token auth is still enforced on /ws/chat for external clients.
    """
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            data = await ws.receive_text()
            try:
                import json as _json
                msg = _json.loads(data)
                _route_to_jarvis(msg.get("text", ""))
            except Exception as exc:
                logger.warning("[Bridge] ws error: %s", exc)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("[Bridge] ws error: %s", exc)
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


@app.post("/api/chat")
async def api_chat(request: Request):
    """HTTP POST fallback for the neural-map chat panel."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    _route_to_jarvis(payload.get("text", ""))
    return {"ok": True}


# ── Static file fallback ───────────────────────────────────────────────────────

@app.get("/static/{filename}")
async def static_file(filename: str):
    path = _STATIC / filename
    if path.exists() and path.is_file():
        return FileResponse(str(path))
    raise HTTPException(status_code=404, detail="Not found")


# ── Entrypoint (called by watchdog via: python -m bridge.server) ──────────────

if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        print("ERROR: uvicorn not installed. Run: pip install uvicorn")
        sys.exit(1)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print(f"[Bridge] Starting on 0.0.0.0:5000")
    print(f"[Bridge] OPS graph: http://192.168.0.111:5000/ops")
    print(f"[Bridge] Health:    http://127.0.0.1:5000/health")

    uvicorn.run(
        "bridge.server:app",
        host="0.0.0.0",
        port=5000,
        log_level="warning",
        access_log=False,
    )
