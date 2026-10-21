"""
test_vision_final_checks.py - strict checks added by the reviewer for Rounds A/Z/B/C.

1. Regression guards: things earlier zips silently deleted or reverted.
2. Partial-profit P&L math with planted numbers (both legs, fees once).
3. The review step really handles PARTIAL (and refuses a second one / a losing one).
4. Own scanner: every cap and skip rule really stops a scan, and a TAKE is stamped source=own.
"""
import math
import os
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from recovered_bot import ai_vision as V          # noqa: E402
from recovered_bot import ai_vision_own as OWN    # noqa: E402
from recovered_bot import ai_vision_exits as XE   # noqa: E402
from recovered_bot import ai_vision_lessons as L  # noqa: E402
from recovered_bot import settings_store as SS    # noqa: E402


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def candles(n):
    out = []
    px = 100.0
    base = int(time.time()) - n * 900
    for i in range(n):
        o = px
        c = o * (1 + math.sin(i / 11) * 0.002)
        h = max(o, c) * 1.001
        l = min(o, c) * 0.999
        out.append({"timestamp": (base + i * 900) * 1000, "open": o, "high": h, "low": l, "close": c, "volume": 1000})
        px = c
    return out


# ------------------------------------------------------------------ 1. regression guards
def test_regression_guards():
    api = _read("backend", "api_server.py")
    for route in ('"/api/vision/pumpdump"', '"/api/vision/pumpdump/seed"', '"/api/vision/compare"',
                  '"/api/vision/own"', '"/api/vision/exits"'):
        assert route in api, f"endpoint {route} missing from api_server.py"
    prov = _read("frontend", "lib", "providers", "app_provider.dart")
    for fn in ("fetchVisionPumpdump", "seedVisionPumpdump", "fetchVisionCompare", "setVisionOwnEnabled", "fetchVisionExits"):
        assert fn in prov, f"{fn} missing from app_provider.dart (the Pump / Results tabs would not compile)"
    for fn in ("record_skip", "check_skip_hindsight", "skip_stats"):
        assert hasattr(L, fn), f"ai_vision_lessons.{fn} was deleted (skip hindsight feature)"
    assert "after_pump_top" not in L.TAGS and "after_dump_bottom" not in L.TAGS, "side-blind tags came back"
    assert "chasing_move" in L.TAGS and "flow_with" in L.TAGS
    for t in ("zsma_near", "zsma_bounce_with"):
        assert t in L.TAGS, t
    guard = _read("backend", "recovered_bot", "ai_guard.py")
    for f in ("ai_vision_own.py", "ai_vision_exits.py", "ai_pumpdump.py"):
        assert f in guard, f"{f} not in the ai_guard read-only list"
    tab = _read("frontend", "lib", "screens", "vision_tab_screen.dart")
    assert "double _dragDx" in tab and "['Pump', 6]" in tab and "Pump/Dump" not in tab
    assert "VisionCompareView(" in tab and "VisionOwnScanLine(" in tab
    assert "notJudged" in tab, "NOT JUDGED part of the today card was lost"
    assert V.CANDLES >= 600
    print("regression guards OK")


# ------------------------------------------------------------------ 2. partial math
def test_partial_pnl_math_exact():
    tr = {"id": "vx", "status": "open", "side": "BUY", "entry": 100.0, "lev": 1.0, "invest": 10.0, "fee_roi": 1.0,
          "sl": 99.0, "notes": [], "symbol": "TESTUSDT", "tf_min": 15, "peak_roi": 0.0,
          "partial_done": False, "partial_frac": 0.0, "partial_pnl": 0.0, "source": "bot"}
    leg = XE.apply_partial(tr, 102.0, 0.5)
    # gross 2%, half closed: 2*0.5 - fee 1.0*0.5 = 0.5% of 10 USDT = 0.05
    assert abs(leg - 0.05) < 1e-9, leg
    assert abs(tr["invest"] - 5.0) < 1e-9
    assert XE.apply_partial(tr, 103.0, 0.5) is None, "second partial must be refused"
    V._close_trade(tr, 104.0, "test")
    # final leg: gross 4% - fee 1% = 3% of remaining 5 USDT = 0.15 ; total 0.20
    assert abs(tr["pnl"] - 0.20) < 1e-6, tr["pnl"]
    # fee charged exactly once overall: unsplit equivalent would be (4-1)% of 10 = 0.30 only if no partial at 102
    print("partial pnl math OK", tr["pnl"])


# ------------------------------------------------------------------ 3. review handles PARTIAL
def _stub_review_env(ai_json):
    cs = candles(300)
    V._fetch = lambda sym, tf: cs
    V.render_chart = lambda *a, **k: b"png"
    V._call_ai = lambda system, text, png=None: (ai_json, None)
    V._live_price = lambda sym: None
    V._save_img = lambda *a, **k: None
    V._count = lambda: None
    return cs


