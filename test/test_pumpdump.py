"""
test_pumpdump.py - unit checks for ai_pumpdump (no network, synthetic candles).
Run from repo root:  python test/test_pumpdump.py
"""
import math
import os
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from recovered_bot import ai_pumpdump as PD
from recovered_bot import ai_ind_features as F


def _candles(n=400, start=100.0, pump_at=None, dump_at=None, wave=0.15):
    """Oldest-first synthetic 15m candles. Optional single pump or dump spike."""
    out = []
    px = start
    base_ts = int(time.time()) - n * 900
    for i in range(n):
        o = px
        # mild noise
        drift = math.sin(i / 17.0) * wave
        if pump_at is not None and pump_at <= i < pump_at + 6:
            drift += 1.2  # strong up impulse
        if dump_at is not None and dump_at <= i < dump_at + 6:
            drift -= 1.2
        c = o * (1 + drift / 100.0)
        h = max(o, c) * 1.002
        l = min(o, c) * 0.998
        vol = 1000 + (500 if (pump_at and pump_at <= i < pump_at + 6) or (dump_at and dump_at <= i < dump_at + 6) else 0)
        out.append({
            "timestamp": (base_ts + i * 900) * 1000,
            "open": o, "high": h, "low": l, "close": c, "volume": vol,
        })
        px = c
    return out


def test_buyer_seller():
    c = _candles(40)
    # force last 8 green full bodies
    for i in range(-8, 0):
        o = c[i]["open"]
        c[i]["close"] = o * 1.008
        c[i]["high"] = c[i]["close"] * 1.001
        c[i]["low"] = o * 0.999
        c[i]["volume"] = 2000
    text, nums = PD.buyer_seller(c)
    assert "buyer" in text.lower() or nums.get("score", 0) > 0, text
    print("buyer_seller OK:", text[:80])


def test_detect_and_record():
    """STRICT: one injected pump must be found once (not 10 times), and a second pass adds nothing."""
    with tempfile.TemporaryDirectory() as td:
        PD.init(td)
        PD._state["events"] = []
        PD._state["stats"] = {}
        PD._state["seeded"] = {}
        PD._loaded = True
        c = _candles(700, pump_at=300, dump_at=520, wave=0.02)   # quiet background so only the injected moves count
        r = PD.seed_history("BTCUSDT", c, 15)
        assert r["ok"], r
        pumps = [e for e in PD._state["events"] if e["kind"] == "pump"]
        dumps = [e for e in PD._state["events"] if e["kind"] == "dump"]
        assert len(pumps) == 1 and len(dumps) == 1, (len(pumps), len(dumps))
        assert pumps[0]["before"] and pumps[0]["at_top"], "before / at_top snapshots must not be empty"
        assert pumps[0]["move_bars"] <= PD.WINDOW_BARS
        again = PD.seed_history("BTCUSDT", c, 15)
        assert again["added"] == 0, again
        # live path must not add the same event again
        assert PD.record_from_candles("BTCUSDT", c, 15) == 0
        snap = PD.snapshot()
        assert "events" in snap and "playbook" in snap and snap["total"] == 2
        print("detect OK: 1 pump + 1 dump, no duplicates, playbook lines:", len(snap["playbook"]))


def test_seed_per_coin():
    with tempfile.TemporaryDirectory() as td:
        PD.init(td)
        PD._state["events"] = []
        PD._state["seeded"] = {}
        PD._loaded = True
        c = _candles(700, pump_at=300, wave=0.02)
        a = PD.maybe_seed("AAAUSDT", lambda s, t: c, 15)
        b = PD.maybe_seed("BBBUSDT", lambda s, t: c, 15)
        a2 = PD.maybe_seed("AAAUSDT", lambda s, t: c, 15)
        assert a["ok"] and not a.get("skipped"), a
        assert b["ok"] and not b.get("skipped"), b          # second coin must NOT be blocked by the first
        assert a2.get("skipped"), a2
        print("seed per coin OK")


def test_prompt_block():
    with tempfile.TemporaryDirectory() as td:
        PD.init(td)
        PD._state["events"] = [{
            "id": "t1", "symbol": "BTCUSDT", "kind": "pump", "move_pct": 5.0,
            "outcome": "reverse", "after_ret": -2.1, "before": {"sd_label": "above_2sd", "z": 2.1, "tsi": 12},
            "ts": time.time(), "vol_ratio": 2.0, "tf_min": 15,
        }] * 6
        PD._rebuild_stats()
        block = PD.prompt_block("BTCUSDT", "BUY", _candles(40))
        assert "PUMP/DUMP" in block or "pump" in block.lower()
        print("prompt_block OK, len", len(block))


def test_zsma_read():
    c = _candles(450)
    feat = F.build(c)
    text = PD.zsma_read(feat, "BUY")
    print("zsma_read:", text[:100] if text else "(empty early)")
    assert isinstance(text, str)


def test_features_new_tags():
    from recovered_bot import ai_vision_lessons as L
    c = _candles(450, pump_at=420)
    feat = F.build(c)
    # ensure h/l present for after_pump tags
    if "h" not in feat:
        feat["h"] = [float(x["high"]) for x in c]
        feat["l"] = [float(x["low"]) for x in c]
    tags = L.features(feat, "BUY")
    print("new tags sample:", {k: tags[k] for k in tags if k in (
        "zsma_slope_with", "z_cross_ok", "chasing_move", "choppy")})
    assert "choppy" in tags or "ema_agrees" in tags
    for old in ("after_pump_top", "after_dump_bottom", "buyers_control", "sellers_control"):
        assert old not in L.TAGS, old                       # tags must be side-relative like the other tags
    assert "flow_with" in L.TAGS and "chasing_move" in L.TAGS


if __name__ == "__main__":
    test_buyer_seller()
    test_detect_and_record()
    test_seed_per_coin()
    test_prompt_block()
    test_zsma_read()
    test_features_new_tags()
    print("\nALL test_pumpdump checks passed.")
