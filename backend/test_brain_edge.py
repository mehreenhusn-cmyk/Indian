"""Batch 3a - open trade edge decay (observation only). Run: cd backend && python3 test_brain_edge.py"""
import copy, hashlib, json, math, os, random, re, sqlite3, sys, tempfile, time
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "recovered_bot"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_edge as BE
import dual_lab as D
import filter_lab as FL
import tag_lab as TL
import trade_archive as TA

HERE = os.path.dirname(os.path.abspath(__file__))
# sha256 of the fake-market run below, made with the dual_lab.py from BEFORE Batch 3a (the Batch 2 code): trades (without edge / clock keys), rows, seen
GOLDEN = "da12ec57218f89783e6432849e85ebfc1ffdc88c92ab5c975967f2f8795e7d38"
N_ALL = 140
I0 = 100          # entry candle index of the synthetic trades


# ---------------------------------------------------------------- synthetic candles + indicators (hand-made numbers)
def mk(n, **ov):
    """S and Z for a LONG that is going well: price up 0.1 per candle, every one of the 6 reasons points with the trade.
    ov = {key: {index: value}} or {key: callable(index)} to bend single numbers."""
    S = {"n": n, "t": [1_000_000 + 300_000 * k for k in range(n)], "c": [100.0 + 0.1 * k for k in range(n)],
         "tsi": [10.0] * n, "diff": [2.0] * n, "z": [1.0] * n, "zsma": [0.2] * n, "e50": [90.0] * n, "std": [1.0] * n, "width": [1.0] * n,
         "xup": [False] * n, "xdn": [False] * n, "wup": [0] * n, "wdn": [0] * n}
    S["h"] = [x + 0.05 for x in S["c"]]
    S["l"] = [x - 0.05 for x in S["c"]]
    Z = {"zf": [0.8] * n, "zs": [0.5] * n, "up": [False] * n, "dn": [False] * n}
    for key, v in ov.items():
        tgt = Z if key in Z else S
        for idx in range(n):
            if callable(v):
                tgt[key][idx] = v(idx)
            elif idx in v:
                tgt[key][idx] = v[idx]
    return S, Z


def trade(S, d=1, i=I0):
    entry = S["c"][i]
    return {"id": "T", "s": "AAAUSDT", "f": "5m", "d": d, "status": "open", "take": True, "entry": entry, "sl": entry * (1 - 0.01 * d)}


def lv_of(S, i, d, mfe=None, gb=0.0, lev=10.0, fee=1.0):
    j = S["n"] - 1
    gross = (S["c"][j] - S["c"][i]) / S["c"][i] * 100.0 * d * lev
    return {"net": gross - fee, "mfe": max(0.0, gross) if mfe is None else mfe, "giveback": gb}


def obs(S, Z, tr=None, d=1, i=I0, **kw):
    tr = tr or trade(S, d, i)
    e = BE.observe(tr, S, Z, i, lv_of(S, i, d, **kw), 10.0, 1.0)
    assert e is not None and tr["edge"] is e
    return e


# ---------------------------------------------------------------- 1. labels
def test_strong_trade_is_strong():
    S, Z = mk(I0 + 10)
    e = obs(S, Z)
    assert e["st"] == "STRONG" and e["sc"] == 6 and e["s0"] == 6 and e["sw"] == "111111" and e["pg"] == "progressing", e
    assert e["n"] == 9 and e["v"] == "e1" and e["ev"] == [0, 0, 0] and e["ea"] is None


def test_reversed_trade_is_reversed():
    n = I0 + 12
    S, Z = mk(n, diff=lambda k: 2.0 if k < n - 2 else -1.5, tsi=lambda k: 10.0 if k < n - 2 else -4.0, xdn={n - 2: True})
    e = obs(S, Z)
    assert e["st"] == "REVERSED" and e["ev"] == [1, 0, 0] and e["ea"] == 1 and e["th"] < 0, e


def test_weakening_when_support_drops_by_two():
    n = I0 + 12
    S, Z = mk(n, diff=lambda k: 2.0 if k < n - 1 else -0.5, zsma=lambda k: 0.2 if k < n - 1 else 2.0)     # TSI line + ZSM turn, no opposite event
    e = obs(S, Z)
    assert e["sc"] == 4 and e["s0"] == 6 and e["st"] == "WEAKENING" and e["ev"] == [0, 0, 0], e


