"""Part 5A: shadow outcomes, evidence grader (60/40), paper capital lock + sizing. Nothing here places a real order."""
import os, sys, threading, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import ai_candidates as AC, ai_grader as GR, ai_capital as CAP


def test_simulate_target_stop_timeout_and_cautious_tie():
    atr = 1.0
    up = [(100.5, 99.8, 100.2), (104.0, 100.0, 103.5)]           # entry 100, stop 98.5, target 103
    r = AC.simulate("BUY", 100.0, atr, up)
    assert r["o"] == "target" and r["r"] > 1.8 and r["r"] < 2.0, r      # +2R minus fees
    dn = [(100.3, 98.0, 98.4)]
    r = AC.simulate("BUY", 100.0, atr, dn)
    assert r["o"] == "stop" and r["r"] < -1.0, r
    tie = [(104.0, 98.0, 100.0)]                                  # both hit in one candle -> stop first
    assert AC.simulate("BUY", 100.0, atr, tie)["o"] == "stop"
    s = AC.simulate("SELL", 100.0, atr, [(100.3, 96.9, 97.5)])
    assert s["o"] == "target", s
    assert AC.simulate("BUY", 100.0, atr, [(100.2, 99.9, 100.0)] * 5) is None      # not decided yet
    t = AC.simulate("BUY", 100.0, atr, [(100.2, 99.9, 100.1)] * AC.MAX_BARS)
    assert t["o"] == "timeout"


def _rows(n, good_tok, bad_tok, good_r=0.8, bad_r=-1.0):
    rows = []
    for i in range(n):
        g = i % 2 == 0
        rows.append({"t": 1000 + i, "r": good_r if g else bad_r, "tk": [good_tok if g else bad_tok, "regime=TRENDING"], "src": "bot", "kind": "signal"})
    return rows


def test_grader_unproven_then_A_then_C():
    assert GR.grade(["sd_zone=SD0..1"], rows=_rows(10, "sd_zone=SD0..1", "sd_zone=SD>2"))["grade"] == "U"
    rows = _rows(80, "sd_zone=SD0..1", "sd_zone=SD>2")
    a = GR.grade(["sd_zone=SD0..1", "regime=TRENDING"], rows=rows)
    assert a["grade"] == "A" and a["exp_r"] > 0.25, a
    c = GR.grade(["sd_zone=SD>2"], rows=rows)
    assert c["grade"] == "C", c
    b = GR.grade(["volume=high"], rows=rows)
    assert b["grade"] == "B", b


def test_grader_needs_both_halves():
    rows = []
    for i in range(80):          # old half wins, new half loses for the same tag: NOT confirmed
        rows.append({"t": 1000 + i, "r": 1.0 if i < 48 else -1.0, "tk": ["sd_zone=SD0..1"], "src": "bot"})
    assert GR.grade(["sd_zone=SD0..1"], rows=rows)["grade"] == "B"


class FakeV:
    _lock = threading.RLock()
    _state = {"trades": []}
    cfg = {}

    @staticmethod
    def _cfg(k, d):
        return FakeV.cfg.get(k, d)

    @staticmethod
    def _day0_ts():
        return 1_000_000.0

    @staticmethod
    def _trade_view(t):
        return {"pnl": t.get("live", 0.0)}


def _own(pnl, closed_at=1_000_100.0, status="closed", live=0.0):
    return {"source": "own", "status": status, "pnl": pnl, "closed_at": closed_at, "opened_at": closed_at - 50, "live": live}


def test_capital_lock_sizing_and_reset():
    CAP._st.update(day0=0.0, lock="")
    FakeV.cfg = {}
    FakeV._state = {"trades": [_own(-3.0, closed_at=900_000.0), _own(5.0)]}
    s = CAP.status(FakeV)
    assert s["balance"] == 102.0 and s["day_start_balance"] == 97.0 and s["net"] == 5.0 and s["state"] == "active", s
    rec = {"source": "own", "lev": 10}
    ok, why, inv, wait = CAP.gate(FakeV, rec, 100.0, 98.0, "A")           # stop 2% -> notional 100, margin 10
    assert ok and abs(inv - 10.0) < 0.01, (ok, why, inv)
    ok, why, inv, wait = CAP.gate(FakeV, rec, 100.0, 98.0, "U")           # learning: half risk
    assert ok and abs(inv - 5.0) < 0.01
    ok, why, inv, wait = CAP.gate(FakeV, rec, 100.0, 98.0, "B")
    assert not ok and "quality over quantity" in why
    assert CAP.gate(FakeV, {"source": "bot"}, 100.0, 98.0, "C")[0], "bot-source trades are never touched"
    FakeV._state["trades"] += [_own(0.0, status="open"), _own(0.0, status="open")]
    ok, why, inv, wait = CAP.gate(FakeV, rec, 100.0, 98.0, "A")
    assert not ok and wait, "max open -> hold and ask again"
    FakeV._state = {"trades": [_own(31.0)]}
    assert "target reached" in CAP.lock_reason(FakeV)
    FakeV._state = {"trades": [_own(31.0), _own(-40.0)]}
    assert "target reached" in CAP.lock_reason(FakeV), "a lock stays for the day even if P&L falls back"
    FakeV._day0_ts = staticmethod(lambda: 1_086_400.0)                      # next trading day
    FakeV._state = {"trades": [_own(31.0, closed_at=1_000_100.0)]}
    s = CAP.status(FakeV)
    assert s["state"] == "active" and s["net"] == 0.0 and s["balance"] == 131.0, s
    FakeV._day0_ts = staticmethod(lambda: 1_000_000.0)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ALL test_capital_lab passed")
