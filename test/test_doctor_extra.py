"""doctor_extra: top-3 actions, filters, health meter (pure functions, no network)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

import doctor_extra as X   # noqa: E402
from recovered_bot import strategy_doctor as SD   # noqa: E402


def test_summary():
    s = X.summary({"enough": True, "sample": 50, "min_sample": 30,
                   "avoid": [{"status": "confirmed", "title": "Very wide SD band", "saved_usdt": 120.0}],
                   "overall": {"n": 50, "net_pnl": -300.0, "win_rate": 8.0, "fee_total": 90}},
                  {"total": 10, "top": [{"verdict": "helps", "title": "Skip BB squeeze"}]})
    k = [a["kind"] for a in s["actions"]]
    assert k == ["AVOID", "DO", "FACT"] and "120" in s["actions"][0]["text"]
    w = X.summary({"enough": True, "avoid": []}, {"total": 5, "top": []})
    assert w["actions"][0]["kind"] == "WAIT" and w["actions"][1]["text"].startswith("Change nothing yet")
    assert X.summary(None, None)["actions"]            # never raises


def test_options_and_filter(monkeypatch=None):
    def tr(i, tf, sym):
        return {"action": "BUY", "roi_pct": -1.0 + (i % 3), "pnl_usdt": -1.0, "timeframe": tf, "symbol": sym,
                "opened_at_ts": 1000 + i, "quality_tag": "clean"}
    raw = [tr(i, "5m" if i % 2 else "15m", "BTCUSDT" if i % 3 else "ETHUSDT") for i in range(40)]
    o = X.options(raw)
    assert o["tfs"] == ["5m", "15m"] or o["tfs"] == ["5m", "15m"][::1], o
    assert "BTCUSDT" in o["coins"]

    class TS:
        @staticmethod
        def get_all_closed(limit, net=True):
            return raw
    old = X.trade_store
    X.trade_store = TS
    try:
        a = X.filtered("5m", "")
        b = X.filtered("", "ETHUSDT")
        c = X.filtered("", "")
    finally:
        X.trade_store = old
    assert a["filter"]["tf"] == "5m" and a["sample"] == 20
    assert b["sample"] == sum(1 for t in raw if t["symbol"] == "ETHUSDT")
    assert c["sample"] == 40


def test_health():
    assert X.health({}, None, 0, None) == {"state": "OK", "lines": ["Nothing is running slowly."]}
    h = X.health({"doctor": [1.0, 25.0, 0]}, "ai_lab", 45.0, {"process_cpu_pct": 95})
    assert h["state"] == "SLOW" and len(h["lines"]) == 3


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
