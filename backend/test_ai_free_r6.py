#!/usr/bin/env python3
"""Round 6: AI Own learns freely (no entry rules), histogram = 10 numbers only, 8 key slots, NVIDIA provider."""
import math, os, re, sys, tempfile
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp(prefix="r6_"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot import ai_keyid as K, ai_keys_api as KA, ai_vision as V, ai_vision_own as O, settings_store as S

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  OK  {name}")
    else: FAIL += 1; print(f" FAIL {name}")

# ---- key detection
check("nvapi- -> nvidia", K.guess("nvapi-" + "A" * 60) == ("nvidia", True))
check("sk- + 32 hex -> deepseek", K.guess("sk-" + "0123456789abcdef" * 2) == ("deepseek", True))
check("long sk- stays openai", K.guess("sk-proj-" + "a" * 80)[0] == "openai")
check("sk-or- openrouter", K.guess("sk-or-v1-" + "a" * 40)[0] == "openrouter")
check("gsk_ groq", K.guess("gsk_" + "a" * 40)[0] == "groq")
check("mstrl_ mistral", K.guess("mstrl_" + "a" * 30)[0] == "mistral")
check("nvidia vision model picked", K.pick_model("nvidia", [{"id": "meta/llama-3.1-8b-instruct"}, {"id": "nvidia/nemotron-nano-12b-v2-vl"}]) == "nvidia/nemotron-nano-12b-v2-vl")
check("nvidia without vision model -> empty", K.pick_model("nvidia", [{"id": "meta/llama-3.1-8b-instruct"}]) == "")
check("deepseek has no picture model", K.pick_model("deepseek", [{"id": "deepseek-chat"}]) == "")

# ---- slots
check("8 key slots", len(KA.SLOTS) == 8 and KA._PFX["backup7"] == "ai8")
check("vision knows 8 slots", V._PFX["backup7"] == "ai8")
check("nvidia in provider table", "nvidia" in V._OAI_STYLE)
for n in (5, 6, 7, 8):
    check(f"default ai{n}_api_key empty", S._defaults.get(f"ai{n}_api_key") == "")
S.update(ai8_api_key="nvapi-" + "B" * 60, ai8_provider="mistral")
sl = {x["slot"]: x for x in V._slots()}
check("slot 8 becomes an NVIDIA slot from the key letters", sl.get("backup7", {}).get("provider") == "nvidia")
S.update(ai8_api_key="")
check("secret of slot 8 is hidden in settings", "ai8_api_key" in open(os.path.join(os.path.dirname(__file__), "api_server.py")).read().split("_SETTINGS_SECRET_KEYS =")[1][:400])

# ---- nvidia request: no response_format, 400 retried without it
class R:
    def __init__(s, c, j=None): s.status_code = c; s._j = j or {}; s.text = ""
    def json(s): return s._j
calls = []
def fake_post(url, headers=None, json=None, timeout=0):
    calls.append((url, dict(json)))
    return R(200, {"choices": [{"message": {"content": "{}"}}]})
V.requests.post = fake_post
out = V._try_oai({"slot": "backup7", "key": "k", "provider": "nvidia", "model": "", "auto": ""}, "sys", "txt", "AAA")
check("nvidia call ok, no response_format", out[0] == "{}" and "response_format" not in calls[-1][1] and "integrate.api.nvidia.com" in calls[-1][0])
seq = [R(400, {"error": "bad"}), R(200, {"choices": [{"message": {"content": "ok"}}]})]
calls.clear()
def fake2(url, headers=None, json=None, timeout=0):
    calls.append(dict(json)); return seq.pop(0)
V.requests.post = fake2
out = V._try_oai({"slot": "backup", "key": "k", "provider": "groq", "model": "", "auto": ""}, "s", "t", None)
check("400 on response_format retried without it", out[0] == "ok" and "response_format" in calls[0] and "response_format" not in calls[1])

# ---- histogram: only numbers
f = {"diff": [0.5, 0.4, 0.3, 0.1, -0.1, -0.2, -0.3, -0.25, -0.1, 0.05, 0.2], "tsi": [-5.0], "tsl": [-4.0]}
hn = V.hist_note(f)
t = hn["text"]
check("10 values in text", len(re.findall(r"[+-]\d\.\d+", t.split("oldest to newest")[1])) >= 10)
check("no hand-made words", not re.search(r"Buyers|Sellers|Not a buy|never a reason|Shrinking|Growing|wait for", t, re.I))
check("word/line/ctx empty", hn["word"] == "" and hn["line"] == "" and hn["ctx"] == "")
check("TSI and signal numbers kept", "TSI -5.0" in t and "signal line -4.0" in t)
check("short = numbers", hn["short"].startswith("last 10 bars:"))
check("not enough bars still safe", V.hist_note({"diff": [0.1]})["vals"] == [])
check("guide no longer pre-reads histogram", "Plain lines:" not in V.GUIDE and "never a reason" not in V.GUIDE)

# ---- prompts
import random
random.seed(3)
CANDLES, _px = [], 100.0
for _i in range(320):
    _o = _px; _px = max(1.0, _px + random.uniform(-1, 1)); _h = max(_o, _px) + 0.3; _l = min(_o, _px) - 0.3
    CANDLES.append({"timestamp": 1_700_000_000_000 + _i * 900_000, "open": _o, "high": _h, "low": _l, "close": _px, "volume": 1000 + _i})
g_own, g_bot = V.guide_text("BTCUSDT", "BUY", own=True), V.guide_text("BTCUSDT", "BUY")
check("own guide has no SKIP/WAIT nudges", "prefer WAIT or SKIP" not in g_own and "choose SKIP or WAIT" not in g_own)
check("bot judge guide unchanged", "prefer WAIT or SKIP" in g_bot and "choose SKIP or WAIT" in g_bot)
_f, _e, lv = V._levels(CANDLES)
rec = {"symbol": "ABCUSDT", "tf_min": 15, "side": "BUY", "sig_price": 100.0, "source": "own", "tsi_hist_note": hn}
try:
    p_own = V._signal_prompt(rec, lv, 100.5)
    rec_b = dict(rec, source="bot"); p_bot = V._signal_prompt(rec_b, lv, 100.5)
    check("own prompt has no 'few trades' / pump rule", "as few trades" not in p_own and "pumped" not in p_own and "doubtful" not in p_own)
    check("own prompt says it learns itself", "you learn from the results" in p_own and "no entry rules" in p_own)
    check("own prompt does not claim 'no daily loss limit'", "no daily loss limit" not in p_own)
    check("bot prompt still has pump line", "pumped" in p_bot)
except Exception as e:
    check(f"prompt build ({type(e).__name__}: {e})", False)

# ---- own scan source: gate gone
src = open(os.path.join(os.path.dirname(__file__), "recovered_bot", "ai_vision_own.py")).read()
tick = src[src.index("def tick(V):"):src.index("def scan_stats")]
check("tick no longer uses the prefilter", "_prefilter(" not in tick and "No setup: fewer than 2" not in tick)
check("lean side helpers", O._agree({"slope_with": True, "tsi_agrees": True, "z_agrees": False}) == 2 and O._agree({}) == 0)

# ---- chart renders with the new box
try:
    c = CANDLES
    png = V.render_chart("TESTUSDT", c, "15m", side="BUY", source="own")
    check("chart renders (png)", bytes(png)[:4] == b"\x89PNG")
except ImportError:
    print("  SKIP chart render (Pillow missing)")
except Exception as e:
    check(f"chart render ({type(e).__name__}: {e})", False)

# ---- REST data counter
from recovered_bot import telemetry as T, http_client as H
T.record_rest_bytes("https://fapi.binance.com/fapi/v1/ticker/price?x=1", 40_000)
T.record_rest_bytes("https://fapi.binance.com/fapi/v1/ticker/price", 40_000)
T.record_rest_bytes("https://fapi.binance.com/fapi/v1/klines?symbol=A", 10_000)
u = T.rest_data_use()
check("REST MB per hour counted", abs(u["mb_hour"] - 0.09) < 0.011 and u["top_mb"][0]["ep"] == "/fapi/v1/ticker/price" and u["top_mb"][0]["calls"] == 2)
class _Resp:
    headers = {"Content-Length": "1234"}; content = b"x" * 5000; status_code = 200
import requests as _rq
_orig = _rq.Session.request
_rq.Session.request = lambda self, m, url, *a, **k: _Resp()
before = T._rest_bytes_total
H._CountingSession().request("GET", "https://example.com/a/b")
check("session adds wire size (Content-Length)", T._rest_bytes_total - before == 1234)
_rq.Session.request = _orig
try:
    T._sample_once()
    check("telemetry snapshot has the data block", "data" in (T.snapshot().get("rest") or {}))
except Exception as e:
    check(f"telemetry snapshot ({type(e).__name__}: {e})", False)

print(f"\n{PASS} passed, {FAIL} failed"); sys.exit(1 if FAIL else 0)
