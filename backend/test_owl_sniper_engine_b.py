"""test_owl_sniper_engine_b.py - checks for owl_sniper_engine_b.py (plain asserts, runs with `python test_owl_sniper_engine_b.py` or pytest).
Covers: bad rows are refused, dict and tuple candles give the same answer, warm-up is None not a guess, regime guard (flat = SIDEWAYS, UNKNOWN blocked),
the signal rules, no look-ahead (changing FUTURE candles never changes an OLD candle's numbers), and parity with the old owl_sniper_engine.py."""
import random

import owl_sniper_engine_b as B


def make(n=900, seed=5, vol=0.004, start=100.0, step=300):
    r, v, rows = random.Random(seed), start, []
    for k in range(n):
        o = v
        v *= 1.0 + r.gauss(0, vol)
        rows.append({"timestamp": 1700000000 + k * step, "open": o, "high": max(o, v) * 1.001, "low": min(o, v) * 0.999, "close": v})
    return rows


def test_bad_rows_refused():
    for bad in ({"timestamp": 1, "open": 1, "high": 1, "low": 2, "close": 1},        # high < low
                {"timestamp": 1, "open": 1, "high": 2, "low": 1, "close": 0},        # price 0
                {"timestamp": 1, "open": 1, "high": 2, "low": 1},                    # missing close
                {"timestamp": 1, "open": 1, "high": 2, "low": 1, "close": "x"}):     # not a number
        try:
            B.to_series([bad])
        except ValueError:
            continue
        raise AssertionError("bad row was accepted: %r" % (bad,))


def test_tuples_equal_dicts():
    d = make(300)
    t = [(x["timestamp"], x["open"], x["high"], x["low"], x["close"], 1.0) for x in d]
    a, b = B.build_features(d, {"sd_len": 50}), B.build_features(t, {"sd_len": 50})
    assert a["z"] == b["z"] and a["hist"] == b["hist"] and a["side_ok"] == b["side_ok"]


def test_warmup_is_none():
    S = B.build_features(make(120), {"sd_len": 100})
    assert S["sma"][98] is None and S["sma"][99] is not None
    assert B.regime_at(S, 99) == "UNKNOWN"                      # VI average needs 50 more candles
    assert B.warmup_end(S) == S["n"]                            # 120 candles are too few: never ready
    assert B.warmup_end(B.build_features(make(300), {"sd_len": 100})) == 99 + 49   # SD from 99, VI average 49 candles later


def test_flat_market_is_sideways_and_z_zero():
    rows = make(400)
    for x in rows[250:]:                                         # dead flat tail
        x.update(open=100.0, high=100.0, low=100.0, close=100.0)
    S = B.build_features(rows, {"sd_len": 60})
    assert S["z"][-1] == 0.0
    assert B.regime_at(S, S["n"] - 1) == "SIDEWAYS"


def test_unknown_when_young_and_signal_never_raises():
    S = B.build_features(make(30), {"sd_len": 20})
    for i in range(-1, 35):
        r = B.raw_signal(S, i)
        assert r["side"] is None
    assert B.latest_snapshot(make(30), {"sd_len": 20}) is None


def test_signal_rules_long_and_short():
    S = B.build_features(make(900, seed=11), {"sd_len": 60})
    seen = {"LONG": 0, "SHORT": 0}
    for i in range(S["n"]):
        r = B.raw_signal(S, i)
        if r["side"] == "LONG":
            assert S["long_x"][i] and r["hist"] > 0 and S["cfg"]["z_lo"] < r["z"] < S["cfg"]["z_hi"]
        if r["side"] == "SHORT":
            assert S["short_x"][i] and r["hist"] < 0 and -S["cfg"]["z_hi"] < r["z"] < -S["cfg"]["z_lo"]
        if r["side"]:
            seen[r["side"]] += 1
    assert seen["LONG"] + seen["SHORT"] > 0


def test_no_lookahead():
    rows = make(700, seed=9)
    cut = 500
    a = B.build_features(rows[:cut], {"sd_len": 60})
    changed = [dict(x) for x in rows]
    for x in changed[cut:]:                                      # wreck the future
        x.update(open=x["open"] * 3, high=x["high"] * 3, low=x["low"] * 3, close=x["close"] * 3)
    b = B.build_features(changed, {"sd_len": 60})
    for key in ("ema_f", "ema_s", "sma", "sd", "z", "tsi", "hist", "vi", "vi_avg", "side_ok", "long_x", "short_x"):
        assert a[key] == b[key][:cut], key


def test_stop_price_sides():
    S = B.build_features(make(400), {"sd_len": 60, "z_mult": 2.2})
    i = S["n"] - 1
    assert B.stop_price(S, i, "LONG") < S["sma"][i] < B.stop_price(S, i, "SHORT")
    assert abs(B.sd_price(S, i, 2) - (S["sma"][i] + 2 * S["sd"][i])) < 1e-12


def test_parity_with_old_engine():
    try:
        import owl_sniper_engine as OLD
    except Exception:                                            # old file not next to this one: skip, not fail
        return
    rows = make(900, seed=21)
    a, o = B.build_features(rows, {"sd_len": 100}), OLD.build_features(rows, {"sd_len": 100})
    for key in ("ema_f", "ema_s", "sma", "sd", "z", "hist", "vi", "vi_avg", "side_ok", "long_x", "short_x"):
        for x, y in zip(a[key], o[key]):
            assert (x is None and y is None) or x == y or abs(x - y) <= 1e-7 * max(1.0, abs(y)), key
    for i in range(a["n"]):
        assert B.raw_signal(a, i)["side"] == OLD.raw_signal(o, i)["side"]


if __name__ == "__main__":
    names = [k for k in sorted(globals()) if k.startswith("test_")]
    for k in names:
        globals()[k]()
        print("ok  ", k)
    print("ALL %d TESTS PASSED" % len(names))
