"""Smart Brain skip switch (smart_brain.gate_reason). No network. Run: cd backend && python3 test_brain_gate.py"""
import json, os, sys, tempfile, time
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smart_brain as B
ok = 0
def check(c, m):
    global ok
    assert c, "FAIL: " + m
    ok += 1
now = time.time()
def view(trust="earned", luck="solid", verdict="dislike", t=None, beat=None, src="MAIN", d=1):
    return {"beat": beat or now, "trust": {"verdict": trust}, "luck": {"verdict": luck},
            "signals": [{"s": "ABCUSDT", "d": d, "src": src, "t": (t or now - 60) * 1000, "verdict": verdict, "verdict_text": "Dislikes it: dirty setup (clean score 20)."}]}
def put(v, gate=None):
    B._save("smart_brain_view.json", v)
    if gate is not None:
        B.set_gate(gate)
check(B.gate_on() is False, "default is OFF")
put(view()); check(B.gate_reason("ABCUSDT", "BUY", now) is None, "OFF = never skips")
B.set_gate(True); check(B.gate_on() is True, "switch can be turned on")
r = B.gate_reason("ABCUSDT", "BUY", now)
check(r and r.startswith("Smart Brain skipped it") and "dirty" in r, "all conditions true -> skip with a reason")
check(B.gate_reason("ABCUSDT", "SELL", now) is None, "other side is not skipped")
check(B.gate_reason("XYZUSDT", "BUY", now) is None, "unknown coin = take it")
put(view(trust="not_yet")); check(B.gate_reason("ABCUSDT", "BUY", now) is None, "trust not earned = take it")
put(view(luck="maybe")); check(B.gate_reason("ABCUSDT", "BUY", now) is None, "luck test not solid = take it")
put(view(verdict="unsure")); check(B.gate_reason("ABCUSDT", "BUY", now) is None, "unsure = take it")
put(view(verdict="like")); check(B.gate_reason("ABCUSDT", "BUY", now) is None, "liked = take it")
put(view(t=now - 7200)); check(B.gate_reason("ABCUSDT", "BUY", now) is None, "old setup (2h) is not matched")
put(view(beat=now - 9999)); check(B.gate_reason("ABCUSDT", "BUY", now) is None, "stopped Brain = take it")
put(view(src="Z")); check(B.gate_reason("ABCUSDT", "BUY", now) is None, "only MAIN / BOTH setups match the main bot's signal")
put(view(d=-1)); check(B.gate_reason("ABCUSDT", "SELL", now) is not None, "SELL matches a sell setup")
B.set_enabled(False); check(B.gate_on() is True, "stopping the Brain keeps the gate flag")
B.set_enabled(True)
B.set_gate(False); put(view()); check(B.gate_reason("ABCUSDT", "BUY", now) is None, "turned OFF again")
check(B.status().get("gate") is False, "status shows the switch")
B._save("smart_brain_view.json", "garbage"); B.set_gate(True); check(B.gate_reason("ABCUSDT", "BUY", now) is None, "bad file never crashes the bot")
# the main bot's hook never raises and is OFF by default
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "recovered_bot", "app.py")).read()
check("smart_brain.gate_reason(symbol, signal.action)" in src and src.count("gate_reason") == 1, "one hook in the main bot")
print("OK %d checks" % ok)
