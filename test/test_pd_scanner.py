"""test_pd_scanner.py - offline test of the Pump / Dump scanner (no network, no Binance): a synthetic market where one coin pumps and one dumps.
Run:  python3 test/test_pd_scanner.py   (from the repo folder)"""
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))
import pd_config as C
import pd_feed
import pd_learn
import pd_runner as R
import pd_store as ST
import pd_tracker
import api.pd_route as ROUTE


def run():
    random.seed(7)
    tmp = tempfile.mkdtemp()
    C.init(tmp)
    t0 = 1_800_000_000.0
    price = {"S%dUSDT" % i: 1.0 + i for i in range(60)}
    price["PUMPUSDT"], price["DUMPUSDT"], price["QUIETUSDT"] = 10.0, 10.0, 5.0
    vol = {s: 5e6 + random.random() * 5e6 for s in price}
    clock = {"m": 0.0}

    def fetch():
        m = clock["m"]
        out = []
        for s in price:
            tick = 0.0003 * random.uniform(-1, 1)
            v = 40000.0 * 20 / 60                     # USDT traded in one 20 s step
            if s == "PUMPUSDT" and 80 <= m < 84:
                tick, v = 0.005, v * 12
            if s == "PUMPUSDT" and 84 <= m < 100:
                tick, v = 0.0, v * 1.0
            if s == "PUMPUSDT" and m >= 100:
                tick, v = -0.0015, v * 0.3
            if s == "DUMPUSDT" and 85 <= m < 89:
                tick, v = -0.005, v * 12
            price[s] *= 1 + tick
            vol[s] += v
            out.append({"symbol": s, "lastPrice": str(price[s]), "quoteVolume": str(vol[s]), "priceChangePercent": "0.1"})
        out.append({"symbol": "BTCUSDT_250627", "lastPrice": "1", "quoteVolume": "9e9"})     # dated future: must be skipped
        out.append({"symbol": "TINYUSDT", "lastPrice": "1", "quoteVolume": "1000"})         # dead coin: must be skipped
        return out

    events = []
    feed = pd_feed.Feed(fetch)
    tr = pd_tracker.Tracker(lambda ev: (events.append(ev), ST.append("events", ev["day"], ev), tr_learn.add_start(ev) if ev["stage"] == "START" else None))
    tr_learn = pd_learn.Learner()
    for k in range(int(130 * 3)):                    # 130 minutes, one poll / 20 s
        clock["m"] = k / 3.0
        R.step(feed, tr, tr_learn, t0 + k * 20)
    stages = [(e["symbol"], e["side"], e["stage"]) for e in events]
    print("events:", stages)
    assert not any(e["symbol"].startswith(("S", "QUIET")) and e["symbol"] not in ("PUMPUSDT", "DUMPUSDT") for e in events), "a quiet coin gave an alert"
    assert ("PUMPUSDT", "pump", "START") in stages, "no pump START"
    assert ("DUMPUSDT", "dump", "START") in stages, "no dump START"
    assert ("PUMPUSDT", "pump", "RUNNING") in stages, "no pump RUNNING"
    assert not any(e["symbol"] == "PUMPUSDT" and e["side"] == "dump" and e["stage"] == "START" for e in events), "the pump coin was called a dump"
    n_start = sum(1 for e in events if e["symbol"] == "PUMPUSDT" and e["stage"] == "START")
    assert n_start == 1, "pump START repeated %d times (spam)" % n_start
    first = [e for e in events if e["symbol"] == "PUMPUSDT" and e["stage"] == "START"][0]
    assert 80 * 60 <= first["ts"] - t0 <= 83 * 60, "START came at minute %.1f" % ((first["ts"] - t0) / 60)
    # outcomes: run on another 70 minutes so the 60 min check finishes
    for k in range(int(130 * 3), int(210 * 3)):
        clock["m"] = k / 3.0
        R.step(feed, tr, tr_learn, t0 + k * 20)
    oc = ST.read_day("outcomes", first["day"]) + ST.read_day("outcomes", C.day_of(t0 + 210 * 60))
    print("outcomes:", [(o["symbol"], o["side"], o["real"], o["mfe"]) for o in oc])
    assert any(o["symbol"] == "PUMPUSDT" and o["real"] for o in oc), "the pump outcome was not saved as real"
    # API answers
    lv = R.live.__wrapped__(t0 + 210 * 60) if hasattr(R.live, "__wrapped__") else None
    d = ROUTE.day_view(first["day"], now=t0 + 210 * 60)
    assert d["pump"] and d["dump"], "day view empty"
    assert any(e.get("result", {}).get("state") == "real" for e in d["pump"]), "day view has no result on the pump START"
    # Round C: ONE card per coin move (the events WATCH / START / RUNNING / WEAK / END of one coin are one episode)
    pe = [e for e in d["pump"] if e["symbol"] == "PUMPUSDT"]
    assert len(pe) == 1, "the pump coin must be ONE episode card, got %d" % len(pe)
    assert pe[0]["started"] and pe[0]["ended"] and pe[0]["stages"][0] in ("WATCH", "START") and "START" in pe[0]["stages"] and pe[0]["stages"][-1] == "END", pe[0]["stages"]
    assert pe[0]["peak_gain"] > 3.0 and len(pe[0]["events"]) >= 4, "episode numbers look wrong"
    assert all(k in pe[0] for k in ("stage", "r5", "vr5", "score", "price", "time", "id", "symbol")), "an older app needs these keys"
    rep = tr_learn.run_tuner(t0 + 210 * 60, tr)
    assert rep["outcomes_14d"]["n"] >= 2
    assert not rep["changes_today"], "the tuner must not change thresholds with so few outcomes"
    print("report:", rep["outcomes_14d"], "OK")
    # a restart keeps the checked alerts waiting
    tr_learn.save_pending(t0)
    assert pd_learn.Learner().pending is not None


if __name__ == "__main__":
    run()
    print("test_pd_scanner: ALL OK")
