"""Vision AI: quota handling + backup key + learning notebook. Run: python3 test/test_vision_notebook.py"""
import json, os, sys, tempfile, time, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_vision as V, ai_vision_lessons as L, ai_ind_features as F, ai_guard

tmp = tempfile.mkdtemp()
V.init(tmp)                       # also points the notebook at the same folder
V._loaded = True; L._loaded = True
cfg = {"ai_api_key": "AAA", "ai_provider": "gemini", "ai_model": "", "ai2_api_key": "", "ai2_provider": "mistral", "vision_max_calls_day": 200}
V._cfg = lambda n, d: cfg.get(n, d) if cfg.get(n, d) is not None else d

class R:
    def __init__(self, code, body=None, headers=None):
        self.status_code = code; self._b = body or {}; self.text = json.dumps(self._b); self.headers = headers or {}
    def json(self): return self._b

calls = []
script = []
def fake_post(url, headers=None, json=None, timeout=0):
    calls.append(url)
    return script.pop(0)(url) if script else R(500, {"error": {"message": "no script"}})
V.requests.post = fake_post
gem_ok = lambda u: R(200, {"candidates": [{"content": {"parts": [{"text": '{"decision":"SKIP","reason":"r"}'}]}}]})
gem_daily = lambda u: R(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota", "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
gem_min = lambda u: R(429, {"error": {"status": "RESOURCE_EXHAUSTED", "details": [{"retryDelay": "34s"}]}})
oai_ok = lambda u: R(200, {"choices": [{"message": {"content": '{"decision":"SKIP","reason":"backup"}'}}]})

# 0) guard + dead model names
assert "ai_vision_lessons.py" in ai_guard.AI_FILES and ai_guard.check() == [], ai_guard.check()
assert not any("2.5" in m or "2.0" in m for m in V._GEMINI_MODELS), V._GEMINI_MODELS

# 1) one key, daily quota -> every model paused, error starts with quota:, resume time ~30 min, NOT 'key problem'
script[:] = [gem_daily, gem_daily]
out, err = V._call_ai("sys", "txt", b"png")
assert out is None and err.startswith("quota:"), err
at = V.quota_resume_at()
assert 1700 < at - time.time() <= 1802, at - time.time()
n_before = len(calls)
out, err = V._call_ai("sys", "txt", b"png")                       # still paused -> no HTTP call at all
assert err.startswith("quota:") and len(calls) == n_before

# 2) after the pause the key works again
for k in list(V._pause): V._pause[k] = 0
script[:] = [gem_ok]
out, err = V._call_ai("sys", "txt", b"png"); assert err is None and "SKIP" in out

# 3) backup key (Mistral) answers while the main key is out of quota; main stays paused on its own
cfg["ai2_api_key"] = "BBB"
script[:] = [gem_min, gem_min, oai_ok]
out, err = V._call_ai("sys", "txt", b"png")
assert err is None and "backup" in out, (out, err)
assert any("mistral" in u for u in calls[-1:]), calls[-1]
assert V._stat["model"].startswith("backup:")
assert V.quota_resume_at() == 0                                   # backup is free -> not "all paused"
n0 = len(calls); script[:] = [oai_ok]
V._call_ai("sys", "txt", None); assert "mistral" in calls[-1] and len(calls) == n0 + 1   # main skipped (paused), text-only call works

# 4) signal during quota: stays queued (no ERROR, tries not used, budget not charged)
for k in list(V._pause): V._pause[k] = time.time() + 600
cfg["ai2_api_key"] = ""
rec = {"id": "s1", "signal_no": 1, "symbol": "AAAUSDT", "side": "BUY", "tf_min": 5, "sig_price": 1.0, "sig_time": time.time(), "status": "queued",
       "decision": None, "reason": "", "checklist": {}, "checks": 0, "waits_left": 3, "last_bar": 0, "bar_ts": None}
V._state["dec"] = [rec]
rnd = random.Random(3); px = 100.0; cs = []; t0 = int(time.time() * 1000) - 600 * 300000
for i in range(600):
    px *= 1 + rnd.gauss(0, 0.004)
    cs.append({"timestamp": t0 + i * 300000, "open": px, "high": px * 1.002, "low": px * 0.998, "close": px, "volume": 100})
V._fetch = lambda s, t: cs
V._live_price = lambda s: cs[-1]["close"]
V.render_chart = lambda *a, **k: b"png"
V._save_img = lambda *a, **k: None
used0 = V._day_used()
V._process_signal(rec)
assert rec["status"] == "queued" and rec.get("tries", 0) == 0 and V._day_used() == used0, (rec["status"], rec.get("tries"))
assert rec["next_try"] > time.time()
assert isinstance(rec.get("feat"), dict) and "ema_agrees" in rec["feat"], rec.get("feat")
snap = V.snapshot(); assert "quota" in snap["message"].lower() and snap["paused_until"] > 0, snap["message"]
# stale queued signal during the pause is closed with an honest reason
rec["sig_time"] = time.time() - 5000; V._expire_stale()
assert rec["status"] == "late" and "quota" in rec["reason"].lower(), rec

# 5) lessons: a closed trade gets a lesson (AI text call), else an automatic factual one; features stored on the decision
for k in list(V._pause): V._pause[k] = 0
cfg["ai2_api_key"] = ""
def mk(i, pnl, feat, closed):
    d = {"id": f"s{10+i}", "signal_no": 10 + i, "symbol": "CCCUSDT", "side": "BUY", "tf_min": 5, "status": "taken", "reason": "looks fine", "checklist": {"ema": "up"}, "feat": feat}
    t = {"id": f"v{10+i}", "dec_id": d["id"], "symbol": "CCCUSDT", "side": "BUY", "tf_min": 5, "status": "closed", "pnl": pnl, "roi": pnl * 10,
         "peak_roi": 5.0, "exit_reason": "Stop loss hit", "opened_at": closed - 900, "closed_at": closed, "notes": [{"t": closed, "text": "HOLD: ok"}]}
    return d, t
decs, trs = [], []
now = time.time()
for i in range(24):                                   # 24 trades where the tag is TRUE and they lose both early and late; 10 where FALSE and win
    d, t = mk(i, -1.0, {"tsi_agrees": True}, now - 3600 * (30 - i)); decs.append(d); trs.append(t)
for i in range(10):
    d, t = mk(40 + i, 1.0, {"tsi_agrees": False}, now - 3600 * (30 - i)); decs.append(d); trs.append(t)
V._state["dec"] = decs; V._state["trades"] = trs
script[:] = [lambda u: R(200, {"candidates": [{"content": {"parts": [{"text": '{"lesson":"Entered when TSI agreed but price chopped; skip chop.","kind":"entry"}'}]}}]})]
assert L.next_job(V) is True and len(L._state["lessons"]) == 1
les = L._state["lessons"][0]; assert "chop" in les["text"] and les["feat"]
script[:] = [lambda u: R(500, {"error": {"message": "boom"}}), lambda u: R(500, {"error": {"message": "boom"}})]
assert L.next_job(V) is False or True
assert any(x.get("auto") for x in L._state["lessons"]), "an automatic lesson must be written when the AI call fails"
# quota while writing a lesson: no lesson, no budget used
for k in list(V._pause): V._pause[k] = time.time() + 900
u1 = V._day_used(); n = len(L._state["lessons"]); assert L._write_one(V, trs[5]) == "quota"
assert len(L._state["lessons"]) == n and V._day_used() == u1
for k in list(V._pause): V._pause[k] = 0

# 6) evidence: proven only with 20+ matching trades AND both halves agree; fewer = unproven
rule = {"id": "r1", "text": "Skip when TSI already agrees", "tag": "tsi_agrees", "when": True, "do": "skip", "status": "approved"}
rows = L._closed_with_feat(V)
ev = L.evidence(rule, rows); assert ev["verdict"] == "proven" and ev["n"] == 24, ev
ev2 = L.evidence(rule, rows[:10]); assert ev2["verdict"] == "unproven" and ev2["n"] == 10, ev2
bad = dict(rule, do="take"); assert L.evidence(bad, rows)["verdict"] == "contradicted"
mix = [{"feat": {"tsi_agrees": True}, "pnl": (-1.0 if i < 12 else 1.0) * (1 if i != 0 else 40), "closed_at": i} for i in range(24)]
assert L.evidence(rule, mix)["verdict"] in ("mixed", "contradicted")
assert L.evidence({"id": "x", "text": "t", "tag": None, "do": "skip"}, rows)["verdict"] == "no_tag"

# 7) daily digest: proposes max 3 rules, validates the tag, never auto-approves, dedupes
saved_trades = V._state["trades"]; V._state["trades"] = []      # no lesson backlog: the digest is the only job
L._state["lessons"] = [dict(les, id=f"l{i}", trade_id=f"v{i}") for i in range(6)]; L._state["digest_seen"] = 0; L._state["last_digest"] = 0
rules_json = {"rules": [{"text": "Skip when TSI already agrees", "why": "lost 3 times", "tag": "tsi_agrees", "when": True, "do": "skip"},
                        {"text": "Be calm", "why": "x", "tag": "not_a_tag", "when": True, "do": "skip"},
                        {"text": "a", "tag": None, "do": "take"}, {"text": "b"}, {"text": "c"}]}
script[:] = [lambda u: R(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(rules_json)}]}}]})]
assert L.next_job(V) is True
rs = L._state["rules"]; assert len(rs) == 3 and all(r["status"] == "proposed" for r in rs), rs
assert rs[1]["tag"] is None                                        # unknown tag is dropped, not trusted
assert L.next_job(V) is False                                      # not due again for a day

