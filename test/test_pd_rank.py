"""test_pd_rank.py - offline test of Round 1 (Naye Movers + Chal rahe + TSI strength + chance). No network.
Run:  python3 test/test_pd_rank.py   (from the repo folder)"""
import math
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))
import pd_chance
import pd_config as C
import pd_feed
import pd_rank
import pd_tracker
import pd_tsi
import pd_runner as R
import pd_learn
import api.pd_route as ROUTE


def fake_klines(calls):
    def fetch(sym, tf, limit):
        calls.append((sym, tf))
        sec = pd_tsi.TF_SEC[tf]
        now = fake_klines.now
        last_open = math.floor(now / sec) * sec
        rows, p = [], 100.0
        rnd = random.Random(hash((sym, tf)) % 1000)
        for k in range(limit):
            o = (last_open - (limit - 1 - k) * sec) * 1000
            p *= 1 + 0.004 * math.sin(k / 7.0) + 0.001 * rnd.uniform(-1, 1)
            rows.append([o, p, p, p, p, 10, o + sec * 1000 - 1, 1000.0, 5, 0, 600.0, 0])      # taker buy quote 600 of 1000 = buyers 60%
        return rows
    return fetch


def test_klines():
    calls = []
    kl = pd_tsi.Klines(fake_klines(calls))
    t = 1_800_000_000.0
    fake_klines.now = t
    assert kl.refresh("AAAUSDT", "5m", t) == "ok"
    assert kl.refresh("AAAUSDT", "5m", t + 30) == "fresh", "refetched inside the same candle"
    d = kl.get("AAAUSDT", "5m")
    assert d and d["tsi"] is not None and d["z200"] is not None and d["zsm"] is not None, "indicator numbers missing: %s" % d
    assert abs(d["taker_buy_share"] - 0.6) < 1e-9
    nxt = kl.cache[("AAAUSDT", "5m")]["next"]
    fake_klines.now = nxt + 1
    assert kl.refresh("AAAUSDT", "5m", nxt + 1) == "ok", "no refetch after the candle closed"
    assert len(calls) == 2
    # hard cap per minute
    C.DEFAULTS["kline_calls_min"] = 3
    kl2 = pd_tsi.Klines(fake_klines([]))
    res = [kl2.refresh("S%dUSDT" % i, "5m", t) for i in range(5)]
    assert res.count("ok") == 3 and res.count("cap") == 2, res
    C.DEFAULTS["kline_calls_min"] = 40
    # 429 -> back off
    def bad(sym, tf, limit):
        raise pd_tsi.RateLimited(429, 120)
    kl3 = pd_tsi.Klines(bad)
    assert kl3.refresh("X", "5m", t) == "blocked" and kl3.refresh("Y", "5m", t + 5) == "blocked" and kl3.limited(t + 5)
    print("klines ok")


def test_tracker_one_side():
    ev = []
    T = 1_800_000_000.0
    tr = pd_tracker.Tracker(ev.append)
    base = {"p": 1.0, "r1": 0.1, "r5": 0.6, "r15": 0.6, "r30": 0.6, "vr1": 3.0, "vr5": 3.0, "flat": True, "rng": 1.0, "brk_up": False, "brk_dn": False, "warm": True}
    tr.eval_symbol("XUSDT", base, T, 1e7)
    assert ("XUSDT", "pump") in tr.states and tr.states[("XUSDT", "pump")]["stage"] == "WATCH"
    f = dict(base, r1=-1.0, r5=-1.6, r15=-1.6, vr1=12.0, vr5=12.0, brk_dn=True)
    tr.eval_symbol("XUSDT", f, T + 40, 1e7)
    assert ("XUSDT", "dump") in tr.states and ("XUSDT", "pump") not in tr.states, "WATCH + DUMP START at the same time"
    g = dict(base, r1=1.2, r5=1.8, vr1=14.0, vr5=14.0, brk_up=True)
    tr.eval_symbol("XUSDT", g, T + 100, 1e7)
    assert ("XUSDT", "pump") not in tr.states, "a coin is on both sides"
    # noise: a WATCH whose 5 min move fell under 0.5% is not shown in Right now
    tr2 = pd_tracker.Tracker(ev.append)
    tr2.eval_symbol("YUSDT", base, T, 1e7)
    tr2.eval_symbol("YUSDT", dict(base, r5=0.3, r1=0.0, vr5=2.5), T + 30, 1e7)
    assert tr2.snapshot()["pump"] == [], "a quiet coin (+0.3%) is in Right now"
    tr2.eval_symbol("YUSDT", dict(base, r5=0.8, vr5=2.5), T + 60, 1e7)
    assert len(tr2.snapshot()["pump"]) == 1
    print("tracker ok")


