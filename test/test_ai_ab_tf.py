"""A/B board: a busy build must never answer with another timeframe's numbers. Run: python3 test/test_ai_ab_tf.py"""
import os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_ab_board as B

# a finished 3m answer exists
B._out_cache.clear()
B._out_cache["3m"] = (time.time(), {"tf": "3m", "insight": {"x": 1}, "signals": 5})

hold, go = threading.Event(), threading.Event()
def holder():
    with B._build_lock:       # another request is building right now
        go.set()
        hold.wait(5)
th = threading.Thread(target=holder); th.start(); go.wait(2)
try:
    r5 = B.build("5m")
    assert r5.get("building") is True and r5["tf"] == "5m" and r5.get("insight") is None, r5       # NOT the 3m answer
    r3 = B.build("3m")
    assert r3["tf"] == "3m" and r3["insight"] == {"x": 1}, r3                                      # same tf: last finished answer
    d = B._norm_tf("")                                                                             # default tf from settings
    r = B.build("")
    assert r["tf"] == d, r
    assert bool(r.get("building")) == (d != "3m"), r                                               # only 3m has a finished answer
finally:
    hold.set(); th.join()
print("ab_board timeframe guard ok")
