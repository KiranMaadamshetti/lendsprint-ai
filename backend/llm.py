"""Provider-agnostic LLM client (Anthropic Claude, OpenAI, Google Gemini) over plain HTTPS.

Configure with environment variables (see .env.example):
    LLM_PROVIDER = anthropic | openai | gemini   (auto-detected from whichever key is set)
    ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
    LLM_MODEL    = optional model override
"""
import json
import os
import re
import time

import httpx

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-2.5-flash",
}
KEY_VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


def provider() -> str | None:
    p = os.getenv("LLM_PROVIDER", "").strip().lower()
    if p in KEY_VARS and os.getenv(KEY_VARS[p]):
        return p
    for name, var in KEY_VARS.items():
        if os.getenv(var):
            return name
    return None


def model_name() -> str | None:
    p = provider()
    return (os.getenv("LLM_MODEL") or DEFAULT_MODELS[p]) if p else None


def status() -> dict:
    p = provider()
    return {"configured": bool(p), "provider": p, "model": model_name()}


def _post(url, headers, payload, timeout=180):
    last = None
    for attempt in range(3):
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 529):
                last = LLMError(f"{r.status_code}: {r.text[:300]}")
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise LLMError(f"{r.status_code}: {r.text[:500]}")
            return r.json()
        except httpx.HTTPError as e:
            last = LLMError(str(e))
            time.sleep(2 * (attempt + 1))
    raise last


def chat(system: str, messages: list[dict], max_tokens: int = 4000, json_mode: bool = False) -> dict:
    """messages: [{"role": "user"|"assistant", "content": str}]. Returns {"text", "model", "latency_ms", "usage"}."""
    p = provider()
    if not p:
        raise LLMNotConfigured("No LLM API key configured. Set ANTHROPIC_API_KEY (or OPENAI_API_KEY / GEMINI_API_KEY) in .env")
    key, model = os.getenv(KEY_VARS[p]), model_name()
    t0 = time.time()
    if p == "anthropic":
        data = _post("https://api.anthropic.com/v1/messages",
                     {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                     {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages, "temperature": 0})
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
    elif p == "openai":
        payload = {"model": model, "messages": [{"role": "system", "content": system}] + messages,
                   "max_completion_tokens": max_tokens, "temperature": 0}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = _post("https://api.openai.com/v1/chat/completions",
                     {"Authorization": f"Bearer {key}", "content-type": "application/json"}, payload)
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
    else:  # gemini
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages]
        cfg = {"maxOutputTokens": max_tokens, "temperature": 0}
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        data = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                     {"content-type": "application/json", "x-goog-api-key": key},
                     {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents, "generationConfig": cfg})
        text = "".join(pt.get("text", "") for pt in data["candidates"][0]["content"]["parts"])
        usage = data.get("usageMetadata", {})
    return {"text": text, "model": f"{p}/{model}", "latency_ms": int((time.time() - t0) * 1000), "usage": usage}


def parse_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def chat_json(system: str, user: str, max_tokens: int = 4000) -> tuple[dict, dict]:
    """Ask for JSON; retry once with the parse error if the model returns malformed JSON."""
    messages = [{"role": "user", "content": user}]
    sys = system + "\n\nRespond with a single valid JSON object only. No prose, no markdown fences."
    res = chat(sys, messages, max_tokens=max_tokens, json_mode=True)
    try:
        return parse_json(res["text"]), res
    except (json.JSONDecodeError, ValueError) as e:
        messages += [{"role": "assistant", "content": res["text"]},
                     {"role": "user", "content": f"That was not valid JSON ({e}). Return the corrected JSON object only."}]
        res2 = chat(sys, messages, max_tokens=max_tokens, json_mode=True)
        res2["latency_ms"] += res["latency_ms"]
        return parse_json(res2["text"]), res2