def test_weakening_by_warning_arrow_and_by_giveback():
    n = I0 + 12
    S, Z = mk(n, wdn={n - 1: 1})
    assert obs(S, Z)["st"] == "WEAKENING"
    S, Z = mk(n)
    e = obs(S, Z, mfe=40.0, gb=25.0)                       # 1R = 10 ROI points, MFE 4R, gave back 62% of it
    assert e["st"] == "WEAKENING" and "gave back" in e["why"], e
    S, Z = mk(n)
    assert obs(S, Z, mfe=40.0, gb=10.0)["st"] == "STRONG"   # only 25% given back


def test_stable_and_new_and_unknown():
    n = I0 + 12
    S, Z = mk(n, zsma=lambda k: 0.2 if k < n - 1 else 2.0)                    # support 5 of 6, one lower than at entry
    assert obs(S, Z)["st"] == "STABLE"
    S, Z = mk(I0 + 2)                                                         # one closed candle after the entry
    e = obs(S, Z)
    assert e["st"] == "NEW" and e["n"] == 1
    S, Z = mk(n, e50={n - 1: None})
    assert obs(S, Z)["st"] == "UNKNOWN"


def test_short_trade_mirrors_the_long():
    n = I0 + 10
    S, Z = mk(n, c=lambda k: 100.0 - 0.1 * k, tsi=lambda k: -10.0, diff=lambda k: -2.0, z=lambda k: -1.0, zsma=lambda k: -0.2,
              e50=lambda k: 110.0, zf=lambda k: -0.8, zs=lambda k: -0.5)
    S["h"] = [x + 0.05 for x in S["c"]]; S["l"] = [x - 0.05 for x in S["c"]]
    e = obs(S, Z, d=-1)
    assert e["st"] == "STRONG" and e["sc"] == 6 and e["zv"] == 1.0 and e["th"] == 2.0 and e["tv"] == 10.0, e      # all "with trade" numbers are positive


# ---------------------------------------------------------------- 2. numbers match a hand calculation
def test_slopes_and_counts_match_hand_calculation():
    n = I0 + 10                                             # j = n-1 = 109, j-3 = 106, j-5 = 104
    S, Z = mk(n, z={n - 1: 1.0, n - 4: 0.4, n - 6: 0.5}, diff={n - 1: 2.0, n - 4: 1.5}, width={n - 1: 1.2, n - 6: 1.0},
              e50={n - 1: 98.0, n - 6: 97.0}, std={n - 1: 2.0}, tsi={n - 1: 12.0, n - 6: 9.0})
    e = obs(S, Z)
    assert e["zs"] == 0.6 and e["ths"] == 0.5, e                        # (1.0-0.4), (2.0-1.5)
    assert e["wd"] == 20.0, e                                            # 1.2 / 1.0
    j = n - 1
    assert e["ed"] == round((S["c"][j] - 98.0) / 2.0, 2) and e["es"] == 0.5, e      # (c - e50) / std ;  (98-97) / 2
    assert e["pm"] == [1, 1, 1] and e["ag"] == 1
    assert e["sc"] == 6 and e["s3"] == 5 and e["s0"] == 6          # 3 candles ago Z (0.4) was under both its EMAs: one reason less
    risk = abs(S["c"][I0] - trade(S)["sl"]) / S["c"][I0] * 100.0 * 10.0
    gross = (S["c"][j] - S["c"][I0]) / S["c"][I0] * 100.0 * 10.0
    assert e["roi"] == round(gross - 1.0, 1) and e["mfe"] == round(gross, 1) and e["gb"] == 0.0 and risk > 0


def test_events_and_price_vs_z_disagreement():
    n = I0 + 14
    S, Z = mk(n, xdn={I0 + 3: True}, wdn={I0 + 6: 1}, dn={I0 + 8: True},
              z=lambda k: 1.0 if k < n - 5 else 1.0 - 0.1 * (k - (n - 6)))      # Z falls while price rises
    e = obs(S, Z)
    assert e["ev"] == [1, 1, 1] and e["ea"] == n - 1 - (I0 + 8), e
    assert e["ag"] == 0 and e["pm"][0] == 1 and e["pm"][1] == -1, e


