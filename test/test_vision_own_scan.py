"""AI Own scans the whole watchlist per candle, logs why it skipped, and day_view adds up. No network, no AI.
Run: python3 test/test_vision_own_scan.py"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def _candles(seed, n=300, tf=15):
    random.seed(seed)
    iv = tf * 60000
    last = int(time.time() * 1000 // iv * iv) - iv          # last CLOSED candle
    out, px = [], 100.0
    for i in range(n):
        px *= 1 + random.uniform(-0.004, 0.0045)
        out.append({"timestamp": last - (n - 1 - i) * iv, "open": px * 0.999, "high": px * 1.003,
                    "low": px * 0.997, "close": px, "volume": 10.0})
    return out


def main():
    from recovered_bot import ai_vision as V, ai_vision_own as O, settings_store
    settings_store.update(vision_own_enabled=True, vision_own_daily_loss_cap=0, vision_own_max_calls_hour=0, vision_own_max_open=3)
    V.enabled = lambda: True
    V.quota_resume_at = lambda: 0
    syms = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT"]
    O._watchlist = lambda: syms
    fetched = []
    V._fetch = lambda s, tf: (fetched.append(s) or _candles(syms.index(s) + 1, tf=tf))
    asked = []

    def fake_process(rec):
        asked.append(rec["symbol"])
        rec["status"] = "skipped"
        rec["reason"] = "test: price at -2SD but TSI below signal"
    V._process_signal = fake_process
    V._state["scan"] = []
    V._state["dec"] = []
    # pass 1: keep ticking until nothing is left to do
    guard = 0
    while O.tick(V) and guard < 20:
        guard += 1
    rows = V._state["scan"]
    assert {r["symbol"] for r in rows} == set(syms), [r["symbol"] for r in rows]      # every coin was scanned once
    for r in rows:
        assert r["result"] in ("no_setup", "skipped", "bot_fired"), r
        assert r["why"] and "ind" in r and "level" in r, r
        if r["result"] == "no_setup":
            assert r["why"].startswith("No setup") and r["ind"], r
        if r["result"] == "skipped":
            assert "test:" in r["why"] and r["level"] and r["ind"], r
    n_fetch = len(fetched)
    # pass 2 right away: same candle -> no new scans and no new network calls
    assert O.tick(V) is False
    assert len(V._state["scan"]) == len(rows) and len(fetched) == n_fetch, (len(fetched), n_fetch)
    # a cap blocks asking but says why
    settings_store.update(vision_own_max_calls_hour=1)
    O._hour_calls[:] = [time.time()]
    assert O.tick(V) is False and "limit" in O.scan_stats()["err"].lower(), O.scan_stats()
    # day_view adds up
    dv = O.day_view(V, 0)
    assert dv["own"]["scanned"] == len(rows) and sum(dv["own"]["results"].values()) == len(rows), dv["own"]
    assert dv["bot"]["signals"] == 0 and dv["own"]["margin"] == 0, dv
    print("PASS test_vision_own_scan", dv["own"]["results"], "asked", len(asked))


if __name__ == "__main__":
    main()