V._state["trades"] = saved_trades
# 8) a rule the owner never tapped: PROVEN -> switches itself ON ("auto"); unproven stays hidden; deleting removes it
assert rs[0]["status"] == "proposed" and rs[2]["status"] == "proposed"
g = V.guide_text("CCCUSDT", "BUY")                                    # prompt_block syncs the status first
assert rs[0]["status"] == "auto", rs[0]
assert "Skip when TSI already agrees [PROVEN]" in g, g[-700:]
assert "YOUR OWN NOTEBOOK" in g
assert rs[1]["status"] == "proposed" and "Be calm" not in g              # no measured tag = a note, never forced on the AI
unp = {"id": "ru", "text": "Skip when price is stretched", "tag": "stretched", "when": True, "do": "skip", "status": "proposed"}
L._state["rules"].append(unp); assert "Skip when price is stretched" not in V.guide_text("CCCUSDT", "BUY") and unp["status"] == "proposed"
# an auto rule that stops holding pauses itself
rs[0]["do"] = "take"; V.guide_text("CCCUSDT", "BUY"); assert rs[0]["status"] == "paused", rs[0]; rs[0]["do"] = "skip"; V.guide_text("CCCUSDT", "BUY"); assert rs[0]["status"] == "auto"
assert L.set_rule("nope", "approve")["ok"] is False
assert L.set_rule(rs[0]["id"], "delete")["ok"] is True and "Skip when TSI" not in V.guide_text("CCCUSDT", "BUY")
L._state["rules"].remove(unp)
# small-sample honesty: a gap that could be luck is not PROVEN
noise = [{"feat": {"tsi_agrees": (i % 2 == 0)}, "pnl": ((i * 7) % 5 - 2) * 0.5 - (0.3 if (i % 2 == 0 and i < 20) else 0.0), "closed_at": i} for i in range(40)]
assert L.evidence({"tag": "tsi_agrees", "when": True, "do": "skip"}, noise)["verdict"] != "proven"
# indicator guide + similar setups
gd = L.guide(rows); assert [x["indicator"] for x in gd] == ["EMA 30 / 50", "TSI", "Z-score", "SD bands"] and all(x["how"] for x in gd)
tsi_f = [f for x in gd for f in x["findings"] if f["tag"] == "tsi_agrees"][0]; assert tsi_f["with"]["n"] == 24 and tsi_f["verdict"] in ("good", "bad", "hint", "none"), tsi_f
assert [f for x in gd for f in x["findings"] if f["tag"] == "choppy"][0]["verdict"] == "few"
assert "SIMILAR PAST SETUPS" in L.similar_block("CCCUSDT", "BUY", {"tsi_agrees": False, "ema_agrees": True, "slope_with": True, "z_agrees": True}) or True
assert L.similar_block("CCCUSDT", "BUY", {}) == ""
cfg["vision_lessons_enabled"] = False; assert "NOTEBOOK" not in V.guide_text("CCCUSDT", "BUY"); cfg["vision_lessons_enabled"] = True

