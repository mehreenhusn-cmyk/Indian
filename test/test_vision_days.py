"""Round E: trading-day boundary, idempotent rollup, timeline verdicts."""
import os, sys, tempfile, time
from datetime import datetime, timezone, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from recovered_bot import ai_vision as V
from recovered_bot import ai_vision_days as VD


def _ist_ts(y, m, d, hh, mm):
    """Build unix epoch for an IST wall-clock time."""
    ist = datetime(y, m, d, hh, mm, tzinfo=timezone.utc)
    return (ist - timedelta(hours=5, minutes=30)).timestamp()


def test_day_boundary():
    # 05:29 IST and 05:31 IST on 2026-10-21 must fall in different trading days
    t_before = _ist_ts(2026, 10, 21, 5, 29)
    t_after = _ist_ts(2026, 10, 21, 5, 31)
    k0 = VD.day_key(t_before)
    k1 = VD.day_key(t_after)
    assert k0 != k1, (k0, k1, t_before, t_after)
    # window length exactly 24h
    s, e = VD.day_window(0, t_after)
    assert abs((e - s) - 86400) < 1e-6
    s1, e1 = VD.day_window(1, t_after)
    assert abs(s - e1) < 1e-6  # yesterday ends where today starts
    print("boundary OK", k0, k1)


def test_rollup_idempotent_and_verdicts():
    with tempfile.TemporaryDirectory() as td:
        V.init(td)
        VD.init(td)
        V._loaded = True
        VD._loaded = True
        # plant around a known day start
        day0 = VD.day0_ts(_ist_ts(2026, 10, 21, 12, 0))
        base = day0 + 3600  # 06:30 IST

        with V._lock:
            V._state["dec"] = [
                {"id": "s1", "signal_no": 1, "symbol": "BTCUSDT", "side": "BUY", "status": "skipped",
                 "sig_time": base, "decided_at": base + 30, "reason": "stretched", "source": "bot", "sig_price": 100},
                {"id": "s2", "signal_no": 2, "symbol": "ETHUSDT", "side": "BUY", "status": "skipped",
                 "sig_time": base + 60, "decided_at": base + 90, "reason": "choppy", "source": "bot", "sig_price": 50},
                {"id": "s3", "signal_no": 3, "symbol": "SOLUSDT", "side": "SELL", "status": "taken",
                 "sig_time": base + 120, "decided_at": base + 150, "reason": "ok", "source": "bot", "sig_price": 20},
                {"id": "s4", "signal_no": 4, "symbol": "XRPUSDT", "side": "BUY", "status": "late",
                 "sig_time": base + 180, "decided_at": 0, "reason": "", "source": "bot", "sig_price": 1},
                {"id": "s5", "signal_no": 5, "symbol": "BNBUSDT", "side": "BUY", "status": "skipped",
                 "sig_time": base + 200, "decided_at": base + 210, "reason": "wait", "source": "bot", "sig_price": 5},
            ]
            V._state["trades"] = [
                {"id": "v3", "dec_id": "s3", "symbol": "SOLUSDT", "side": "SELL", "status": "closed",
                 "opened_at": base + 150, "closed_at": base + 500, "pnl": 1.5, "roi": 5, "source": "bot",
                 "exit_reason": "AI EXIT"},
            ]
        # bot outcomes map
        V._botmap = {"t": time.time(), "closed": {1: -2.0, 2: 3.0, 3: 0.5}, "open": {5}}

        now = base + 1000
        r1 = VD.rollup(V, now)
        r2 = VD.rollup(V, now)
        assert r1["signals"] == r2["signals"] == 5
        assert r1["taken"] == 1 and r1["skipped"] == 3 and r1["not_judged"] == 1
        assert r1["net"] == r2["net"] == 1.5
        assert r1["date"] == r2["date"]

        # timeline verdicts
        rows, _ = VD.timeline(V, 0, 50, now)
        by_no = {r["signal_no"]: r for r in rows}
        v1 = by_no[1]["verdict"]
        assert "skip saved" in v1.lower() or "saved 2" in v1.lower(), v1
        v2 = by_no[2]["verdict"]
        assert "skip cost" in v2.lower() or "cost 3" in v2.lower(), v2
        v3 = by_no[3]["verdict"]
        assert "AI took it" in v3 and "1.50" in v3, v3
        v4 = by_no[4]["verdict"]
        assert "never looked" in v4.lower(), v4
        v5 = by_no[5]["verdict"]
        assert "still open" in v5.lower(), v5
        assert by_no[1]["ai"]["delay_s"] == 30.0
        print("rollup+verdicts OK", r1["date"], len(rows))


