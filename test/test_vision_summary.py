"""
test_vision_summary.py - Round A: today counts add up, status words, planted day,
pump/dump plain sentences + SMALL SAMPLE under 20 events.

Run from repo root:  python3 test/test_vision_summary.py
"""
import os
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from recovered_bot import ai_vision as V
from recovered_bot import ai_pumpdump as PD


def _plant_day():
    """Plant a known set of decisions + trades for 'today' and check the block."""
    day0 = V._day0_ts()
    # clear in-memory state
    with V._lock:
        V._state["dec"] = []
        V._state["trades"] = []
        V._loaded = True

    # 2 taken, 3 skipped, 1 waiting, 1 queued, 2 not judged = 9 signals
    base = day0 + 3600
    plants = [
        ("s1", "taken", "TAKE"),
        ("s2", "taken", "TAKE"),
        ("s3", "skipped", "SKIP"),
        ("s4", "skipped", "SKIP"),
        ("s5", "expired", "SKIP"),
        ("s6", "waiting", "WAIT"),
        ("s7", "queued", None),
        ("s8", "late", None),        # AI was busy: NOT an AI skip
        ("s9", "error", None),       # AI check failed: NOT an AI skip
    ]
    for i, (sid, st, dec) in enumerate(plants):
        V._state["dec"].append({
            "id": sid, "signal_no": 100 + i, "symbol": "BTCUSDT", "side": "BUY",
            "tf_min": 15, "status": st, "decision": dec,
            "sig_time": base + i * 60, "decided_at": base + i * 60,
        })
    # one open trade + two closed (one stop, one exit) opened today
    V._state["trades"].append({
        "id": "v100", "dec_id": "s1", "symbol": "BTCUSDT", "side": "BUY", "tf_min": 15,
        "entry": 100.0, "sl": 99.0, "status": "open", "opened_at": base,
        "invest": 10.0, "fee_roi": 1.0, "lev": 1, "pnl": 0, "roi": 0,
    })
    V._state["trades"].append({
        "id": "v101", "dec_id": "s2", "symbol": "ETHUSDT", "side": "BUY", "tf_min": 15,
        "entry": 50.0, "sl": 49.0, "status": "closed", "opened_at": base + 10,
        "closed_at": base + 100, "exit_reason": "hard stop hit", "invest": 10.0,
        "fee_roi": 1.0, "lev": 1, "pnl": -1.5, "roi": -15.0,
    })
    V._state["trades"].append({
        "id": "v102", "dec_id": "sX", "symbol": "SOLUSDT", "side": "SELL", "tf_min": 15,
        "entry": 20.0, "sl": 21.0, "status": "closed", "opened_at": base + 20,
        "closed_at": base + 200, "exit_reason": "AI EXIT momentum fade", "invest": 10.0,
        "fee_roi": 1.0, "lev": 1, "pnl": 2.0, "roi": 20.0,
    })

    t = V._today_block(V._state["trades"], V._state["dec"])
    assert t["signals"] == 9, t
    assert t["taken"] == 2, t
    assert t["skipped"] == 3, t
    assert t["waiting"] == 1, t
    assert t["queued"] == 1, t
    assert t["not_judged"] == 2, t
    assert t["taken"] + t["skipped"] + t["waiting"] + t["queued"] + t["not_judged"] == t["signals"], t
    assert t["open"] == 1, t
    assert t["closed"] == 2, t
    assert t["stopped"] == 1, t
    assert t["exited"] == 1, t
    assert abs(t["net"] - 0.5) < 1e-6, t  # -1.5 + 2.0
    assert t["words"]["TAKEN"] == 2
    assert t["words"]["SKIPPED"] == 3
    assert t["words"]["WAITING"] == 2  # waiting + queued
    assert t["words"]["NOT JUDGED"] == 2
    assert t["words"]["STOPPED"] == 1
    assert t["words"]["EXITED"] == 1
    print("today block OK:", t)


def _plant_pumpdump_plain():
    with tempfile.TemporaryDirectory() as td:
        PD.init(td)
        PD._loaded = True
        PD._state["events"] = []
        # 10 pumps: 6 reverse, 3 continue, 1 sideways  -> under 20 = SMALL SAMPLE
        for i in range(10):
            outcome = "reverse" if i < 6 else ("continue" if i < 9 else "sideways")
            PD._state["events"].append({
                "id": f"p{i}", "symbol": "BTCUSDT", "kind": "pump", "move_pct": 5.0,
                "outcome": outcome, "after_ret": -2.0 if outcome == "reverse" else 1.0,
                "before": {"sd_label": "above_2sd", "z": 2.0, "tsi": 10},
                "ts": time.time(), "vol_ratio": 2.0, "tf_min": 15,
            })
        # 5 dumps: 2 reverse, 2 continue, 1 sideways
        for i in range(5):
            outcome = "reverse" if i < 2 else ("continue" if i < 4 else "sideways")
            PD._state["events"].append({
                "id": f"d{i}", "symbol": "ETHUSDT", "kind": "dump", "move_pct": 4.5,
                "outcome": outcome, "after_ret": 1.5 if outcome == "reverse" else -1.0,
                "before": {"sd_label": "below_2sd", "z": -2.0, "tsi": -8},
                "ts": time.time(), "vol_ratio": 1.8, "tf_min": 15,
            })
        PD._rebuild_stats()
        snap = PD.snapshot()
        plain = snap.get("plain") or []
        assert len(plain) >= 2, plain
        p0, p1 = plain[0], plain[1]
        # 6/10 = 60% dumped, 30% continued, 10% sideways
        assert "After a pump:" in p0 and "60%" in p0 and "dumped" in p0, p0
        assert "30%" in p0 and "10%" in p0 and "n=10" in p0, p0
        assert "SMALL SAMPLE" in p0, p0
        # 2/5 = 40% bounced, 40% continued, 20% sideways
        assert "After a dump:" in p1 and "40%" in p1 and "bounced" in p1, p1
        assert "SMALL SAMPLE" in p1, p1
        # dumps are present (not missing)
        assert (snap.get("stats") or {}).get("by_kind", {}).get("dump", {}).get("n") == 5
        print("plain sentences OK:")
        for line in plain:
            print(" ", line)


def _old_backend_hides_today():
    """If today key missing, card must not crash — simulated by empty dict path in UI;
    backend always sends today now. Just ensure function runs on empty lists."""
    t = V._today_block([], [])
    assert t["signals"] == 0
    assert t["taken"] == 0
    print("empty today OK")


def test_no_regressions_of_earlier_fixes():
    """Round A once reverted two earlier fixes and left _dragDx undeclared. Guard them."""
    import os
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    py = open(os.path.join(root, "backend", "recovered_bot", "ai_vision.py"), encoding="utf-8").read()
    assert 'feat["flow_with"]' in py and "buyers_control" not in py, "side-relative flow_with tag was reverted"
    dart = open(os.path.join(root, "frontend", "lib", "screens", "vision_tab_screen.dart"), encoding="utf-8").read()
    assert "double _dragDx" in dart, "_dragDx used but not declared (build breaker)"
    assert "['Pump', 6]" in dart and "Pump/Dump" not in dart, "tab label must stay 'Pump' (label stays short)"
    print("regression guard OK")


if __name__ == "__main__":
    # minimal init so paths exist
    with tempfile.TemporaryDirectory() as td:
        V.init(td)
        V._loaded = True
        _plant_day()
        _old_backend_hides_today()
        _plant_pumpdump_plain()
        test_no_regressions_of_earlier_fixes()
    print("\nALL test_vision_summary checks passed.")
