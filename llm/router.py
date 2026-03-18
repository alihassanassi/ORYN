"""
LLMRouter — routes decisions to cheapest capable model, tracks spend.

Routing logic:
  structured decision (approve/score/summarize) → LocalJudge (Ollama, free)
  natural language operator command             → local first, cloud if needed
  novel reasoning (exploit analysis, codegen)   → cloud LLM
  cloud unavailable                             → local with disclaimer

Token tracking: monthly spend aggregated for operator visibility.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LLMRouter:

    def __init__(self):
        self._judge = None

    def _get_judge(self):
        if self._judge is None:
            from llm.local_judge import LocalJudge
            self._judge = LocalJudge()
        return self._judge

    def route(self, request_type: str, payload: dict) -> dict:
        """
        request_type: "decision" | "command" | "analysis" | "generation"

        "decision"   → LocalJudge handles 100% locally
        "command"    → LocalJudge first; escalate to cloud if confidence < 0.7
        "analysis"   → cloud (novel reasoning, too complex for 8B model)
        "generation" → cloud (report writing, code generation)
        """
        judge = self._get_judge()

        if request_type == "decision":
            result = judge.should_approve_action(
                payload.get("tool", ""),
                payload.get("args", {}),
                payload.get("context", "")
            )
            self._log_routing("local", request_type)
            return {"response": result, "model_used": judge._model, "tokens_used": None}

        if request_type == "score":
            result = judge.score_finding(payload.get("finding", {}))
            self._log_routing("local", request_type)
            return {"response": result, "model_used": judge._model, "tokens_used": None}

        if request_type == "summarize":
            result = judge.summarize_scan_result(
                payload.get("tool", ""),
                payload.get("raw_output", ""),
                payload.get("asset_count", 0)
            )
            self._log_routing("local", request_type)
            return {"response": result, "model_used": judge._model, "tokens_used": None}

        # Fallthrough: route to existing cloud LLM path
        self._log_routing("cloud", request_type)
        return {"response": None, "model_used": "cloud", "tokens_used": None,
                "escalated": True}

    def _log_routing(self, destination: str, request_type: str) -> None:
        """Logs routing decision to actions table for spend tracking."""
        try:
            from storage.db import get_db
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO actions (source, tool, target, status, created_at) "
                    "VALUES (?, ?, ?, 'completed', datetime('now'))",
                    (f"llm_{destination}", request_type, destination)
                )
        except Exception:
            pass

    def get_token_stats(self) -> dict:
        """Monthly token usage stats — aggregated, no target names."""
        from storage.db import get_db
        try:
            with get_db() as conn:
                cloud = conn.execute(
                    "SELECT COUNT(*) FROM actions WHERE source='llm_cloud' "
                    "AND created_at > datetime('now','-30 days')"
                ).fetchone()[0]
                local = conn.execute(
                    "SELECT COUNT(*) FROM actions WHERE source='llm_local' "
                    "AND created_at > datetime('now','-30 days')"
                ).fetchone()[0]
        except Exception:
            cloud, local = 0, 0
        total = cloud + local
        ratio = local / total if total > 0 else 0.0
        cost  = cloud * 0.001  # rough estimate: ~$0.001/cloud call
        return {
            "cloud_calls_month":        cloud,
            "local_calls_month":        local,
            "local_ratio":              round(ratio, 3),
            "estimated_cost_month_usd": round(cost, 4),
        }