def _trade(entry, side="BUY"):
    return {"id": "vr1", "dec_id": "d1", "status": "open", "side": side, "entry": entry, "lev": 1.0, "invest": 10.0,
            "fee_roi": 1.0, "sl": entry * 0.98, "target": entry * 1.05, "notes": [], "symbol": "TESTUSDT", "tf_min": 15,
            "peak_roi": 0.0, "tgt_bar": 0, "last_review_bar": 0, "bar_ts": None,
            "partial_done": False, "partial_frac": 0.0, "partial_pnl": 0.0, "source": "bot"}


def test_review_partial_taken_once_and_only_in_profit():
    saved = (V._fetch, V.render_chart, V._call_ai, V._live_price, V._save_img, V._count)
    try:
        with tempfile.TemporaryDirectory() as td:
            V.init(td)
            V._loaded = True
            cs = _stub_review_env('{"action":"PARTIAL","fraction":0.5,"reason":"band reached","new_stop":null,"new_target":null,"checklist":{}}')
            price = cs[-1]["close"]
            # in profit by 3% -> partial allowed
            tr = _trade(price / 1.03)
            with V._lock:
                V._state["trades"] = [tr]
            V._review(tr, "test")
            assert tr["partial_done"] is True and abs(tr["partial_frac"] - 0.5) < 1e-9, tr
            assert abs(tr["invest"] - 5.0) < 1e-9
            assert any("PARTIAL" in n["text"] for n in tr["notes"]), tr["notes"]
            assert tr["status"] == "open", "a partial must not close the trade"
            # second PARTIAL refused -> HOLD
            V._review(tr, "test2")
            assert abs(tr["invest"] - 5.0) < 1e-9
            assert any("refused" in n["text"] for n in tr["notes"]), tr["notes"]
            # losing trade: partial refused
            tr2 = _trade(price * 1.03)
            with V._lock:
                V._state["trades"] = [tr2]
            V._review(tr2, "test3")
            assert tr2["partial_done"] is False and abs(tr2["invest"] - 10.0) < 1e-9
            print("review PARTIAL OK")
    finally:
        (V._fetch, V.render_chart, V._call_ai, V._live_price, V._save_img, V._count) = saved


def test_review_trail_moves_stop_only_tighter():
    saved = (V._fetch, V.render_chart, V._call_ai, V._live_price, V._save_img, V._count)
    try:
        with tempfile.TemporaryDirectory() as td:
            V.init(td)
            V._loaded = True
            cs = candles(300)
            price = cs[-1]["close"]
            tr = _trade(price / 1.03)
            old_sl = tr["sl"]
            new_good = price * 0.995
            _stub_review_env('{"action":"TRAIL","reason":"lock gains","new_stop":%r,"new_target":null,"checklist":{}}' % new_good)
            with V._lock:
                V._state["trades"] = [tr]
            V._review(tr, "t")
            assert tr["sl"] == new_good and tr["sl"] > old_sl
            # a looser stop must be ignored
            _stub_review_env('{"action":"TRAIL","reason":"x","new_stop":%r,"new_target":null,"checklist":{}}' % (old_sl * 0.9))
            keep = tr["sl"]
            V._review(tr, "t2")
            assert tr["sl"] == keep, "stop was loosened"
            print("review TRAIL OK")
    finally:
        (V._fetch, V.render_chart, V._call_ai, V._live_price, V._save_img, V._count) = saved


# ------------------------------------------------------------------ 4. own scanner
class _Env:
    def __init__(self):
        self.saved = (V.enabled, V.quota_resume_at, V._fetch, V._process_signal, OWN._watchlist, OWN._prefilter)

    def restore(self):
        (V.enabled, V.quota_resume_at, V._fetch, V._process_signal, OWN._watchlist, OWN._prefilter) = self.saved


def _reset_own():
    OWN._hour_calls[:] = []
    OWN._last_bar.clear()
    OWN._DUE.clear()
    OWN._idx = 0
    for k in ("scanned", "passed", "asked", "took", "skipped"):
        OWN._stats[k] = 0
    OWN._stats["err"] = ""


