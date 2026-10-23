"""
ai_keyid.py - paste ANY AI key, the backend works out whose key it is and which model to use.

  guess(key)            -> provider from the key's first letters (sk-ant-, sk-or-, AIza, gsk_ ...). No network.
  inspect(key)          -> asks the company's "list models" page (free, no quota used): is the key real, and which
                           picture-reading model is the best one to use. Result is remembered for 10 minutes.
  test_call(prov,key,m) -> ONE tiny question to the model: ready / out of quota / bad key / bad model, in plain words.

Read-only toward the bot and the exchange. Never raises: every function returns a dict with "ok" and a plain message.
"""
import hashlib
import re
import threading
import time

import requests

NAMES = {"gemini": "Google Gemini", "anthropic": "Claude (Anthropic)", "openai": "OpenAI", "groq": "Groq",
         "mistral": "Mistral", "openrouter": "OpenRouter", "nvidia": "NVIDIA", "deepseek": "DeepSeek"}
_OAI_BASE = {"openai": "https://api.openai.com/v1", "groq": "https://api.groq.com/openai/v1",
             "mistral": "https://api.mistral.ai/v1", "openrouter": "https://openrouter.ai/api/v1",
             "nvidia": "https://integrate.api.nvidia.com/v1", "deepseek": "https://api.deepseek.com"}
_FALLBACK = {"gemini": "gemini-flash-lite-latest", "anthropic": "claude-haiku-5-5", "openai": "gpt-4o-mini",
             "mistral": "mistral-small-latest", "groq": "meta-llama/llama-4-scout-17b-16e-instruct",
             "openrouter": "meta-llama/llama-4-maverick:free",
             "nvidia": "nvidia/nemotron-nano-12b-v2-vl", "deepseek": ""}
_PROBE_ORDER = ("mistral", "openai", "groq", "openrouter", "nvidia", "gemini", "anthropic")   # for keys with no known prefix
_T = 12
_lock = threading.Lock()
_cache = {}            # sha1(key) -> (time, result)
_auto = {}             # "provider:sha1" -> model (used by ai_vision without any network call)


def _h(key):
    return hashlib.sha1(str(key).encode()).hexdigest()[:16]


def mask(key):
    k = str(key or "")
    return "" if not k else (k[:4] + "..." + k[-4:] if len(k) > 10 else "****")


def guess(key):
    """-> (provider, sure). sure=False means 'probably' (a bare 32-letter key is how Mistral keys usually look)."""
    k = str(key or "").strip()
    if k.startswith("sk-ant-"):
        return "anthropic", True
    if k.startswith("sk-or-"):
        return "openrouter", True
    if k.startswith("AIza"):
        return "gemini", True
    if k.startswith("gsk_"):
        return "groq", True
    if k.startswith("nvapi-"):
        return "nvidia", True
    if re.fullmatch(r"sk-[0-9a-f]{32}", k):          # DeepSeek keys: sk- + exactly 32 hex letters (OpenAI keys are much longer)
        return "deepseek", True
    if k.startswith("sk-"):
        return "openai", True
    if k.lower().startswith("mstr"):
        return "mistral", True
    if re.fullmatch(r"[A-Za-z0-9]{32}", k):
        return "mistral", False
    return "", False


def cached_model(provider, key):
    return _auto.get(f"{provider}:{_h(key)}", "")


def remember_model(provider, key, model):
    if model:
        _auto[f"{provider}:{_h(key)}"] = model


# ------------------------------------------------------------------ list models (free call)
def _plain(r):
    try:
        j = r.json()
        e = j.get("error", j)
        m = e.get("message") if isinstance(e, dict) else str(e)
        return str(m)[:160]
    except Exception:
        return (r.text or "")[:160]


