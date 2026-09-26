"""Provider-agnostic LLM client (Anthropic Claude, OpenAI, Google Gemini) over plain HTTPS.

Configure with environment variables (see .env.example):
    LLM_PROVIDER = anthropic | openai | gemini   (auto-detected from whichever key is set)
    ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
    LLM_MODEL    = optional model override
"""
import base64
import json
import os
import re
import threading
import time

import httpx

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4.1-mini",
    "gemini": None,  # auto-discovered from the key's model list (Google retires versions often)
}
KEY_VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Throttle concurrent LLM calls so a batch of many documents doesn't trip provider rate limits.
_sem = threading.BoundedSemaphore(int(os.getenv("LLM_CONCURRENCY", "4")))
_resolved: dict[str, str] = {}
_bad_models: set[str] = set()
_resolve_lock = threading.Lock()


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def provider() -> str | None:
    p = os.getenv("LLM_PROVIDER", "").strip().lower()
    if p in KEY_VARS and os.getenv(KEY_VARS[p]):
        return p
    for name, var in KEY_VARS.items():
        if os.getenv(var):
            return name
    return None


def _gemini_pick(models):
    """Choose the newest stable 'flash' model that supports generateContent."""
    best, best_key = None, None
    for m in models:
        name = m.get("name", "").removeprefix("models/")
        if "generateContent" not in m.get("supportedGenerationMethods", []) or name in _bad_models:
            continue
        mm = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash(-preview.*|-latest|-\d{3})?", name)
        if not mm:
            continue
        preview = 1 if (mm.group(2) or "").startswith("-preview") else 0
        key = (-preview, float(mm.group(1)), mm.group(2) is None)
        if best_key is None or key > best_key:
            best, best_key = name, key
    return best


def _resolve_gemini(key):
    with _resolve_lock:
        if _resolved.get("gemini"):
            return _resolved["gemini"]
        try:
            r = httpx.get(f"{GEMINI_BASE}/models?pageSize=200", headers={"x-goog-api-key": key}, timeout=30)
            r.raise_for_status()
            choice = _gemini_pick(r.json().get("models", []))
        except Exception:  # noqa: BLE001
            choice = None
        _resolved["gemini"] = choice or "gemini-flash-latest"
        return _resolved["gemini"]


def model_name(resolve=True) -> str | None:
    p = provider()
    if not p:
        return None
    if p == "gemini" and _resolved.get("gemini"):
        return _resolved["gemini"]
    if os.getenv("LLM_MODEL"):
        return os.getenv("LLM_MODEL")
    if p == "gemini":
        return _resolve_gemini(os.getenv(KEY_VARS[p])) if resolve else _resolved.get("gemini", "auto")
    return DEFAULT_MODELS[p]


def status() -> dict:
    p = provider()
    return {"configured": bool(p), "provider": p, "model": model_name()}


class QuotaExhausted(LLMError):
    pass


def _quota_info(text):
    """Pull the quota id and suggested retry delay out of a Google 429 body."""
    ids = re.findall(r'"quotaId":\s*"([^"]+)"', text)
    delay = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', text)
    daily = any("PerDay" in q for q in ids) or "per day" in text.lower()
    return ids, float(delay.group(1)) if delay else None, daily


def _post(url, headers, payload, timeout=240):
    last = None
    for attempt in range(7):
        try:
            with _sem:
                r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code == 429:
                ids, delay, daily = _quota_info(r.text)
                msg = f"429 quota exceeded ({', '.join(ids) or 'rate limit'})"
                if daily or "limit: 0" in r.text:
                    raise QuotaExhausted(msg + " - daily / zero quota for this model", 429)
                last = LLMError(msg, 429)
                time.sleep(min(65, delay + 1 if delay else 4 * 2 ** attempt))
                continue
            if r.status_code in (500, 502, 503, 529):
                last = LLMError(f"{r.status_code}: {r.text[:300]}", r.status_code)
                time.sleep(min(30, 3 * 2 ** attempt))
                continue
            if r.status_code >= 400:
                raise LLMError(f"{r.status_code}: {r.text[:800]}", r.status_code)
            return r.json()
        except httpx.HTTPError as e:
            last = LLMError(str(e))
            time.sleep(min(20, 2 * (attempt + 1)))
    raise last


def list_gemini_models():
    key = os.getenv(KEY_VARS["gemini"])
    r = httpx.get(f"{GEMINI_BASE}/models?pageSize=200", headers={"x-goog-api-key": key}, timeout=30)
    r.raise_for_status()
    return [m["name"].removeprefix("models/") for m in r.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]