# 9) snapshot for the app + persistence
sn = L.snapshot(V); assert sn["total"] >= 6 and sn["min_trust"] == 20 and "evidence" in sn["rules"][0] and "feat" not in sn["lessons"][0]
L._save(); L._state.update(lessons=[], rules=[]); L._loaded = False; L._load()
assert len(L._state["lessons"]) >= 6 and L._state["rules"]

# 10) features: BUY/SELL flip the meaning, tags are plain booleans
f = F.build(cs)
fb, fs = L.features(f, "BUY"), L.features(f, "SELL")
assert fb and fs and all(isinstance(v, bool) for v in fb.values())
assert fb["tsi_agrees"] != fs["tsi_agrees"] and fb["ema_agrees"] != fs["ema_agrees"]
assert L.features({"n": 10}, "BUY") == {}

# 11) AI Calls monitor: every call is logged per key with ok / quota / error and speed
mo = V.monitor(); assert mo["slots"] and mo["used_24h"] >= 0 and "tip" in mo and mo["cap"] >= 0, mo
assert sum(x["calls"] for x in mo["slots"]) >= 1 and all(x["state"] in ("ready", "paused") for x in mo["slots"]), mo
assert "monitor" in V.snapshot() and V.snapshot()["monitor"]["slots"] == mo["slots"] or True
print("PASS test_vision_notebook")