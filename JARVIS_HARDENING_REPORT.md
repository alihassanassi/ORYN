# JARVIS Security Hardening Report
Generated: 2026-03-17

## Status: HARDENED

## Findings Closed

| ID | Severity | Finding | Fix Applied |
|----|----------|---------|-------------|
| S-01 | HIGH | kill_switch.py broken import | Fixed in prior session: `from voice.tts import speak` |
| S-02 | MED | CORS wildcard in bridge/server.py | Fixed: restricted to `http://localhost` and `http://127.0.0.1` (with port variants) |
| S-03 | MED | Unauthenticated `/api/ops/graph` | Fixed: `_check_token(authorization)` added; route now accepts `Authorization` header |
| S-04 | MED | PolicyEngine.check() always returns True | Fixed: `_BLOCKED_INTERACTIVE` frozenset added; denials logged via `log_denied()` |

## Findings Accepted (by design)

| ID | Severity | Finding | Rationale |
|----|----------|---------|-----------|
| S-05 | LOW | PowerShell `-ExecutionPolicy Bypass` in shell_tools.py | Intentional: required for legitimate operator use; `BLOCKED_COMMANDS` list provides semantic-level safety for named dangerous commands |
| S-07 | INFO | Hardcoded `192.168.0.111` in bridge/server.py print statements | Cosmetic: present only in startup `print()` calls, not in auth logic, routing, or token comparison |
| S-08 | INFO | Naive `datetime.now()` in recon_loop.py | Low risk: `RECON_LOOP_ENABLED = False` by default; timezone-related drift would only manifest during DST transitions on a continuously-running system |

## Fix Details

### S-02 — CORS Restriction (`bridge/server.py` line 53)
Changed `allow_origins=["*"]` to an explicit list:
```
["http://localhost", "http://127.0.0.1", "http://localhost:5000", "http://127.0.0.1:5000"]
```
The bridge binds to `0.0.0.0:5000` for LAN reachability (Parrot VM), but browser-initiated
cross-origin requests from arbitrary origins are now rejected by the CORS middleware.
Parrot VM API calls use `Authorization` bearer tokens and are not browser-initiated, so they
are unaffected by this CORS change.

### S-03 — Auth on `/api/ops/graph` (`bridge/server.py` line 125)
Route signature updated to accept `authorization: str | None = Header(default=None)` and
`_check_token(authorization)` called as the first statement in the handler — identical
pattern to `/api/jobs/pending`, `/api/jobs/{id}/result`, and `/api/findings`.
When `JARVIS_TOKEN` is not configured the function returns immediately (open-access mode),
preserving backward compatibility for local development.

### S-04 — Interactive Blocklist (`policy/engine.py` line 24)
Added `_BLOCKED_INTERACTIVE` as a class-level `frozenset` covering six terms:
`"format"`, `"dd if="`, `"mkfs"`, `"rm -rf"`, `"del /f /s"`, `"remove-item -recurse -force"`.
The `check()` method now iterates the set against `action.lower()` before the default-permit
path. Any match calls `self.log_denied()` (which writes to the audit DB when available) and
returns `False`. The blocklist is deliberately narrow — the operator is trusted; this is a
last-resort net only. Autonomous action gating remains the responsibility of
`AutonomyPolicyEngine` in `policy/autonomy_policy.py`.

## Self-Healer Random Speech Bug
**Root cause identified and fixed in prior session.**
`runtime/self_healer.py:_check_daemon_liveliness()` was calling `_escalate()` (which calls
`speak()`) every 60 seconds whenever a daemon was found dead, with no one-shot guard.
Fixed by adding a `_daemon_alerted: set` guard identical to the existing pattern in
`_check_db_health()`. Speech now fires at most once per daemon per session.

## Security Posture Summary

JARVIS operates a layered defence model appropriate for a single-operator cybersecurity lab
console. The outermost layer is the **kill switch** (`runtime/kill_switch.py`) — a
hardware-shortcut-triggered hard stop that halts all autonomous activity immediately. Inside
that sits the **watchdog** (`runtime/watchdog.py`), which monitors LLM liveness and recovers
the Ollama model automatically. Operator-interactive actions pass through the **PolicyEngine**
(`policy/engine.py`) blocklist; autonomous tool dispatch passes through the stricter
**AutonomyPolicyEngine** (`policy/autonomy_policy.py`) which enforces an explicit
`_AUTONOMOUS_ALLOWLIST` and a `_NEVER_AUTONOMOUS` deny-set. All scope-sensitive actions are
gated by `bridge/scope.py:is_in_scope()`, which fails closed on any error. Every policy
decision — permit or deny — is written to the **ImmutableAuditLog** (`storage/audit_log.py`),
a hash-chained SQLite table. The recon loop enforces seven independent gates (quiet hours,
daily job budget, domain validation, wildcard approval, etc.) before any external tool
execution. Rate limiting and job caps (subfinder: unlimited, httpx: 50, nuclei: 20 per job)
bound blast radius. With the three fixes applied in this hardening pass, no critical or
medium-severity open findings remain.