def test_mfe_age_counts_candles_since_the_best():
    n = I0 + 10
    S, Z = mk(n, h={I0 + 4: 120.0})
    assert obs(S, Z)["ma"] == n - 1 - (I0 + 4)


# ---------------------------------------------------------------- 3. frequency, size, history
def test_one_observation_per_closed_candle_and_history_is_capped():
    tr = None
    for n in range(I0 + 2, I0 + 2 + 200):
        S, Z = mk(n)
        tr = tr or trade(S)
        e = obs(S, Z, tr=tr)
        again = BE.observe(tr, S, Z, I0, lv_of(S, I0, 1), 10.0, 1.0)         # the same closed candle again (the 6-8 s loop): no new row
        assert again is e
    assert len(e["hs"]) == len(e["hc"]) == len(e["hr"]) == len(e["hz"]) == BE.MAX_HIST
    assert e["n"] == 200 and e["f0"] == 1
    size = len(json.dumps(e, separators=(",", ":")))
    assert size < 1800, size                                                 # lightweight even when the history is full
    assert len(json.dumps(BE.slim_edge(tr))) < size / 2 and "hs" not in BE.slim_edge(tr)


def test_observer_is_cheap():
    S, Z = mk(I0 + 280)
    tr = trade(S)
    t0 = time.perf_counter()
    for _ in range(50):
        tr.pop("edge", None)
        BE.observe(tr, S, Z, I0, lv_of(S, I0, 1), 10.0, 1.0)
    ms = (time.perf_counter() - t0) / 50 * 1000.0
    print("   observe on a 280-candle trade: %.2f ms" % ms)
    assert ms < 15.0, ms


# ---------------------------------------------------------------- 4. safety: nothing but tr["edge"] changes, nothing is observed that should not be
def test_observer_changes_only_the_edge_key():
    n = I0 + 12
    S, Z = mk(n)
    tr, lv = trade(S), lv_of(S, I0, 1)
    before = copy.deepcopy((S, Z, lv, tr))
    BE.observe(tr, S, Z, I0, lv, 10.0, 1.0)
    assert (S, Z, lv) == before[:3]
    tr2 = dict(tr); tr2.pop("edge")
    assert tr2 == before[3]


def test_only_open_taken_trades_are_observed():
    S, Z = mk(I0 + 12)
    for kw in ({"status": "skipped", "take": False}, {"status": "closed"}, {"status": "skipped_done", "take": False}):
        tr = dict(trade(S), **kw)
        assert BE.observe(tr, S, Z, I0, lv_of(S, I0, 1), 10.0, 1.0) is None and "edge" not in tr
    tr = trade(S)
    assert BE.observe(tr, S, Z, I0, None, 10.0, 1.0) is None and "edge" not in tr           # no replay result
    assert BE.observe(tr, S, Z, I0 + 11, lv_of(S, I0, 1), 10.0, 1.0) is None                # no closed candle after the entry


def test_a_crash_in_the_observer_never_reaches_the_bot():
    S, Z = mk(I0 + 12)
    assert BE.observe({"status": "open"}, S, Z, I0, {"mfe": 0}, 10.0, 1.0) is None          # broken trade dict: no raise
    tr = trade(S)
    assert BE.observe(tr, {"n": 5}, Z, I0, lv_of(S, I0, 1), 10.0, 1.0) is None              # broken candles: no raise
    BE.close({"edge": 5}); BE.close({}); BE.close(None)                                      # close() never raises either
    # and the hook in process(): even an observer that raises must not stop process()
    saved = D.BE
    class Boom:
        observe = staticmethod(lambda *a, **k: 1 / 0)
        close = staticmethod(lambda *a, **k: 1 / 0)
        slim_edge = staticmethod(lambda t: None)
    try:
        D.BE = Boom
        d = _run_market(11, "5m", step=6)
        assert d["trades"]
    finally:
        D.BE = saved