def _next_gemini_model(key):
    """After a quota wall on one model, try the next-best flash / flash-lite model this key can use."""
    try:
        names = [n for n in list_gemini_models() if n not in _bad_models]
    except Exception:  # noqa: BLE001
        return None
    for pat in (r"gemini-[\d.]+-flash", r"gemini-[\d.]+-flash-lite", r"gemini-flash-latest", r"gemini-flash-lite-latest", r"gemini-[\d.]+-flash.*"):
        cands = sorted([n for n in names if re.fullmatch(pat, n)], reverse=True)
        if cands:
            return cands[0]
    return None


def _gemini_parts(content):
    if isinstance(content, str):
        return [{"text": content}]
    parts = []
    for c in content:
        if c.get("type") == "file":
            parts.append({"inline_data": {"mime_type": c["mime"], "data": base64.b64encode(c["data"]).decode()}})
        else:
            parts.append({"text": c["text"]})
    return parts


def _anthropic_content(content):
    if isinstance(content, str):
        return content
    out = []
    for c in content:
        if c.get("type") == "file":
            kind = "document" if c["mime"] == "application/pdf" else "image"
            out.append({"type": kind, "source": {"type": "base64", "media_type": c["mime"], "data": base64.b64encode(c["data"]).decode()}})
        else:
            out.append({"type": "text", "text": c["text"]})
    return out


def chat(system: str, messages: list[dict], max_tokens: int = 4000, json_mode: bool = False) -> dict:
    """messages: [{"role": "user"|"assistant", "content": str | [{"type":"text","text":..}|{"type":"file","mime":..,"data":bytes}]}].
    Returns {"text", "model", "latency_ms", "usage"}."""
    p = provider()
    if not p:
        raise LLMNotConfigured("No LLM API key configured. Set GEMINI_API_KEY (or ANTHROPIC_API_KEY / OPENAI_API_KEY) in .env")
    key = os.getenv(KEY_VARS[p])
    t0 = time.time()
    if p == "anthropic":
        model = model_name()
        msgs = [{"role": m["role"], "content": _anthropic_content(m["content"])} for m in messages]
        data = _post("https://api.anthropic.com/v1/messages",
                     {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                     {"model": model, "max_tokens": max_tokens, "system": system, "messages": msgs, "temperature": 0})
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
    elif p == "openai":
        model = model_name()
        if any(not isinstance(m["content"], str) for m in messages):
            raise LLMError("Scanned documents need a Gemini or Claude key (OpenAI path supports text PDFs only).")
        payload = {"model": model, "messages": [{"role": "system", "content": system}] + messages,
                   "max_completion_tokens": max_tokens, "temperature": 0}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = _post("https://api.openai.com/v1/chat/completions",
                     {"Authorization": f"Bearer {key}", "content-type": "application/json"}, payload)
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
    else:  # gemini
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": _gemini_parts(m["content"])} for m in messages]
        cfg = {"maxOutputTokens": max(max_tokens, 8192), "temperature": 0}
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents, "generationConfig": cfg}
        for _ in range(5):
            model = model_name()
            try:
                data = _post(f"{GEMINI_BASE}/models/{model}:generateContent",
                             {"content-type": "application/json", "x-goog-api-key": key}, body)
                break
            except QuotaExhausted:
                _bad_models.add(model)
                nxt = _next_gemini_model(key) if not os.getenv("LLM_MODEL_LOCK") else None
                if not nxt:
                    raise QuotaExhausted("Gemini quota exhausted for this API key (free tier). Enable billing in Google AI Studio "
                                         "or add a different key in .env, then restart.", 429)
                with _resolve_lock:
                    _resolved["gemini"] = nxt
                continue
            except LLMError as e:
                if e.status == 404:
                    # retired / unavailable model: use the replacement Google names in the error, else rediscover
                    _bad_models.add(model)
                    suggested = [m.rstrip(".") for m in re.findall(r"models/(gemini[\w.\-]+)", str(e)) if m.rstrip(".") not in _bad_models]
                    with _resolve_lock:
                        _resolved["gemini"] = suggested[0] if suggested else None
                        if not suggested:
                            _resolved.pop("gemini", None)
                    os.environ.pop("LLM_MODEL", None)
                    continue
                raise
        else:
            raise LLMError("No usable Gemini model found for this API key. Set LLM_MODEL in .env.")
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(pt.get("text", "") for pt in parts if not pt.get("thought"))
        if not text:
            raise LLMError(f"Gemini returned no text (finishReason={cand.get('finishReason')}, block={data.get('promptFeedback')})")
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
