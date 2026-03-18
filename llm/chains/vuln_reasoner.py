"""
llm/chains/vuln_reasoner.py — CVE + tech stack -> attack hypothesis.

SECURITY: Never calls network tools directly. Analysis only.
All CVE data wrapped in wrap_untrusted() before LLM.
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
        logger.warning(f"[VulnReasoner] LLM call failed: {e}")
        return ""


def reason_vulnerability(cve_data: dict, tech_stack: str, target_url: str = "") -> dict:
    """
    Given CVE data + tech stack, generate an exploitation hypothesis.

    cve_data: dict with keys: cve_id, description, cvss_score, affected_versions
    Returns: hypothesis (str), confidence (float 0-1), exploit_steps (list)
    """
    safe_cve = wrap_untrusted(str(cve_data)[:2000], "cve_data")
    safe_tech = wrap_untrusted(tech_stack[:500], "tech_stack")
    target_ctx = f"Target URL: {target_url}\n" if target_url else ""

    prompt = (
        f"{target_ctx}Tech stack: {safe_tech}\n\n"
        f"CVE data:\n{safe_cve}\n\n"
        "Does this CVE apply to this tech stack? If yes:\n"
        "1. Explain why it applies\n"
        "2. Give 2-3 concrete test steps\n"
        "3. Rate confidence 0-10\n"
        "If no, say 'NOT APPLICABLE' and why."
    )
    system = (
        "You are a bug bounty hunter reasoning about CVE applicability. "
        "Be specific and actionable. Never suggest illegal or destructive actions."
    )
    response = _call_llm(prompt, system=system, fast=False)
    if not response:
        return {"ok": False, "hypothesis": "", "confidence": 0.0, "exploit_steps": [], "applicable": False}

    applicable = "NOT APPLICABLE" not in response.upper()
    import re
    confidence_match = re.search(r'confidence[:\s]+(\d+)/10', response, re.IGNORECASE)
    confidence = int(confidence_match.group(1)) / 10.0 if confidence_match else 0.5

    steps = [l.strip() for l in response.splitlines() if re.match(r'^\d+\.', l.strip())]

    return {
        "ok":            True,
        "hypothesis":    response[:500],
        "confidence":    confidence,
        "exploit_steps": steps,
        "applicable":    applicable,
        "cve_id":        cve_data.get("cve_id", ""),
    }


def tool_reason_vulnerability(cve_id: str = "", description: str = "", tech_stack: str = "", target_url: str = "") -> dict:
    """Tool: reason about CVE applicability to a target tech stack."""
    cve_data = {"cve_id": cve_id, "description": description}
    result = reason_vulnerability(cve_data, tech_stack, target_url)
    if not result["ok"]:
        return {"ok": False, "output": "LLM unavailable.", "error": "llm_error", "artifacts": [], "meta": {}}
    status = "APPLICABLE" if result["applicable"] else "NOT APPLICABLE"
    return {
        "ok":        True,
        "output":    f"{status} (confidence: {result['confidence']:.0%})\n{result['hypothesis'][:300]}",
        "error":     None,
        "artifacts": [],
        "meta":      result,
    }
