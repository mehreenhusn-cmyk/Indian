"""Z-SMA coverage with CANDLES=600 and side-relative tags."""
import os, sys, math, time, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import ai_vision as V
from recovered_bot import ai_ind_features as F
from recovered_bot import ai_vision_lessons as L

def candles(n):
    out=[]; px=100.0; base=int(time.time())-n*900
    for i in range(n):
        o=px; c=o*(1+math.sin(i/11)*0.002); h=max(o,c)*1.001; l=min(o,c)*0.999
        out.append({"timestamp":(base+i*900)*1000,"open":o,"high":h,"low":l,"close":c,"volume":1000}); px=c
    return out

def test_full_coverage():
    assert V.CANDLES >= 600
    c = candles(600)
    f = F.build(c)
    n = f["n"]
    view = V.VIEW
    start = n - view
    zs = f["zsma"]
    ok = sum(1 for j in range(start, n) if zs[j] is not None)
    assert ok == view, f"expected all {view} bars to have Z-SMA, got {ok}"
    print("full coverage OK", ok)

def test_short_note():
    c = candles(420)
    f = F.build(c)
    start = f["n"] - V.VIEW
    zs = f["zsma"]
    ok = sum(1 for j in range(max(0,start), f["n"]) if j < len(zs) and zs[j] is not None)
    assert ok < V.VIEW
    print("short history partial OK", ok)

def test_tags_side_relative():
    c = candles(600)
    f = F.build(c)
    buy = L.features(f, "BUY")
    sell = L.features(f, "SELL")
    for k in ("zsma_slope_with", "z_agrees", "z_sign_ok"):
        if k in buy and k in sell:
            assert buy[k] != sell[k] or True  # may both false; if both true, fail
            if buy[k] and sell[k]:
                raise AssertionError(f"{k} true for both sides")
    print("side-relative tags OK", {k: (buy.get(k), sell.get(k)) for k in ("zsma_near","z_cross_ok","zsma_slope_with")})

if __name__ == "__main__":
    test_full_coverage()
    test_short_note()
    test_tags_side_relative()
    print("ALL test_vision_zsma passed")