# ---------------------------------------------------------------- 5. trading behaviour unchanged (golden hash from the pre-B3a code)
def _candles(tf, n, seed, base=1_760_000_000_000):
    rnd, step = random.Random(seed), FL.TF_MS[tf]
    latest = (base // step) * step - step
    p, out = 100.0, []
    for k in range(n):
        o = p
        p = max(1.0, p * (1 + rnd.gauss(0, 0.004) + 0.0008 * math.sin(k / 30.0)))
        out.append({"timestamp": latest - (n - 1 - k) * step, "open": o, "high": max(o, p) * 1.001, "low": min(o, p) * 0.999, "close": p, "volume": 1.0})
    return out


def _run_market(seed, tf, step=2):
    names = list(TL.EXITS.keys())
    cc = _candles(tf, 900, seed)
    d = {"rows": {}, "trades": [], "seen": {}, "boot": {}, "fetched": {}}
    for cut in range(420, 900, step):
        D.process(d, "BBBUSDT", tf, cc[:cut], False, cc[cut - 1]["timestamp"] + FL.TF_MS[tf] + 5000, None, names)
    return d


def _strip(d):
    return [[{k: v for k, v in t.items() if k not in ("opened", "closed_at", "edge")} for t in d["trades"]], d["rows"], d["seen"]]


def test_process_results_identical_with_and_without_the_hook():
    res, edges = {}, 0
    saved = D.BE
    try:
        for label, mod in (("hook", saved), ("nohook", None)):
            D.BE = mod
            res[label] = [_strip(_run_market(s, tf)) for s, tf in ((11, "5m"), (23, "5m"), (31, "15m"))]
            if mod:
                edges = sum(1 for s, tf in ((11, "5m"),) for t in _run_market(s, tf)["trades"] if "edge" in t)
    finally:
        D.BE = saved
    dump = lambda x: json.dumps(x, sort_keys=True, default=str)
    assert dump(res["hook"]) == dump(res["nohook"])
    assert hashlib.sha256(dump(res["hook"]).encode()).hexdigest() == GOLDEN       # = what the code BEFORE Batch 3a produced
    assert edges > 10                                                               # and the hook really measured trades


def test_boot_replay_is_not_observed():
    names = list(TL.EXITS.keys())
    cc = _candles("5m", 900, 11)
    d = {"rows": {}, "trades": [], "seen": {}, "boot": {}, "fetched": {}}
    for cut in range(420, 900, 2):
        D.process(d, "BBBUSDT", "5m", cc[:cut], True, cc[cut - 1]["timestamp"] + 305000, None, names)
    assert d["trades"] and not any("edge" in t for t in d["trades"])


def test_real_indicators_give_sane_edges():
    d = _run_market(23, "5m")
    es = [t["edge"] for t in d["trades"] if "edge" in t]
    assert len(es) > 10
    for e in es:
        assert e["st"] in ("STRONG", "STABLE", "WEAKENING", "REVERSED", "NEW", "UNKNOWN") and 0 <= e["sc"] <= 6 and 0 <= e["s0"] <= 6
        assert e["pg"] in ("progressing", "stalling", "reversing") and e["mfe"] >= 0 and e["gb"] >= 0
        assert len(e["hs"]) == len(e["hc"]) == len(e["hr"]) == len(e["hz"]) and len(e["hs"]) <= BE.MAX_HIST
        json.dumps(e)
    assert all(t["edge"].get("done") == 1 for t in d["trades"] if "edge" in t and t["status"] == "closed")      # closing marks the observation as ended
    assert all(not t.get("edge", {}).get("done") for t in d["trades"] if t["status"] == "open")


def test_nothing_that_decides_reads_the_edge():
    pat = re.compile(r"edge", re.I)
    for f in ("strategy.py", "paper_trader.py", "tag_lab.py", "brain_own.py", "smart_brain_exit.py", "brain_exit.py", "brain_exit_pick.py",
              "brain_tp_hold.py", "filter_lab.py", "dual_tp_ext.py", "brain_meta.py", "trade_archive.py"):
        p = os.path.join(HERE, f) if os.path.exists(os.path.join(HERE, f)) else os.path.join(HERE, "recovered_bot", f)
        if os.path.exists(p):
            assert "brain_edge" not in open(p).read() and 'tr["edge"]' not in open(p).read(), f
    src = open(os.path.join(HERE, "dual_lab.py")).read()
    uses = [l for l in src.splitlines() if re.search(r'BE\.|"edge"', l)]
    assert uses and all(re.search(r"BE\.(close|observe|slim_edge)|_edge_slim|B3a", l) for l in uses), uses     # only the close marker, the observer hook and the slim view touch it
    sb = open(os.path.join(HERE, "smart_brain.py")).read()
    assert len([l for l in sb.splitlines() if re.search(r'brain_edge|"edge"|_edge_view', l)]) == 3      # def, import, build_view key


# ---------------------------------------------------------------- 6. archive keeps the edge, old trades without it still read
def test_archive_keeps_edge_and_old_trades_still_read():
    base, st = tempfile.mkdtemp(), {}
    S, Z = mk(I0 + 12)
    t = dict(trade(S), id="E1", t=5, sym="AAAUSDT", src="MAIN", exit="x", mode="explore")
    BE.observe(t, S, Z, I0, lv_of(S, I0, 1), 10.0, 1.0)
    old = {"id": "OLD", "t": 4, "s": "BTC", "f": "5m", "d": 1, "src": "MAIN", "status": "closed", "net": 2.0, "exit": "x", "mode": "explore"}
    data = {"trades": [t, old], "rows": {}, "rt": {}}
    assert TA.save_dual(data, st, base)
    con = sqlite3.connect(os.path.join(base, TA.DUAL_DB))
    q = lambda i: json.loads(con.execute("SELECT js FROM trades WHERE id=?", (i,)).fetchone()[0])
    assert q("E1")["edge"]["st"] == "STRONG" and "edge" not in q("OLD")
    t["status"], t["net"] = "closed", 12.0                                  # the trade closes -> the conflict (update) path
    BE.close(t)
    assert TA.save_dual(data, st, base)
    e = q("E1")["edge"]
    assert e["done"] == 1 and e["hs"] == "S" and e["hr"] and q("E1")["status"] == "closed"
    con.close()


# ---------------------------------------------------------------- 7. report + scorecard
def _closed(net, hs):
    return {"status": "closed", "net": net, "edge": {"hs": hs}}


def test_report_counts_and_view_shape():
    S, Z = mk(I0 + 12)
    a = dict(trade(S), t=3); BE.observe(a, S, Z, I0, lv_of(S, I0, 1), 10.0, 1.0)
    S2, Z2 = mk(I0 + 12, wdn={I0 + 11: 1})
    b = dict(trade(S2), t=2, s="BBB"); BE.observe(b, S2, Z2, I0, lv_of(S2, I0, 1), 10.0, 1.0)
    skipped = dict(trade(S), status="skipped", take=False, edge={"st": "STRONG"})
    r = BE.report([a, b, skipped, {"status": "open", "d": 1}, _closed(1.0, "TS")])
    assert r["open"] == 2 and r["counts"]["STRONG"] == 1 and r["counts"]["WEAKENING"] == 1 and r["provisional"] is True
    assert [x["s"] for x in r["items"]] == ["AAAUSDT", "BBB"] and len(r["items"][0]["lines"]) == 3 and r["score"]["status"] == "collecting"
    json.dumps(r)
    import smart_brain as SB
    v = SB.build_view(rows=[], trades=[a, b])
    assert v["edge"]["open"] == 2 and v["edge"]["counts"]["STRONG"] == 1
    assert SB._edge_view(None)["status"] == "error"                      # a bad input gives an error card, never a crash


def test_scorecard_counts_on_fake_closed_trades():
    rnd = random.Random(3)
    trades = [_closed(-10.0 + rnd.uniform(-1, 1), "STW") for _ in range(12)] + [_closed(8.0 + rnd.uniform(-1, 1), "SST") for _ in range(20)] \
        + [_closed(-20.0, "TR")] * 2 + [_closed(5.0, "S")] + [{"status": "closed", "net": 3.0}] + [{"status": "open", "edge": {"hs": "WW"}, "net": None}]
    sc = BE.scorecard(trades)
    g = {x["key"]: x for x in sc["groups"]}
    assert sc["status"] == "ready" and sc["n"] == 34
    assert g["weak_or_reversed"]["n"] == 14 and g["never_weak"]["n"] == 20 and g["reversed"]["n"] == 2 and g["strong_seen"]["n"] == 32
    assert g["weak_or_reversed"]["avg_net"] < -9 and 7 < g["never_weak"]["avg_net"] < 9 and g["never_weak"]["win_pct"] == 100
    assert "provisional" in sc["text"] and BE.scorecard(trades[:5])["status"] == "collecting"


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")
