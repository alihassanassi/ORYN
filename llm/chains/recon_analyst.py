"""
llm/chains/recon_analyst.py — Multi-step analysis of raw scan results.

Chain:
  Step 1: Summarize raw data (fast model)
  Step 2: Identify anomalies (primary model)
  Step 3: Generate attack hypotheses (primary model)
  Step 4: Score hypotheses (fast model)

SECURITY: All tool output wrapped before LLM. No network calls.
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from security.sanitizer import wrap_untrusted
except ImportError:
    def wrap_untrusted(text: str, source: str = "external") -> str:
        return f"[{source}]\n{text[:4000]}"


def _call_llm(prompt: str, system: str = "", fast: bool = False) -> str:
    """Call LLM via client.complete(). Returns text or empty string on failure."""
    try:
        import config as _c
        model = getattr(_c, 'OLLAMA_MODEL', 'qwen3:14b')
        fast_model = getattr(_c, 'OLLAMA_JUDGE_MODEL', 'phi4-mini')
        use_model = fast_model if fast else model
        from llm.client import LLM
        client = LLM(model=use_model)
        messages = [{"role": "user", "content": prompt}]
        result = client.complete(messages, system=system)
        return result.get("content", "") or ""
    except Exception as e:
        logger.warning(f"[ReconAnalyst] LLM call failed: {e}")
        return ""


def analyze_scan_results(raw_output: str, target: str = "", tech_stack: str = "") -> dict:
    """
    Multi-step analysis of raw scan output.

    Returns structured dict with summary, anomalies, hypotheses, scored_hypotheses.
    Falls back gracefully if LLM unavailable.
    """
    safe_output = wrap_untrusted(raw_output[:6000], "scan_output")
    context = f"Target: {target}\nTech stack: {tech_stack}\n" if (target or tech_stack) else ""

    # Step 1: Summarize (fast model)
    summary = _call_llm(
        f"{context}Summarize these scan results in 3 bullet points. Be factual:\n\n{safe_output}",
        system="You are a security analyst. Summarize scan data concisely. No markdown headers.",
        fast=True,
    ) or "Summary unavailable."

    # Step 2: Anomalies (primary model)
    anomalies_raw = _call_llm(
        f"{context}Scan summary:\n{summary}\n\nList any anomalies or unexpected findings. "
        "Format: one anomaly per line starting with '- '",
        system="You are a bug bounty hunter. Identify security-relevant anomalies in scan data.",
        fast=False,
    ) or ""
    anomalies = [l.lstrip("- ").strip() for l in anomalies_raw.splitlines() if l.strip().startswith("-")]

    # Step 3: Attack hypotheses (primary model)
    hyp_raw = _call_llm(
        f"Anomalies found:\n{anomalies_raw or 'None identified'}\n\n"
        "Generate up to 3 specific attack hypotheses to test. "
        "Format: 'HYPOTHESIS: [type] - [specific test]'",
        system="You are a penetration tester. Generate testable attack hypotheses from scan anomalies.",
        fast=False,
    ) or ""
    hypotheses = [l.replace("HYPOTHESIS:", "").strip() for l in hyp_raw.splitlines() if "HYPOTHESIS:" in l]

    # Step 4: Score hypotheses (fast model)
    scored = []
    if hypotheses:
        score_prompt = (
            "Score each hypothesis by likelihood of finding a real bug (0-10):\n" +
            "\n".join(f"{i+1}. {h}" for i, h in enumerate(hypotheses)) +
            "\nRespond with: '1. [score]/10' per line."
        )
        scores_raw = _call_llm(score_prompt, fast=True) or ""
        import re
        score_map = {}
        for line in scores_raw.splitlines():
            m = re.search(r'(\d+)\.\s.*?(\d+)/10', line)
            if m:
                score_map[int(m.group(1)) - 1] = int(m.group(2))
        for i, h in enumerate(hypotheses):
            scored.append({"hypothesis": h, "score": score_map.get(i, 5)})
        scored.sort(key=lambda x: x["score"], reverse=True)

    return {
        "ok":                True,
        "target":            target,
        "summary":           summary,
        "anomalies":         anomalies,
        "hypotheses":        hypotheses,
        "scored_hypotheses": scored,
    }


def tool_analyze_scan_results(raw_output: str = "", target: str = "", tech_stack: str = "") -> dict:
    """Tool wrapper for analyze_scan_results."""
    if not raw_output:
        return {"ok": False, "output": "raw_output required.", "error": "missing_param", "artifacts": [], "meta": {}}
    result = analyze_scan_results(raw_output, target, tech_stack)
    top = result["scored_hypotheses"][:2] if result["scored_hypotheses"] else []
    summary_text = result["summary"] + (
        "\n\nTop hypotheses:\n" + "\n".join(f"  {h['hypothesis']} ({h['score']}/10)" for h in top)
        if top else ""
    )
    return {"ok": True, "output": summary_text, "error": None, "artifacts": [], "meta": result}
