"""Offline tests (no internet): key detection, model pick, slot fix-up, key manager, load report.
Run:  python3 test_ai_keys_and_load.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recovered_bot import ai_keyid, ai_keys_api, ai_vision, load_report, settings_store  # noqa: E402

OK = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    OK.append(bool(cond))


# ---- 1. guess from the first letters
for key, want in (("sk-ant-api03-abc", "anthropic"), ("sk-or-v1-d4251052ab", "openrouter"), ("AIzaSyA-123456789", "gemini"),
                  ("gsk_j9hAW6VETdNTrDNnh", "groq"), ("sk-proj-abcdefghijkl", "openai"), ("mstrl_qzMHfYpWjgnYbONhqQ", "mistral")):
    check(f"guess {want}", ai_keyid.guess(key)[0] == want)
check("guess bare 32 chars = mistral (not sure)", ai_keyid.guess("a" * 32) == ("mistral", False))
check("guess junk = unknown", ai_keyid.guess("hello") == ("", False))

# ---- 2. best model from each company's own list
check("gemini prefers flash-lite-latest", ai_keyid.pick_model("gemini", [{"id": "gemini-flash-latest"}, {"id": "gemini-flash-lite-latest"}]) == "gemini-flash-lite-latest")
check("gemini lite by version", ai_keyid.pick_model("gemini", [{"id": "gemini-3.5-flash-lite"}, {"id": "gemini-3.1-flash-lite"}, {"id": "gemini-3.8-flash"}]) == "gemini-3.5-flash-lite")
check("groq picks scout/maverick, skips whisper", ai_keyid.pick_model("groq", [{"id": "whisper-large-v3"}, {"id": "meta-llama/llama-4-maverick-17b-128e-instruct"}, {"id": "llama-3.3-70b-versatile"}]) == "meta-llama/llama-4-maverick-17b-128e-instruct")
check("groq with no picture model = empty", ai_keyid.pick_model("groq", [{"id": "llama-3.3-70b-versatile"}]) == "")
check("mistral needs vision flag", ai_keyid.pick_model("mistral", [{"id": "mistral-large-latest", "capabilities": {"vision": False}}, {"id": "mistral-small-latest", "capabilities": {"vision": True}}]) == "mistral-small-latest")
orr = [{"id": "x/y:free", "architecture": {"input_modalities": ["text"]}, "pricing": {"prompt": "0"}},
       {"id": "google/gemma-3-27b-it:free", "architecture": {"input_modalities": ["text", "image"]}, "pricing": {"prompt": "0"}},
       {"id": "paid/model", "architecture": {"input_modalities": ["text", "image"]}, "pricing": {"prompt": "0.1"}}]
check("openrouter picks a FREE picture model", ai_keyid.pick_model("openrouter", orr) == "google/gemma-3-27b-it:free")
check("anthropic picks haiku", ai_keyid.pick_model("anthropic", [{"id": "claude-opus-4"}, {"id": "claude-haiku-4-5-20251001"}]) == "claude-haiku-4-5-20251001")

# ---- 3. inspect with fake internet
real_list = ai_keyid._list


def fake_list(provider, key):
    if key.endswith("BAD"):
        return 401, None, "invalid key"
    if provider == "gemini" and key.startswith("AIza"):
        return 200, [{"id": "gemini-flash-lite-latest"}], ""
    if provider == "openrouter" and key.startswith("sk-or-"):
        return 200, orr, ""
    return 404, None, "nope"


ai_keyid._list = fake_list
r = ai_keyid.inspect("AIzaSyFAKEKEY123456", force=True)
check("inspect gemini ok", r["ok"] and r["provider"] == "gemini" and r["model"] == "gemini-flash-lite-latest")
check("auto model remembered", ai_keyid.cached_model("gemini", "AIzaSyFAKEKEY123456") == "gemini-flash-lite-latest")
r = ai_keyid.inspect("gsk_FAKEBAD", force=True)
check("inspect bad key says so", (not r["ok"]) and r["state"] == "bad_key")
r = ai_keyid.inspect("sk-or-v1-FAKEKEYFAKE", force=True)
check("inspect openrouter ok", r["ok"] and r["model"].endswith(":free"))
r = ai_keyid.inspect("zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", force=True)
check("inspect unknown key probes and fails politely", (not r["ok"]) and r["state"] == "unknown")

# ---- 4. slots: key letters beat a wrong provider, auto model used
settings_store.update(ai_api_key="sk-or-v1-FAKEKEYFAKE", ai_provider="openai", ai_model="",
                      ai2_api_key="", ai3_api_key="", ai4_api_key="")
sl = ai_vision._slots()
check("OpenRouter key typed under 'openai' is fixed", sl and sl[0]["provider"] == "openrouter")
settings_store.update(ai_auto_model="google/gemma-3-27b-it:free", ai_auto_prov="openrouter")
check("auto model is used", ai_vision._slot_models(ai_vision._slots()[0]) == ["google/gemma-3-27b-it:free"])
settings_store.update(ai_model="my/own-model")
check("owner's own model wins", ai_vision._slot_models(ai_vision._slots()[0]) == ["my/own-model"])
settings_store.update(ai_model="")

# ---- 5. key manager
settings_store.update(ai_api_key="", ai_provider="openai", ai_auto_model="", ai_auto_prov="")
a = ai_keys_api.add("AIzaSyFAKEKEY123456")
check("add -> first empty slot = main", a["ok"] and a["slot"] == "main" and a["provider"] == "gemini")
check("settings got the key + provider", settings_store.get("ai_api_key") == "AIzaSyFAKEKEY123456" and settings_store.get("ai_provider") == "gemini")
a = ai_keys_api.add("AIzaSyFAKEKEY123456")
check("same key twice is refused", not a["ok"])
a = ai_keys_api.add("sk-or-v1-FAKEKEYFAKE")
check("second key -> backup 1", a["ok"] and a["slot"] == "backup")
a = ai_keys_api.add("gsk_FAKEBAD")
check("bad key is NOT saved", (not a["ok"]) and not settings_store.get("ai3_api_key"))
st = ai_keys_api.status()
check("status lists 4 slots", len(st["slots"]) == 4 and st["slots"][0]["provider_name"] == "Google Gemini" and st["slots"][2]["filled"] is False)
check("status never shows the full key", "FAKEKEY123456" not in str(st))
check("clear works", ai_keys_api.clear("backup")["ok"] and not settings_store.get("ai2_api_key"))
ai_keyid._list = real_list

# ---- 6. load report on made-up samples
now = time.time()
rows = []
for i in range(120):
    t = now - (120 - i) * 30
    rows.append({"t": t, "cpu": 30, "ram": 55, "lag": 20, "stalls": [], "feed": "LIVE", "api": {"/api/status": [10, 200, 40]}})
rows[60]["stalls"] = [{"ms": 1800, "where": "api_server.py:1 jsonable_encoder"}]
rows[60]["lag"] = 1800
rows[61]["stalls"] = [{"ms": 1600, "where": "api_server.py:1 jsonable_encoder"}]
r = load_report.build(1.0, samples=rows, now=now, starts_crashes=(0, 0))
check("report ok with data", r["ok"] and len(r["meters"]) == 6)
check("two freezes found", [m for m in r["meters"] if m["key"] == "loop"][0]["value"].startswith("2 freezes"))
check("text has verdict", "MAIN BOTTLENECK" in r["text"])
rows2 = [dict(x, stalls=[], lag=10) for x in rows]
r2 = load_report.build(1.0, samples=rows2, now=now, starts_crashes=(0, 0))
check("quiet system -> no bottleneck", r2["verdict"]["key"] == "ok")
rows3 = [dict(x, cpu=95) for x in rows2]
r3 = load_report.build(1.0, samples=rows3, now=now, starts_crashes=(0, 0))
check("busy CPU named", r3["verdict"]["key"] == "cpu")
r4 = load_report.build(1.0, samples=[], now=now, starts_crashes=(0, 0))
check("no data handled", r4["ok"] is False and "text" in r4)

print("\nALL PASS" if all(OK) else "\nSOME FAILED")
sys.exit(0 if all(OK) else 1)