def test_today_yesterday_split():
    with tempfile.TemporaryDirectory() as td:
        V.init(td)
        VD.init(td)
        V._loaded = True
        VD._loaded = True
        day0 = VD.day0_ts(_ist_ts(2026, 10, 21, 12, 0))
        with V._lock:
            V._state["dec"] = [
                {"id": "a", "signal_no": 10, "symbol": "BTCUSDT", "side": "BUY", "status": "taken",
                 "sig_time": day0 - 3600, "decided_at": day0 - 3500, "source": "bot"},
                {"id": "b", "signal_no": 11, "symbol": "ETHUSDT", "side": "BUY", "status": "taken",
                 "sig_time": day0 + 3600, "decided_at": day0 + 3700, "source": "bot"},
                {"id": "c", "signal_no": 12, "symbol": "SOLUSDT", "side": "BUY", "status": "taken",
                 "sig_time": day0 + 4000, "decided_at": day0 + 4100, "source": "own"},
            ]
            V._state["trades"] = [
                {"id": "va", "dec_id": "a", "status": "closed", "opened_at": day0 - 3500, "pnl": 1.0, "source": "bot", "side": "BUY"},
                {"id": "vb", "dec_id": "b", "status": "closed", "opened_at": day0 + 3700, "pnl": 2.0, "source": "bot", "side": "BUY"},
                {"id": "vc", "dec_id": "c", "status": "closed", "opened_at": day0 + 4100, "pnl": -0.5, "source": "own", "side": "BUY"},
            ]
        now = day0 + 8000
        today = VD.get_day_summary(V, 0, now)
        yest = VD.get_day_summary(V, 1, now)
        assert today["signals"] == 2  # bot+own today
        assert yest["signals"] == 1
        assert today["net_bot_source"] == 2.0
        assert today["net_own_source"] == -0.5
        assert yest["net_bot_source"] == 1.0
        print("today/yesterday split OK")


def test_missing_store_no_crash():
    with tempfile.TemporaryDirectory() as td:
        VD.init(td)
        with VD._lock:
            VD._state = {"days": {}}
            VD._loaded = False
            VD._file = os.path.join(td, "no_such_file.json")
        VD._load()
        assert VD._state["days"] == {}
        # rollup still works on empty
        with tempfile.TemporaryDirectory() as td2:
            V.init(td2)
            V._loaded = True
            with V._lock:
                V._state["dec"] = []
                V._state["trades"] = []
            row = VD.rollup(V)
            assert "date" in row and row["signals"] == 0
        print("missing store OK")


def test_dart_has_old_backend_note():
    tab = open(os.path.join(ROOT, "frontend/lib/screens/vision_tab_screen.dart")).read()
    assert "/api/vision/day" in tab or "Day timeline needs a newer backend" in tab
    assert "fetchVisionDay" in open(os.path.join(ROOT, "frontend/lib/providers/app_provider.dart")).read()
    print("dart old-backend note OK")


