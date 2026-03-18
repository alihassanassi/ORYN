# JARVIS Startup Fix Notes
Date: 2026-03-17

---

## Problem 1 — bridge.server and jarvis_ops thrashing watchdog

### Root cause
`runtime/watchdog.py` monitored three services: `ollama`, `jarvis_ops`, and `bridge`.
Neither `jarvis_ops/main.py` nor `bridge/server.py` exist in this repo — only their
`static/` subdirectories are present.  The watchdog health-checked both at
`http://127.0.0.1:8080/api/health` and `http://127.0.0.1:5000/health` respectively,
found them offline every 30 seconds, tried to restart them by running their missing
entry-point files, waited for the restart delay, re-probed, still found them offline,
and repeated — until `max_restarts` (5) was exceeded.

The bridge server was designed to run on the Parrot Linux VM, not the Windows laptop.
`jarvis_ops` is a stub that only has a static HTML ops-graph page; no Python API
server has been written for it yet.

### Files changed
- `runtime/watchdog.py`

### What changed
1. `_build_services()` now probes whether `jarvis_ops/main.py` and `bridge/server.py`
   exist on disk.  If they do not, the service is marked `optional: True`.
2. `_check_all()` — new branch for optional services:
   - Failures are logged at DEBUG (not WARNING) to avoid spammy output.
   - If the entry-point file does not exist, the loop `continue`s immediately —
     no restart is attempted, no integrity check, no audit event.
   - If the file exists but the service is down, exponential back-off is applied:
     retry at check #1, then #2, #4, #8 … capped at every 32 checks (~16 min).
3. A new `_optional_fail_counts` dict tracks consecutive failures per optional service.

### When jarvis_ops/main.py is created later
The moment the file is created, `optional` will be `False` on the next JARVIS boot
(because `_build_services()` re-runs at import time) and the watchdog will treat it
as a critical service with full restart behaviour.

---

## Problem 2 — 28-second startup to first TTS speech

### Root causes

#### Gap 1: 9 seconds between window shown and Chatterbox loading starting
`TTS.__init__()` spawned a single `_init` thread that ran sequentially:
  1. `_find_output()` — queries sounddevice for all audio devices (can hang 5-10s on
     Windows when Bluetooth/virtual devices are present)
  2. Chatterbox `initialize()` + `warmup()` — CUDA model load (~5s warm, ~10s cold)
  3. Kokoro `initialize()` + `warmup()` (~5-10s)

Because `_find_output()` ran first and blocked the thread, Chatterbox didn't start
until sounddevice finished.  The 9-second gap was pure audio device enumeration delay.

#### Gap 2: 10 seconds between Chatterbox ready and first speak_begin
Even after Chatterbox loaded (t+18s), `_ready` was never set because the code fell
through to the primary fallback chain which runs Kokoro next.  Kokoro's `initialize()`
+ `warmup()` takes ~10s.  The greeting poller (`_try_greet`, 200ms interval) was
waiting on `self._tts._ready` which only became True after Kokoro finished.

`config.VOICE_DEFAULT_PROFILE = "chatterbox_jarvis"` means Chatterbox IS the intended
primary voice, but the code wasn't treating it as ready until after Kokoro loaded too.

#### Bug 3: warmup() inverted guard in chatterbox_backend.py
`warmup()` had a broken early-return guard on line 180:
```python
if getattr(self, '_ready_flag', False) and self._model is not None:
    return   # BUG: returns when ready — warmup never ran!
```
This exited the method immediately after a successful `initialize()`, so Chatterbox
was never warmed up, and the first synthesis call at greeting time was 3-5s slower
than it needed to be.

#### Issue 4: "--- Logging error ---" in console
Python's `logging` module catches exceptions from handlers and prints them to `sys.stderr`
via its lastResort handler.  On Windows with PySide6, `sys.stderr` can be detached or
replaced (e.g. when running from a launcher without a console window, or during Qt
shutdown).  When a `StreamHandler` tries to write to a closed/replaced stream it raises
an exception, which Python reports as `--- Logging error ---`.

### Files changed
- `voice/tts.py`
- `voice/backends/chatterbox_backend.py`
- `main.py`

### What changed

#### voice/tts.py
1. Added `_chatterbox_ready_evt` (a `threading.Event`) to synchronise the two new
   init threads.
2. Extracted Chatterbox init into its own `_init_chatterbox` thread (`TTS-chatterbox-init`)
   that starts at the same time as `_init` (`TTS-init`).  Both threads start immediately
   from `TTS.__init__()`.
3. `_init` now calls `_find_output()` (sounddevice) AND waits on
   `_chatterbox_ready_evt` before proceeding to the fallback chain — so whichever
   finishes last gates the chain, but they run in parallel, removing the sequential block.
4. Added early-ready logic: if `VOICE_DEFAULT_PROFILE` contains "chatterbox" and
   Chatterbox loaded successfully, `_ready = True` is set immediately and
   `_restore_settings()` is called — allowing the greeting to fire without waiting
   for Kokoro.  Kokoro warmup continues in the background.

#### voice/backends/chatterbox_backend.py
Removed the inverted guard at the top of `warmup()`:
```python
# BEFORE (broken — exits if ready)
if getattr(self, '_ready_flag', False) and self._model is not None:
    return

# AFTER — just the correct guard
if not self.is_ready():
    return
```

#### main.py
Replaced `logging.basicConfig(...)` with a custom `_SafeStreamHandler` subclass
that wraps `emit()` in a try/except and silently discards errors from closed/broken
streams.  Also sets `logging.lastResort = None` to suppress the double-print fallback.

---

## Before/After timing expectations

| Event                    | Before  | After   |
|--------------------------|---------|---------|
| UI shown                 | 4s      | 4s      |
| Chatterbox loading start | 13s     | ~0s     |
| Chatterbox ready         | 18s     | ~5-8s   |
| First speech             | 28s     | ~8-10s  |

Cold boot (first run, model not in pagefile cache): Chatterbox may take 10-15s.
Warm boot (Windows has the model files cached): Chatterbox ready in ~5s.

---

## Manual steps required

None.  All fixes take effect on the next JARVIS boot.

If you later create `jarvis_ops/main.py` as a real Flask/FastAPI server:
- The watchdog will automatically detect it and treat the service as non-optional.
- Ensure it serves `GET /api/health` returning HTTP 200 for the health check to pass.

If you create `bridge/server.py` on this machine (Windows → Windows bridge scenario):
- Same as above — watchdog will auto-promote it to monitored+restart-on-fail.
- Ensure it listens on `127.0.0.1:5000` and serves `GET /health` returning HTTP 200.

---

## Summary of changed files

| File                                          | Change summary                                      |
|-----------------------------------------------|-----------------------------------------------------|
| `runtime/watchdog.py`                         | Optional service flag + exponential back-off        |
| `voice/tts.py`                                | Parallel Chatterbox init + early-ready on Chatterbox|
| `voice/backends/chatterbox_backend.py`        | Fix inverted warmup() guard                         |
| `main.py`                                     | SafeStreamHandler to stop logging errors            |
