"""Pluggable LLM providers for the planner/executor loop.

- OpenAICompatProvider: any OpenAI-compatible /chat/completions endpoint with tool calling (OpenAI, xAI, Groq,
  Together, vLLM, Ollama, LM Studio...). Configured by WITNESS_LLM_BASE_URL / WITNESS_LLM_API_KEY / WITNESS_LLM_MODEL.
- OfflineProvider: deterministic planner used in tests and when no key is configured. It maps requests to tool
  calls with simple rules and, in `gullible` mode, obeys instructions found in tool output: a stand-in for a
  hijacked model, so tests prove the firewall (not the model) is what stops injected actions."""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol
import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Completion:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class Provider(Protocol):
    name: str

    async def complete(self, messages: list[dict], tools: list[dict], lang: str) -> Completion: ...


class OpenAICompatProvider:
    name = "openai-compat"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0, transport=None):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def complete(self, messages, tools, lang):
        body = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
            body["tool_choice"] = "auto"
        r = await self.client.post(f"{self.base_url}/chat/completions", json=body,
                                   headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc["function"].get("arguments")}
            calls.append(ToolCall(tc["id"], tc["function"]["name"], args if isinstance(args, dict) else {"value": args}))
        return Completion(msg.get("content"), calls)


_URL = re.compile(r"https?://[^\s'\"<>]+")
_MONEY = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s?(?:usd|dollars)", re.I)


class OfflineProvider:
    """Rule-based planner. One tool call per turn, then a summary once results are in."""
    name = "offline"

    def __init__(self, gullible: bool = True):
        self.gullible = gullible
        self._n = 0

    def _id(self):
        self._n += 1
        return f"call_{self._n}"

    def _plan(self, text: str, tools: set[str]) -> ToolCall | None:
        t = text.strip()
        low = t.lower()
        m = re.match(r"(?:please )?remember(?: that)?\s+(.+)", low)
        if m and "memory_save" in tools:
            return ToolCall(self._id(), "memory_save", {"text": t[len(t) - len(m.group(1)):]})
        if re.search(r"what do you (know|remember)|recall|do you remember", low) and "memory_search" in tools:
            q = re.sub(r".*?(about|regarding)\s+", "", low) if re.search(r"about|regarding", low) else low
            return ToolCall(self._id(), "memory_search", {"query": q.strip(" ?")})
        mp = re.search(r"\b(?:pay|buy|order|purchase)\b", low)
        money = _MONEY.search(t)
        if mp and money and "pay" in tools:
            merch = re.search(r"\b(?:at|from|to)\s+([a-z0-9.-]+\.[a-z]{2,})", low)
            amt = money.group(1) or money.group(2)
            return ToolCall(self._id(), "pay", {"merchant": merch.group(1) if merch else "unknown",
                                                "amount": float(amt), "currency": "USD",
                                                "description": t[:120]})
        em = re.search(r"\b(?:email|mail|send an email to)\s+([\w.+-]+@[\w-]+\.[\w.]+)\s*(?:saying|:|that)?\s*(.*)", t, re.I)
        if em and "email_send" in tools:
            return ToolCall(self._id(), "email_send", {"to": em.group(1), "subject": "Message from Witness",
                                                       "body": em.group(2) or "(no body)"})
        url = _URL.search(t)
        if url and "web_fetch" in tools:
            return ToolCall(self._id(), "web_fetch", {"url": url.group(0).rstrip(".,)")})
        if re.search(r"calendar|schedule|meetings?|agenda", low) and "calendar_list" in tools:
            return ToolCall(self._id(), "calendar_list", {"days": 7})
        fw = re.search(r"(?:write|save) (?:a )?(?:file|note)\s+([\w.-]+)\s*(?:with|:)\s*(.+)", t, re.I)
        if fw and "files_write" in tools:
            return ToolCall(self._id(), "files_write", {"path": fw.group(1), "content": fw.group(2)})
        fr = re.search(r"(?:read|open) (?:the )?file\s+([\w./-]+)", t, re.I)
        if fr and "files_read" in tools:
            return ToolCall(self._id(), "files_read", {"path": fr.group(1)})
        if re.search(r"\b(list|show) (my )?files\b", low) and "files_list" in tools:
            return ToolCall(self._id(), "files_list", {})
        mc = re.search(r"\buse\s+(mcp:[\w-]+/[\w.-]+)\s*(\{.*\})?", t)
        if mc and mc.group(1) in tools:
            return ToolCall(self._id(), mc.group(1), json.loads(mc.group(2)) if mc.group(2) else {})
        return None

    async def complete(self, messages, tools, lang):
        names = {t["name"] for t in tools}
        last = messages[-1]
        if last["role"] == "user":
            call = self._plan(last["content"], names)
            if call:
                return Completion(None, [call])
            return Completion(_chat_reply(last["content"], lang))
        if last["role"] == "tool":
            body = last["content"]
            if self.gullible and "UNTRUSTED" in body:
                inner = body.split("\n", 1)[-1]
                call = self._plan(inner, names - {"web_fetch"})
                if call and call.name in {"pay", "email_send", "files_write"} or (call and call.name.startswith("mcp:")):
                    return Completion(None, [call])  # a hijacked model obeys the page
            return Completion(_summarize(body, lang))
        return Completion("OK")


def _summarize(tool_text: str, lang: str = "en") -> str:
    from witness.i18n import phrase
    if tool_text.startswith("BLOCKED by policy: "):
        return phrase("blocked", lang, why=tool_text[len("BLOCKED by policy: "):])
    if tool_text.startswith("DENIED"):
        return phrase("blocked", lang, why="you denied it")
    inner = tool_text.split("\n", 1)[-1] if tool_text.startswith("<<<UNTRUSTED") else tool_text
    inner = inner.replace("<<<END UNTRUSTED>>>", "").strip()
    return inner[:600] if inner else "Done."


def _chat_reply(text: str, lang: str) -> str:
    from witness.i18n import NAMES
    return (f"[offline planner] I understood your message ({NAMES.get(lang, lang)}) but no tool matches it. "
            "Configure WITNESS_LLM_BASE_URL/WITNESS_LLM_API_KEY for open-ended tasks.")


def from_env(transport=None) -> Provider:
    base, key = os.environ.get("WITNESS_LLM_BASE_URL"), os.environ.get("WITNESS_LLM_API_KEY")
    if base and key:
        return OpenAICompatProvider(base, key, os.environ.get("WITNESS_LLM_MODEL", "gpt-4o-mini"), transport=transport)
    return OfflineProvider(gullible=os.environ.get("WITNESS_OFFLINE_GULLIBLE", "true").lower() == "true")
