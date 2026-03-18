# ORYN
### Autonomous Cybersecurity Operations Console

> Local-first. Voice-interactive. Fails-closed.
> Built for bug bounty research. No cloud. No telemetry. All yours.

---

## What This Is

ORYN is a production-grade autonomous cybersecurity console that runs
entirely on local hardware. It integrates a dual-model LLM stack,
a four-backend voice synthesis pipeline, a six-layer persistent memory
system, and a seven-gate serial safety chain that governs all autonomous
recon activity.

**143 Python files. 50+ tools. 16-step boot. 23 security fixes.**
Built by one person in seven days.

---

## Architecture

```
Layer 5 — Autonomy      autonomy/ · scheduler/ · runtime/ · policy/
Layer 4 — Interface     gui/ (PySide6, 8-tab panel, 4 personas)
Layer 3 — Execution     agents/ · tools/ · voice/ · llm/ · bridge/
Layer 2 — State/Memory  storage/ · memory/ (6-layer persistent)
Layer 1 — Configuration config.py · security/ · policy/
```

---

## Key Features

- **Dual-model LLM** — qwen3:14b reasoning + phi4-mini fast decisions
- **4-backend voice pipeline** — Chatterbox → Kokoro → Piper → SAPI
- **6-layer persistent memory** — learns operator patterns across sessions
- **7-gate safety chain** — every autonomous action fails-closed
- **50+ registered tools** — recon, finding, reporting, memory, system
- **4 AI personas** — each with distinct voice and personality
- **Hash-chained audit trail** — every action logged, tamper-detectable
- **VM bridge** — dispatches recon tools to Parrot Linux via FastAPI

---

## Safety Model

ORYN is built fails-closed. Every security boundary defaults to deny.

- `RECON_LOOP_ENABLED = False` by default
- `HUNT_AUTO_APPROVE_THRESHOLD = 0.0` — permanent
- No report ever submitted without explicit operator review
- Kill switch: filesystem sentinel + Python state, manual reset required

Read `ARCHITECTURE.md` before touching anything.

---

## Hardware Target

Intel i7-14700F · 64GB DDR5 · RTX 4070 Ti Super 16GB

---

## Research

This system is the subject of the paper:
**"ORYN: Architecture of a Local-First Autonomous Cybersecurity Console"**
*Ali Hassan Assi · Independent Researcher · 2026*

---

## Author

**Ali Hassan Assi**
Independent Researcher · San Diego, CA

*Built because the tools didn't exist yet.*

---

> *"One person. Seven days. These files."*