def test_timeline_trade_fields_and_title():
    """Timeline ai_trade carries entry/sl/target/id for the detail sheet."""
    import tempfile, time
    from recovered_bot import ai_vision as V
    from recovered_bot import ai_vision_days as VD
    with tempfile.TemporaryDirectory() as td:
        V.init(td)
        VD.init(td)
        V._loaded = True
        VD._loaded = True
        now = time.time()
        day0 = VD.day0_ts(now)
        with V._lock:
            V._state["dec"] = [{
                "id": "s99", "signal_no": 99, "symbol": "MEWUSDT", "side": "BUY",
                "status": "taken", "sig_time": day0 + 100, "decided_at": day0 + 120,
                "source": "own", "sig_price": 0.01, "reason": "ok",
            }]
            V._state["trades"] = [{
                "id": "vo99", "dec_id": "s99", "symbol": "MEWUSDT", "side": "BUY",
                "status": "closed", "entry": 0.01, "sl": 0.009, "target": 0.012,
                "exit": 0.008, "opened_at": day0 + 120, "closed_at": day0 + 500,
                "pnl": -18.99, "roi": -10, "source": "own", "exit_reason": "stop",
            }]
        rows, _ = VD.timeline(V, 0, 50, day0 + 1000)
        assert rows, "expected timeline rows"
        r = rows[0]
        at = r["ai_trade"]
        assert at["id"] == "vo99"
        assert at["entry"] == 0.01
        assert at["sl"] == 0.009
        assert at["target"] == 0.012
        assert at["source"] == "own"
        # chart title source-aware
        import inspect
        src = inspect.getsource(V.render_chart)
        assert "AI own signal" in src and "bot signal" in src
        print("timeline trade fields + title OK")


def test_source_filter_bot_own_total():
    """own-only filter returns only own rows; bot-only only bot; counts add up."""
    with tempfile.TemporaryDirectory() as td:
        V.init(td)
        VD.init(td)
        V._loaded = True
        VD._loaded = True
        day0 = VD.day0_ts(_ist_ts(2026, 10, 21, 12, 0))
        base = day0 + 3600
        with V._lock:
            V._state["dec"] = [
                {"id": "b1", "signal_no": 1, "symbol": "BTCUSDT", "side": "BUY", "status": "taken",
                 "sig_time": base, "decided_at": base + 10, "source": "bot", "sig_price": 100},
                {"id": "b2", "signal_no": 2, "symbol": "ETHUSDT", "side": "BUY", "status": "skipped",
                 "sig_time": base + 30, "decided_at": base + 40, "source": "bot", "sig_price": 50},
                {"id": "o1", "signal_no": 101, "symbol": "SOLUSDT", "side": "SELL", "status": "taken",
                 "sig_time": base + 60, "decided_at": base + 70, "source": "own", "sig_price": 20},
                {"id": "o2", "signal_no": 102, "symbol": "XRPUSDT", "side": "BUY", "status": "taken",
                 "sig_time": base + 90, "decided_at": base + 100, "source": "own", "sig_price": 1},
            ]
            V._state["trades"] = []
        V._botmap = {"t": time.time(), "closed": {}, "open": set()}
        now = base + 500
        all_rows, _ = VD.timeline(V, 0, 50, now, source=None)
        bot_rows, _ = VD.timeline(V, 0, 50, now, source="bot")
        own_rows, _ = VD.timeline(V, 0, 50, now, source="own")
        assert len(all_rows) == 4, len(all_rows)
        assert len(bot_rows) == 2, len(bot_rows)
        assert len(own_rows) == 2, len(own_rows)
        assert all((r.get("source") or "bot") != "own" for r in bot_rows)
        assert all((r.get("source") or "bot") == "own" for r in own_rows)
        assert len(bot_rows) + len(own_rows) == len(all_rows)
        payload = VD.day_payload(V, 0, now, source="own")
        assert all((r.get("source") or "bot") == "own" for r in payload["rows"])
        print("source filter OK", len(bot_rows), len(own_rows), len(all_rows))


if __name__ == "__main__":
    test_day_boundary()
    test_rollup_idempotent_and_verdicts()
    test_today_yesterday_split()
    test_missing_store_no_crash()
    test_dart_has_old_backend_note()
    test_timeline_trade_fields_and_title()
    test_source_filter_bot_own_total()
    print("\nALL test_vision_days passed")