def _list(provider, key):
    """-> (status, raw list or None, error text). raw items are dicts with at least 'id'."""
    try:
        if provider == "gemini":
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                             headers={"x-goog-api-key": key}, timeout=_T)
            if r.status_code != 200:
                return r.status_code, None, _plain(r)
            out = []
            for m in r.json().get("models", []):
                if "generateContent" in (m.get("supportedGenerationMethods") or []):
                    out.append({"id": str(m.get("name", "")).replace("models/", "")})
            return 200, out, ""
        if provider == "anthropic":
            r = requests.get("https://api.anthropic.com/v1/models?limit=100",
                             headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=_T)
            if r.status_code != 200:
                return r.status_code, None, _plain(r)
            return 200, [{"id": m.get("id", "")} for m in r.json().get("data", [])], ""
        if provider == "openrouter":
            a = requests.get("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": f"Bearer {key}"}, timeout=_T)
            if a.status_code != 200:
                return a.status_code, None, _plain(a)
            r = requests.get("https://openrouter.ai/api/v1/models", timeout=_T)       # public list, has prices + picture support
            return (200, r.json().get("data", []), "") if r.status_code == 200 else (200, [], "")
        base = _OAI_BASE.get(provider)
        if not base:
            return 0, None, "unknown provider"
        r = requests.get(base + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=_T)
        if r.status_code != 200:
            return r.status_code, None, _plain(r)
        return 200, r.json().get("data", []), ""
    except requests.exceptions.RequestException as e:
        return 0, None, "network: " + str(e)[:100]
    except Exception as e:
        return 0, None, "error: " + str(e)[:100]


def _ver(s):
    return tuple(int(x) for x in re.findall(r"\d+", s)[:4]) or (0,)


_BAD = re.compile(r"preview|exp|image|tts|audio|embed|live|thinking|robotics|computer|guard|whisper|moderation|ocr|realtime|transcribe", re.I)


def pick_model(provider, raw):
    """Best picture-reading model from the company's own list. Falls back to a sensible default."""
    ids = [str(m.get("id", "")) for m in (raw or []) if m.get("id")]
    fb = _FALLBACK.get(provider, "")
    if not ids:
        return fb
    if provider == "gemini":
        for want in ("gemini-flash-lite-latest", "gemini-flash-latest"):        # Lite has the bigger free limit
            if want in ids:
                return want
        lite = sorted([i for i in ids if "flash-lite" in i and not _BAD.search(i)], key=_ver)
        if lite:
            return lite[-1]
        fl = sorted([i for i in ids if "flash" in i and not _BAD.search(i)], key=_ver)
        return fl[-1] if fl else fb
    if provider == "anthropic":
        h = sorted([i for i in ids if "haiku" in i])
        return h[-1] if h else (sorted(ids)[-1] if ids else fb)
    if provider == "openai":
        for want in ("gpt-4o-mini", "gpt-4.1-mini", "gpt-5-mini", "gpt-4o"):
            if want in ids:
                return want
        return fb
    if provider == "mistral":
        vis = [m for m in raw if (m.get("capabilities") or {}).get("vision")]
        names = [str(m["id"]) for m in vis]
        for want in ("mistral-small-latest", "pixtral-12b-latest", "mistral-medium-latest"):
            if want in names:
                return want
        return names[0] if names else fb
    if provider == "groq":
        vis = [i for i in ids if re.search(r"scout|maverick|vision", i, re.I) and not _BAD.search(i)]
        vis.sort(key=lambda i: (0 if "scout" in i else 1 if "maverick" in i else 2, i))
        return vis[0] if vis else ""        # "" = this key has no picture model; shown to the owner
    if provider == "nvidia":
        vis = [i for i in ids if re.search(r"nemotron.*vl|vl.*nemotron|vision|llama-4|pixtral|mistral-small|qwen.*vl", i, re.I) and not _BAD.search(i)]
        for want in ("nvidia/nemotron-nano-12b-v2-vl", "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"):
            if want in vis:
                return want
        vis.sort(key=lambda i: (0 if "nemotron" in i else 1, i))
        return vis[0] if vis else ""
    if provider == "deepseek":
        return ""        # DeepSeek's API reads text only: it cannot look at a chart picture
    if provider == "openrouter":
        free = []
        for m in raw:
            mods = ((m.get("architecture") or {}).get("input_modalities")) or []
            pr = (m.get("pricing") or {}).get("prompt")
            if "image" in mods and str(pr) in ("0", "0.0", "0.00") and str(m.get("id", "")).endswith(":free"):
                free.append(str(m["id"]))
        for fam in ("llama-4-maverick", "llama-4-scout", "gemma-3", "mistral-small", "qwen2.5-vl", "qwen"):
            for i in free:
                if fam in i:
                    return i
        return free[0] if free else fb
    return fb


