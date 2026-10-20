"""ai_ind_tracker + path logger 'ind' samples on FAKE data. Run: python3 test/test_ai_ind_tracker.py"""
import os, sys, random, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_ind_tracker as T, ai_path_logger as PL

random.seed(3)
px, cs = 100.0, []
for i in range(330):
    px *= 1 + random.uniform(-0.004, 0.004)
    cs.append({"timestamp": 1_700_000_000_000 + i * 180_000, "open": px, "high": px * 1.002, "low": px * 0.998, "close": px})
s = T.ind_sample(cs)
assert s and len(s) == 3 and all(isinstance(x, float) for x in s), s
assert T.ind_sample(cs[:50]) is None                      # not enough candles -> nothing saved, no crash
assert T.ind_sample([]) is None
print("ind_sample ok", s)

d = tempfile.mkdtemp()
PL.init(d)
pos = {"id": 7, "symbol": "C", "action": "BUY", "entry_price": 100.0, "leverage": 1, "opened_at_ts": 1000.0,
       "signal_stop_loss": 98.0}
PL.tick(pos, 0.5, sl=98.0, tps={1: 101, 2: 102, 3: 103, 4: 104})
key = PL.make_key(7, 1000.0)
assert PL.add_ind(key, [180.0, 1.2, 14.5, 9.0]) and not PL.add_ind("nope@0", [1, 1, 1, 1])
for i in range(450):
    PL.add_ind(key, [200.0 + i, 0.0, 0.0, 0.0])
assert len(PL._open[key]["ind"]) == 400                   # capped
PL.finish(dict(pos, closed_at_ts=1300.0, roi_pct=1.0, gross_roi_pct=1.0), "TP1")
line = json.loads(open(os.path.join(d, "ai_trade_paths.jsonl")).read().splitlines()[-1])
assert "ind" in line and len(line["ind"]) == 400
print("ALL PASS")