def test_chance():
    tmp = tempfile.mkdtemp()
    C.init(tmp)
    ch = pd_chance.Chance()
    t = 1_800_000_000.0
    assert ch.add("AUSDT", "pump", "new", 10.0, "k1", 70, t) and not ch.add("AUSDT", "pump", "new", 10.0, "k1", 70, t + 60), "same coin twice in 60 min"
    ch.track({"AUSDT": 10.4}, t + 600)
    ch.track({"AUSDT": 10.1}, t + 3700)
    assert ch.stats["buckets"]["k1"] == [1, 1], ch.stats
    r = ch.rate("k1", "pump", "new")
    assert r["est"] and r["checked"] == 1, r
    ch.stats["buckets"]["k2"] = [85, 140]
    r = ch.rate("k2", "pump", "new")
    assert (not r["est"]) and r["pct"] == 61 and r["worked"] == 85 and r["checked"] == 140, r
    print("chance ok")


def test_market():
    random.seed(11)
    tmp = tempfile.mkdtemp()
    C.init(tmp)
    t0 = 1_800_000_000.0
    names = ["C%02dUSDT" % i for i in range(60)] + ["CLIMBUSDT", "QUIETUSDT", "TOPUSDT"]
    price = {s: 1.0 + i * 0.1 for i, s in enumerate(names)}
    chg = {s: 20.0 - 0.3 * i for i, s in enumerate(names[:60])}
    chg["CLIMBUSDT"], chg["QUIETUSDT"], chg["TOPUSDT"] = 20.0 - 0.3 * 36, 20.0 - 0.3 * 40, 20.0 - 0.3 * 5 + 0.01
    vol = {s: 8e6 + random.random() * 4e6 for s in names}
    clock = {"m": 0.0}

    def fetch():
        m = clock["m"]
        out = []
        for s in names:
            tick, v = 0.0002 * random.uniform(-1, 1), 40000.0 * 20 / 60
            if s == "CLIMBUSDT" and 35 <= m < 75:
                tick, v = 0.0004, v * 6
                chg[s] = min(chg[s] + 0.3 / 3.0 * 0.5, 40.0)         # climbs in the 24h list
            if s == "QUIETUSDT" and 35 <= m < 75:
                chg[s] = min(chg[s] + 0.3 / 3.0 * 0.5, 40.0)         # climbs in the list but has NO volume and no move
            if s == "TOPUSDT":
                if 20 <= m < 60:
                    tick, v = 0.0006, v * 3
                if m >= 60:
                    chg[s] = 5.0                                     # falls out of the top 10 later: must stay visible
            price[s] *= 1 + tick
            vol[s] += v
            out.append({"symbol": s, "lastPrice": str(price[s]), "quoteVolume": str(vol[s]), "priceChangePercent": str(chg.get(s, 0.0))})
        return out

    calls = []
    fake_klines.now = t0
    kl = pd_tsi.Klines(fake_klines(calls))
    feed = pd_feed.Feed(fetch)
    ev = []
    tr = pd_tracker.Tracker(ev.append)
    lr = pd_learn.Learner()
    rk = pd_rank.Rank(kl, pd_chance.Chance())
    seen_mover, seen_quiet, run_seen, run_after = False, False, False, False
    for k in range(int(100 * 3)):
        clock["m"] = k / 3.0
        now = t0 + k * 20
        fake_klines.now = now
        R.step(feed, tr, lr, now, rk)
        s = rk.snapshot(now)
        pm = [c["symbol"] for c in s["movers"]["pump"]]
        dm = [c["symbol"] for c in s["movers"]["dump"]]
        assert not (set(pm) & set(dm)), "a coin on both sides"
        seen_mover = seen_mover or "CLIMBUSDT" in pm
        seen_quiet = seen_quiet or "QUIETUSDT" in pm
        rn = [c["symbol"] for c in s["running"]["pump"]]
        if "TOPUSDT" in rn:
            run_seen = True
        if clock["m"] > 70 and "TOPUSDT" in rn:
            run_after = True
        assert not (set(pm) & set(rn)), "a coin in both lists"
        for c in s["movers"]["pump"]:
            assert 0 <= c["strength"] <= 100 and c["chance"]["est"] and c["rank"] > 10
    assert seen_mover, "CLIMB (rank 37 -> top 15, volume 6x) never reached Naye Movers"
    assert not seen_quiet, "a coin with no volume and no move was shown"
    assert run_seen and run_after, "a top-10 coin was dropped from Chal rahe (seen=%s, after leaving top 10=%s)" % (run_seen, run_after)
    tops = [c for c in s["running"]["pump"] if c["symbol"] == "TOPUSDT"]
    assert tops and "tiring" in tops[0] and tops[0]["tf_ready"] > 0, tops
    assert any(t[1] == "5m" for t in calls) and len(calls) <= 40 * 100 / 1.0, "kline calls out of control: %d" % len(calls)
    out = ROUTE._safe(R.movers)
    assert out.get("state") in (None, "off"), out
    print("market ok: movers seen, quiet hidden, top-10 coin kept, kline calls %d" % len(calls))


if __name__ == "__main__":
    test_klines()
    test_tracker_one_side()
    test_chance()
    test_market()
    print("ALL OK")