def inspect(key, provider=None, force=False):
    """-> {ok, provider, provider_name, model, state, message}. state: ready | bad_key | no_vision | network | unknown."""
    key = str(key or "").strip()
    if not key:
        return {"ok": False, "provider": "", "provider_name": "", "model": "", "state": "unknown", "message": "No key pasted."}
    ck = _h(key)
    now = time.time()
    with _lock:
        hit = _cache.get(ck)
    if hit and not force and now - hit[0] < 600 and (not provider or hit[1].get("provider") == provider):
        return dict(hit[1])
    sure = True
    if not provider:
        provider, sure = guess(key)
    tries = [provider] if provider and sure else ([provider] if provider else []) + [p for p in _PROBE_ORDER if p != provider]
    res = None
    last_err = ""
    for pv in tries:
        st, raw, err = _list(pv, key)
        if st == 200:
            model = pick_model(pv, raw)
            ok = bool(model)
            res = {"ok": ok, "provider": pv, "provider_name": NAMES.get(pv, pv), "model": model,
                   "state": "ready" if ok else "no_vision",
                   "message": (f"{NAMES.get(pv, pv)} key works. Model: {model}." if ok else
                               f"{NAMES.get(pv, pv)} key works, but no picture-reading model is on this key. Use a different key for the Vision AI.")}
            remember_model(pv, key, model)
            break
        last_err = err
        if st in (401, 403) and sure:
            res = {"ok": False, "provider": pv, "provider_name": NAMES.get(pv, pv), "model": "", "state": "bad_key",
                   "message": f"This looks like a {NAMES.get(pv, pv)} key, but {NAMES.get(pv, pv)} says it is not valid ({st}). Copy it again, or create a new key."}
            break
        if st == 0 and sure:
            res = {"ok": False, "provider": pv, "provider_name": NAMES.get(pv, pv), "model": "", "state": "network",
                   "message": "Could not reach " + NAMES.get(pv, pv) + " (internet?). " + err}
            break
    if res is None:
        res = {"ok": False, "provider": "", "provider_name": "", "model": "", "state": "unknown",
               "message": "Could not tell whose key this is. Check that you copied the whole key. " + last_err[:80]}
    with _lock:
        _cache[ck] = (now, res)
        if len(_cache) > 40:
            _cache.pop(next(iter(_cache)))
    return dict(res)


# ------------------------------------------------------------------ one tiny question
def test_call(provider, key, model):
    """-> {state: ready|quota|bad_key|bad_model|error, message}. Uses 1 small call (counts toward the free limit)."""
    try:
        if provider == "gemini":
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json={"contents": [{"role": "user", "parts": [{"text": "Reply with the word OK."}]}],
                                    "generationConfig": {"maxOutputTokens": 8}}, timeout=25)
        elif provider == "anthropic":
            r = requests.post("https://api.anthropic.com/v1/messages",
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                              json={"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "Reply with the word OK."}]}, timeout=25)
        else:
            r = requests.post(_OAI_BASE.get(provider, _OAI_BASE["openai"]) + "/chat/completions",
                              headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                              json={"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "Reply with the word OK."}]}, timeout=25)
    except requests.exceptions.RequestException as e:
        return {"state": "error", "message": "No internet or the server did not answer. " + str(e)[:80]}
    except Exception as e:
        return {"state": "error", "message": str(e)[:100]}
    c = r.status_code
    if c == 200:
        return {"state": "ready", "message": "Working. The model answered."}
    if c == 429:
        return {"state": "quota", "message": "Out of free calls for now (limit reached). It comes back by itself."}
    if c in (401, 403):
        return {"state": "bad_key", "message": "The key is not accepted. Create a new key."}
    if c == 404:
        return {"state": "bad_model", "message": "This model name is retired. Press Detect again to pick a new one."}
    return {"state": "error", "message": f"{c}: {_plain(r)}"}