def test_own_scanner_rules():
    env = _Env()
    try:
        with tempfile.TemporaryDirectory() as td:
            V.init(td)
            V._loaded = True
            V.enabled = lambda: True
            V.quota_resume_at = lambda: 0
            cs = candles(300)
            V._fetch = lambda sym, tf: cs
            OWN._watchlist = lambda: ["AAAUSDT", "BBBUSDT"]
            OWN._prefilter = lambda feat, side: (side == "BUY", {"slope_with": True})
            calls = []

            def fake_process(rec):
                calls.append(rec["symbol"])
                V._finish(rec, "taken", "TAKE", "test take")
                tr = {"id": "v" + str(rec["signal_no"]), "dec_id": rec["id"], "symbol": rec["symbol"], "side": rec["side"],
                      "status": "open", "source": rec.get("source"), "pnl": 0}
                with V._lock:
                    V._state["trades"].append(tr)
            V._process_signal = fake_process

            SS.update(vision_own_enabled=False)
            _reset_own()
            with V._lock:
                V._state["trades"] = []
                V._state["dec"] = []
            assert OWN.tick(V) is False and calls == [], "must do nothing while switched off"

            SS.update(vision_own_enabled=True, vision_own_max_calls_hour=2, vision_own_max_open=3, vision_own_daily_loss_cap=5)
            _reset_own()
            assert OWN.tick(V) is True and calls == ["AAAUSDT"], calls
            with V._lock:
                tr = V._state["trades"][0]
            assert tr["source"] == "own" and tr["id"].startswith("vo"), tr
            # same coin again, same bar: skipped (no double ask). The scan now goes on to the next coin in the same pass.
            OWN._idx = 0
            assert OWN.tick(V) is True and calls == ["AAAUSDT", "BBBUSDT"], calls
            # whole watchlist done for this candle: nothing more to ask
            assert OWN.tick(V) is False and calls == ["AAAUSDT", "BBBUSDT"], calls
            # hourly cap of 2 reached
            OWN._last_bar.clear()
            OWN._DUE.clear()
            OWN._idx = 0
            with V._lock:
                for t in V._state["trades"]:
                    t["status"] = "closed"
            assert OWN.tick(V) is False and len(calls) == 2, "hourly cap ignored"

            # max open cap
            SS.update(vision_own_max_calls_hour=50, vision_own_max_open=1)
            _reset_own()
            with V._lock:
                V._state["trades"] = [{"id": "vo9", "status": "open", "source": "own", "symbol": "ZZZUSDT", "pnl": 0}]
            before = len(calls)
            assert OWN.tick(V) is False and len(calls) == before, "max open ignored"

            # daily loss cap
            SS.update(vision_own_max_open=3)
            with V._lock:
                V._state["trades"] = [{"id": "vo8", "status": "closed", "source": "own", "symbol": "ZZZUSDT",
                                       "pnl": -6.0, "opened_at": time.time()}]
            _reset_own()
            assert OWN.tick(V) is False and len(calls) == before, "daily loss cap ignored"
            assert "loss cap" in OWN._stats["err"]

            # bot already fired on this coin and bar
            with V._lock:
                V._state["trades"] = []
                V._state["dec"] = [{"symbol": "AAAUSDT", "bar_ts": cs[-1]["timestamp"], "source": "bot", "id": "s1"}]
            _reset_own()
            OWN._watchlist = lambda: ["AAAUSDT"]
            assert OWN.tick(V) is False and len(calls) == before, "must skip when the bot fired on that bar"
            print("own scanner rules OK")
    finally:
        env.restore()
        SS.update(vision_own_enabled=False)


def test_own_uses_real_functions():
    src = _read("backend", "recovered_bot", "ai_vision_own.py")
    assert "market_watch" not in src and "_judge_one" not in src and "timeframe_min" not in src
    for name in ("_process_signal", "_tf_min", "_day0_ts", "_mark", "enabled", "quota_resume_at", "_fetch"):
        assert hasattr(V, name), f"ai_vision.{name} missing"
    from recovered_bot import status as S
    assert hasattr(S, "get_watchlist")
    print("own scanner uses real functions OK")


def test_today_card_is_bot_only():
    decs = [{"id": "s1", "signal_no": 1, "status": "taken", "sig_time": time.time(), "source": "bot"},
            {"id": "o1", "signal_no": 900001, "status": "skipped", "sig_time": time.time(), "source": "own"}]
    t = V._today_block([], decs)
    assert t["signals"] == 1 and t["taken"] == 1 and t["skipped"] == 0, t
    print("today card bot-only OK")


def test_rule_evidence_ignores_own_trades():
    with tempfile.TemporaryDirectory() as td:
        V.init(td)
        V._loaded = True
        with V._lock:
            V._state["dec"] = [{"id": "a", "feat": {"slope_with": True}}, {"id": "b", "feat": {"slope_with": True}}]
            V._state["trades"] = [
                {"status": "closed", "pnl": 1.0, "dec_id": "a", "source": "bot", "closed_at": 1},
                {"status": "closed", "pnl": 5.0, "dec_id": "b", "source": "own", "closed_at": 2},
            ]
        rows = L._closed_with_feat(V)
        assert len(rows) == 1 and rows[0]["pnl"] == 1.0, rows
        print("rule evidence bot-only OK")


if __name__ == "__main__":
    test_regression_guards()
    test_partial_pnl_math_exact()
    test_review_partial_taken_once_and_only_in_profit()
    test_review_trail_moves_stop_only_tighter()
    test_own_scanner_rules()
    test_own_uses_real_functions()
    test_today_card_is_bot_only()
    test_rule_evidence_ignores_own_trades()
    print("ALL test_vision_final_checks passed")
