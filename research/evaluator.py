from __future__ import annotations

_SEV_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

# VRAM requirements for known model sizes (GB)
_VRAM_MAP = {
    "3b": 2.5, "7b": 4.5, "8b": 5.0, "9b": 6.0,
    "12b": 7.5, "14b": 9.0, "27b": 16.0, "32b": 20.0,
    "70b": 40.0, "72b": 45.0,
    "mini": 3.0, "scout": 8.0, "maverick": 24.0,
}

_RECOMMENDED_FAMILIES = {"qwen3", "gemma3", "phi4", "llama4", "deepseek", "mistral"}


class LLMEvaluator:
    """Evaluates new LLM releases against JARVIS hardware constraints.

    RTX 4070 Ti Super: 16GB VRAM.
    Reserve 4GB for Chatterbox TTS → 12GB usable for LLM.
    """

    def evaluate(self, item: dict) -> dict:
        model = (item.get("title") or item.get("raw", {}).get("model", "")).lower()

        # Estimate VRAM from model name
        vram = 99.0
        for tag, gb in sorted(_VRAM_MAP.items(), key=lambda x: len(x[0]), reverse=True):
            if tag in model:
                vram = gb
                break

        fits = vram <= 12.0
        recommended = fits and any(fam in model for fam in _RECOMMENDED_FAMILIES)

        if fits:
            recommendation = (
                f"Fits in 16GB VRAM (~{vram}GB). "
                f"Run: ollama pull {item.get('title', model)}"
            )
        else:
            recommendation = (
                f"Requires ~{vram}GB VRAM — exceeds available headroom "
                f"(12GB after Chatterbox reservation)."
            )

        return {
            "vram_gb":        vram,
            "fits_hardware":  fits,
            "recommended":    recommended,
            "recommendation": recommendation,
        }


def classify_severity(cvss_score: float | None) -> str:
    if cvss_score is None:
        return "info"
    s = float(cvss_score)
    if s >= 9.0:  return "critical"
    if s >= 7.0:  return "high"
    if s >= 4.0:  return "medium"
    if s > 0.0:   return "low"
    return "info"


def should_surface(item: dict, targets: list[str]) -> bool:
    sev = item.get("severity", "info").lower()
    if sev in ("critical", "high"):
        return True
    if item.get("affects_targets", 0):
        return True
    title = (item.get("title") or "").lower()
    for t in targets:
        if t and t.lower() in title:
            return True
    return False


def get_digest_text(items: list[dict], persona: str = "jarvis") -> str:
    if not items:
        return "Intelligence queue is clear. No unactioned research items."
    total     = len(items)
    critical  = sum(1 for i in items if i.get("severity") == "critical")
    high      = sum(1 for i in items if i.get("severity") == "high")
    targeted  = sum(1 for i in items if i.get("affects_targets", 0))
    top = sorted(items, key=lambda x: _SEV_ORDER.get(x.get("severity", "info"), 0), reverse=True)[:3]
    top_titles = "; ".join(i.get("title", "untitled")[:80] for i in top)
    parts = [f"Intelligence queue has {total} unactioned item(s)."]
    if critical:
        parts.append(f"{critical} critical severity.")
    if high:
        parts.append(f"{high} high severity.")
    if targeted:
        parts.append(f"{targeted} affect active targets.")
    parts.append(f"Top items: {top_titles}.")
    return " ".join(parts)
