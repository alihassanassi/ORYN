"""
llm/client.py — Ollama LLM client via OpenAI-compatible REST API.

Primary model: qwen3:14b — native tool/function calling, 128K ctx, ~60 t/s on RTX 4070 Ti Super.
Handles both native function/tool calls and inline JSON tool calls.
Initialises the connection in a daemon thread so the UI opens instantly.
Qwen3 <think> tags are stripped automatically — thinking mode is disabled via options["think"]=False
but the strip is a safety net in case of model version inconsistency.
"""
from __future__ import annotations
import json
import re
import threading
from typing import Optional

from config import OLLAMA_BASE_URL, OLLAMA_KEEP_ALIVE, OLLAMA_MODEL, OLLAMA_OPTIONS


def _strip_think(text: str) -> str:
    """Strip Qwen3 chain-of-thought blocks from response text.
    Qwen3 emits <think>...</think> when thinking mode is on.
    The options["think"]=False flag disables it, but this is a belt-and-suspenders guard.
    """
    if "<think>" not in text:
        return text
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


class LLM:
    """
    Ollama (qwen3:14b primary) via OpenAI-compatible REST API.
    Thread-safe; can be called from background workers.
    """

    def __init__(self,
                 model: str = OLLAMA_MODEL,
                 base_url: str = OLLAMA_BASE_URL):
        self.model    = model
        self.base_url = base_url
        self._client  = None
        self._online  = False
        threading.Thread(target=self._init, daemon=True).start()

    def _init(self):
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key="local", base_url=self.base_url)
            self._client.models.list()
            self._online = True
        except Exception:
            # Intentionally broad: Ollama may be offline at startup; suppress to keep UI responsive.
            # KeyboardInterrupt / SystemExit are BaseException subclasses and still propagate.
            pass

    @property
    def online(self) -> bool:
        return self._online

    # ── Inline tool-call detector (fallback: some models emit JSON as raw text) ─
    @staticmethod
    def _sniff_tool(text: str) -> Optional[dict]:
        if not text or "{" not in text:
            return None
        candidates = []
        if text.strip().startswith("{"):
            candidates.append(text.strip())
        for m in re.finditer(r"\{[^{}]{3,}\}", text):
            candidates.append(m.group())
        for blob in candidates:
            try:
                obj = json.loads(blob)
                if "name" in obj and isinstance(obj["name"], str):
                    return {
                        "id":        "inline_0",
                        "name":      obj["name"],
                        "arguments": obj.get("arguments", obj.get("parameters", {})),
                    }
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        return None

    def complete(
        self,
        messages:    list[dict],
        system:      str = "",
        tools:       Optional[list[dict]] = None,
        temperature: float = 0.35,
        max_tokens:  int   = 350,
    ) -> dict:
        """Return {"content": str, "tool_calls": list[dict]}."""
        if not self._online:
            return {
                "content":    "Ollama is offline, sir. Ensure it is running on port 11434.",
                "tool_calls": [],
            }

        api_msgs: list[dict] = []
        if system:
            api_msgs.append({"role": "system", "content": system})

        for m in messages:
            role = m.get("role", "user")
            if role == "tool":
                api_msgs.append({
                    "role":         "tool",
                    "tool_call_id": m.get("tool_call_id", "tc"),
                    "content":      m.get("content", ""),
                })
            elif m.get("tool_calls"):
                api_msgs.append({
                    "role":       "assistant",
                    "content":    m.get("content") or None,
                    "tool_calls": m["tool_calls"],
                })
            else:
                api_msgs.append({"role": role, "content": m.get("content", "")})

        kw: dict = {
            "model":       self.model,
            "messages":    api_msgs,
            "temperature": temperature,
            "max_tokens":  max_tokens,
            "extra_body":  {"options": OLLAMA_OPTIONS, "keep_alive": OLLAMA_KEEP_ALIVE},
        }
        if tools:
            kw["tools"]       = tools
            kw["tool_choice"] = "auto"

        try:
            resp   = self._client.chat.completions.create(**kw)
            msg    = resp.choices[0].message
            text   = _strip_think(msg.content or "")
            native = []

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:    args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, ValueError, TypeError): args = {}
                    native.append({
                        "id":        tc.id,
                        "name":      tc.function.name,
                        "arguments": args,
                    })

            if not native and text:
                sniffed = self._sniff_tool(text)
                if sniffed:
                    return {"content": "", "tool_calls": [sniffed]}

            return {"content": text, "tool_calls": native}

        except Exception as e:
            return {"content": f"I encountered a system error, sir: {e}", "tool_calls": []}

    def complete_stream(
        self,
        messages:    list[dict],
        system:      str   = "",
        temperature: float = 0.35,
    ):
        """Yield text chunks from a streaming completion (no tool calling)."""
        if not self._online:
            yield "Ollama is offline, sir. Ensure it is running on port 11434."
            return

        api_msgs: list[dict] = []
        if system:
            api_msgs.append({"role": "system", "content": system})
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                continue
            api_msgs.append({"role": role, "content": m.get("content", "")})

        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=api_msgs,
                temperature=temperature,
                max_tokens=350,
                stream=True,
                extra_body={"options": OLLAMA_OPTIONS, "keep_alive": OLLAMA_KEEP_ALIVE},
            )
            buffer = ""
            in_think = False
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if not delta:
                    continue
                buffer += delta
                # Strip Qwen3 <think>...</think> blocks from the stream
                if "<think>" in buffer:
                    in_think = True
                if in_think:
                    if "</think>" in buffer:
                        buffer = buffer[buffer.index("</think>") + len("</think>"):].lstrip()
                        in_think = False
                    continue
                if buffer:
                    yield buffer
                    buffer = ""
            if buffer and not in_think:
                yield buffer
        except Exception as e:
            yield f"I encountered a system error, sir: {e}"
