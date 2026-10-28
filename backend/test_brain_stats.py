"""Tests for Batch 4b-2a (brain_stats.py): what happened after each Brain state, against a baseline, walk-forward, with small-sample rules.
Run: cd backend && python3 test_brain_stats.py
"""
import hashlib, json, os, random, re, sqlite3, sys, tempfile, time
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "recovered_bot"))
sys.path.insert(0, HERE)
import brain_stats as BS
import trade_archive as TA

MS = 300000                      # 5m
T0 = 1_700_000_000_000


def calls_of(tid, t0, series, fin, tf="5m", d=1, flags="full", reg=None):
    """series = [(n, state, roi)] -> call dicts exactly like brain_stats.load() makes them."""
    ms = 300000 if tf == "5m" else 900000
    exit_n = series[-1][0] + 1
    out = []
    for q, (n, st, roi) in enumerate(series):
        later = [r for _n, _s, r in series[q + 1:]] + [fin]
        out.append({"id": tid, "t": t0 + n * ms, "n": n, "st": st, "roi": float(roi), "fin": float(fin), "mx": max(later), "mn": min(later),
                    "left": fin - roi, "d": d, "tf": tf, "sym": "X", "xc": t0 + exit_n * ms + ms, "sm": None, "reg": reg})
    return out


def market(n_trades, seed, rule, mix=False):
    """Trades one hour apart, each lives 6 candles (40 min), so every older trade has finished before a newer trade starts.
    rule(i, rnd, roi3) -> (state at candle 3, final result)."""
    rnd = random.Random(seed)
    rr = random.Random(seed + 1000)                           # side / timeframe / regime come from their own random stream (the others stay as they were)
    calls = []
    for i in range(n_trades):
        d, tf, reg = (1 if i % 2 == 0 else -1, "5m" if (i // 2) % 2 == 0 else "15m", rr.randrange(3)) if mix else (1, "5m", None)
        r3 = rnd.uniform(-6, 14)
        st, fin = rule(i, rnd, r3)
        series = [(n, st if n == 3 else "T", r3 + (n - 3) * 1.0 + rnd.gauss(0, 0.5)) for n in range(1, 6)]
        calls += calls_of("T%04d" % i, T0 + i * 3600000, series, fin, tf=tf, d=d, reg=reg)
    return calls


def planted(i, rnd, r3):                                   # WEAKENING always means: leaving then was 10 points better than holding
    w = rnd.random() < 0.55
    return ("W", r3 - 10 + rnd.gauss(0, 2)) if w else (rnd.choice("ST"), r3 + rnd.gauss(0, 2))


def noeffect(i, rnd, r3):                                  # the state tells nothing: the result is the same whatever the state
    return rnd.choice("STWR"), r3 + rnd.gauss(0, 3)


# ---------------------------------------------------------------- 1. counting
def test_the_first_call_of_a_state_counts_once_per_trade():
    base = market(60, 1, noeffect)
    long_w = calls_of("LONG", T0 + 999 * 3600000, [(n, "W", 4.0) for n in range(1, 7)], 1.0)   # six W calls in one trade
    r = BS.compute(base + long_w)["states"]["W"]
    plain = BS.compute(base)["states"]["W"]
    assert r["n"] + r["unjudged"] == plain["n"] + plain["unjudged"] + 1, (r, plain)


def test_trades_are_counted_not_candles_in_the_sample_size():
    c = calls_of("A", T0, [(n, "W", 3.0) for n in range(1, 40)], 0.0)
    r = BS.compute(c)["states"]["W"]
    assert r["n"] + r["unjudged"] == 1


# ---------------------------------------------------------------- 2. small samples
def test_few_trades_say_not_enough_data_and_never_lean():
    r = BS.compute(market(25, 2, planted))
    for s in BS.STATES:
        v = r["states"][s]
        assert v["verdict"] == "NOT ENOUGH DATA" and v["lean"] is None and v["p"] is None, v
        assert "NOT ENOUGH DATA" in v["text"]


def test_nothing_at_all_is_not_enough_data_and_not_a_crash():
    r = BS.compute([])
    assert r["trades"] == 0 and all(v["verdict"] == "NOT ENOUGH DATA" and v["n"] == 0 for v in r["states"].values())


def test_small_groups_are_pulled_toward_zero():
    r = BS.compute(market(100, 3, planted))["states"]["W"]
    assert r["n"] >= 30 and abs(r["shrunk"]) < abs(r["excess"]) and (r["shrunk"] < 0) == (r["excess"] < 0), r


# ---------------------------------------------------------------- 3. a real effect and no effect
def test_a_planted_effect_is_found_with_the_right_direction():
    r = BS.compute(market(400, 4, planted))["states"]["W"]
    assert r["verdict"] == "SUPPORTED" and r["lean"] == "exit_now" and r["excess"] < -3 and r["n"] >= BS.FULL_N, r
    assert r["halves"][0] < 0 and r["halves"][1] < 0
    assert r["avail"] >= 0 and r["back"] >= 0


def test_no_effect_is_almost_never_called_supported():
    sup = 0
    for seed in range(10, 18):
        for v in BS.compute(market(500, seed, noeffect))["states"].values():
            sup += v["verdict"] == "SUPPORTED"
    assert sup <= 2, sup                                       # luck alone should give about 2% of states; fixed seeds make this deterministic


def test_a_result_explained_by_the_stage_of_the_trade_is_not_credited_to_the_state():
    def rule(i, rnd, r3):                                      # every trade with high ROI gives 8 points back, whatever the state was
        return rnd.choice("SW"), r3 - (8 if r3 > 5 else 0) + rnd.gauss(0, 1)
    rs = BS.compute(market(500, 5, rule))["states"]
    for s in ("S", "W"):
        assert abs(rs[s]["excess"]) < 2.0 and rs[s]["verdict"] != "SUPPORTED", rs[s]
        assert rs[s]["left"] < -1.0                           # the raw number alone WOULD have looked like a big effect


def test_older_and_newer_half_must_agree():
    def rule(i, rnd, r3):                                      # first part of the history: W is bad, later: W is good; other trades are normal
        if rnd.random() < 0.5:
            return "S", r3 + rnd.gauss(0, 2)
        return ("W", r3 - 15 + rnd.gauss(0, 2)) if i < 200 else ("W", r3 + 5 + rnd.gauss(0, 2))
    r = BS.compute(market(400, 6, rule))["states"]["W"]
    assert r["halves"][0] * r["halves"][1] < 0 and r["verdict"] == "NO CLEAR PATTERN" and r["lean"] is None, r


# ---------------------------------------------------------------- 4. walk-forward (no look-ahead)
def test_a_later_result_never_changes_the_baseline_of_an_older_call():
    calls = market(120, 7, noeffect)
    early = [c for c in calls if c["id"] in ("T0050", "T0051")]
    book_all = BS._Base(BS._first_per(calls, lambda c: BS._cell(c["n"], c["roi"])))
    poisoned = [dict(c, left=c["left"] + 1e6) if c["id"] >= "T0060" else c for c in calls]      # every trade after T0059 gets a crazy result
    book_bad = BS._Base(BS._first_per(poisoned, lambda c: BS._cell(c["n"], c["roi"])))
    for c in early:
        assert book_all.at(c) == book_bad.at(c), c["id"]


def test_the_judgement_of_older_calls_does_not_change_when_newer_trades_arrive_or_go_wild():
    calls = market(300, 8, planted)
    cut = "T0200"
    wild = [dict(c, left=c["left"] + 1e6, fin=c["fin"] + 1e6) if c["id"] >= cut else c for c in calls]      # the future gets absurd results
    for s in ("W", "S", "T"):
        a = {c["id"]: round(e, 9) for c, e, _b in BS.judged(calls, s)[0] if c["id"] < cut}
        b = {c["id"]: round(e, 9) for c, e, _b in BS.judged(wild, s)[0] if c["id"] < cut}
        c_only = {c["id"]: round(e, 9) for c, e, _b in BS.judged([c for c in calls if c["id"] < cut], s)[0]}
        assert a and a == b == c_only, s                       # identical with the real future, a crazy future, and no future at all


def test_a_trade_counts_as_earlier_only_when_its_exit_candle_had_closed():
    keep = BS.MIN_CELL
    BS.MIN_CELL = 1
    try:
        a = calls_of("A", T0, [(1, "T", 2.0), (2, "T", 3.0)], 1.0)                  # exit candle opens T0+3*MS, closes at A["xc"]
        xc = a[0]["xc"]
        book = BS._Base(BS._first_per(a, lambda c: BS._cell(c["n"], c["roi"])))
        probe = dict(a[0], id="B", n=1, roi=2.0)
        assert book.at(dict(probe, t=xc - 1)) is None                               # one ms before it closed: not known yet
        assert book.at(dict(probe, t=xc)) is not None                               # call candle opens when it had closed: known
    finally:
        BS.MIN_CELL = keep


# ---------------------------------------------------------------- 5. archive reading
def _journey_row(tid, t0, flags="full"):
    d = dict.fromkeys(TA.JCOLS)
    d.update(id=tid, v="j1", t=t0 + MS - 1, sym="X", tf="5m", d=1, flags=flags, net=1.0, exit_n=4, saved=1.0)
    return tuple(d[c] for c in TA.JCOLS)


def _out_row(c, exit_n):
    return (c["id"], c["t"], "j1", c["n"], c["st"], c["roi"], c["fin"], c["mx"], c["mn"], exit_n - c["n"], None)


def _archive(base, specs):
    js, outs = [], []
    for tid, t0, series, fin, flags in specs:
        js.append(_journey_row(tid, t0, flags))
        outs += [_out_row(c, series[-1][0] + 1) for c in calls_of(tid, t0, series, fin)]
    assert TA.save_learn(js, outs, base)


def test_load_gives_the_same_calls_as_the_hand_made_ones_and_drops_flagged_journeys():
    base = tempfile.mkdtemp()
    s1 = [(1, "T", 1.0), (2, "W", 2.0), (3, "T", 3.0)]
    _archive(base, [("G", T0, s1, 2.0, "full"), ("L", T0 + 5 * MS, s1, 2.0, "late:2"), ("N", T0 + 9 * MS, s1, 2.0, "net_diff"),
                    ("P", T0 + 20 * MS, s1, 2.0, "gaps:1")])
    calls, info = BS.load(base)
    ids = {c["id"] for c in calls}
    assert ids == {"G", "P"} and info["left_out"] == 6 and info["trades"] == 2, (ids, info)
    mine = [c for c in calls_of("G", T0, s1, 2.0)]
    got = [c for c in calls if c["id"] == "G"]
    assert [(c["t"], c["xc"], c["left"], c["mx"], c["mn"]) for c in got] == [(c["t"], c["xc"], c["left"], c["mx"], c["mn"]) for c in mine]


def test_reading_never_writes_and_a_missing_archive_makes_no_file():
    base = tempfile.mkdtemp()
    r = BS.run(base)
    assert r["err"] == "" and r["trades"] == 0 and not os.path.exists(os.path.join(base, "brain_archive.db"))
    _archive(base, [("G", T0, [(1, "T", 1.0), (2, "T", 2.0)], 2.0, "full")])
    before = open(os.path.join(base, "brain_archive.db"), "rb").read()
    BS.run(base)
    con = TA.open_brain_ro(base)
    try:
        try:
            con.execute("INSERT INTO journey(id, v) VALUES ('Z', 'j1')")
            raise AssertionError("the read-only connection accepted a write")
        except sqlite3.OperationalError:
            pass
    finally:
        con.close()
    assert sqlite3.connect(os.path.join(base, "brain_archive.db")).execute("SELECT COUNT(*) FROM journey").fetchone()[0] == 1
    assert len(before) > 0


def test_a_damaged_archive_is_reported_not_raised():
    base = tempfile.mkdtemp()
    open(os.path.join(base, "brain_archive.db"), "wb").write(b"this is not a database" * 50)
    r = BS.run(base)
    assert r["err"] and r["trades"] == 0


def test_runs_while_the_brain_worker_has_a_write_open():
    base = tempfile.mkdtemp()
    _archive(base, [("G", T0, [(1, "T", 1.0), (2, "T", 2.0)], 2.0, "full")])
    w = sqlite3.connect(os.path.join(base, "brain_archive.db"), timeout=1)
    w.execute("BEGIN IMMEDIATE")
    w.execute("INSERT OR IGNORE INTO journey(id, v) VALUES ('W', 'j1')")
    try:
        r = BS.run(base)
        assert r["err"] == "" and r["trades"] == 1, r
    finally:
        w.rollback()
        w.close()


# ---------------------------------------------------------------- 6. nothing here decides
def test_source_guards():
    src = open(os.path.join(HERE, "brain_stats.py")).read()
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    assert not re.search(r"delete\s+from|drop\s+table|update\s+\w+\s+set|insert\s+(or\s+\w+\s+)?into", code, re.I)     # reads only
    for bad in ("requests", "urllib", "anthropic", "websocket", "paper_trader", "strategy", "dual_lab", "market_ws", "telegram", "smart_brain"):
        assert not re.search(r"^\s*(import|from)\s+%s\b" % bad, code, re.M), bad
    for s in ("dual_lab.py", "paper_trader.py", "strategy.py", "market_ws.py"):
        p = os.path.join(HERE, s) if os.path.exists(os.path.join(HERE, s)) else None
        if p:
            assert "brain_stats" not in open(p).read(), s                                 # no trading file knows about this module


def test_texts_are_plain_and_never_advice():
    for r in BS.compute(market(400, 4, planted))["states"].values():
        t = r["text"].lower()
        assert "not advice" in t or "not enough data" in t or "no clear pattern" in t, t


# ================================================================ B4b-2b
def planted_buy(i, rnd, r3):                               # the effect exists only for BUY trades (even i = side +1 in market(mix=True))
    return planted(i, rnd, r3) if i % 2 == 0 else noeffect(i, rnd, r3)


def _all(res):
    return [r for g in res["slices"] for r in g["states"].values()]


# ---------------------------------------------------------------- 7. regime
def test_regime_edges_are_the_same_words_as_tag_lab():
    import tag_lab as TL
    for pct in range(0, 101):
        word = TL._side_word("x", pct).split()[-1]                  # trending / mixed / sideways
        assert BS.REG_NAMES[BS.bisect.bisect_right(BS.REG_EDGES, pct)] == word, (pct, word)


def test_load_reads_the_regime_of_each_call_candle_from_obs_without_writing():
    import test_brain_learn as TL, brain_learn as BL
    base = tempfile.mkdtemp()
    TL._market(base, seed=31)
    BL.step(base, limit=100000)
    before = open(os.path.join(base, "dual_archive.db"), "rb").read()
    calls, info = BS.load(base)
    assert calls and info["no_regime"] == 0, info
    con = sqlite3.connect(os.path.join(base, "dual_archive.db"))
    keys = json.loads(con.execute("SELECT v FROM meta WHERE k LIKE 'obs_keys_%'").fetchone()[0])
    for c in calls[:50]:
        f = json.loads(con.execute("SELECT f FROM obs WHERE id = ? AND t = ? AND k = 'O'", (c["id"], c["t"])).fetchone()[0])
        assert c["sm"] == float(f[keys.index("sm")]) and c["reg"] == (0 if c["sm"] < 34 else 1 if c["sm"] < 67 else 2)
    assert open(os.path.join(base, "dual_archive.db"), "rb").read() == before


# ---------------------------------------------------------------- 8. slices
def test_a_slice_finds_an_effect_only_where_it_exists():
    res = BS.analyze(market(700, 21, planted_buy, mix=True))
    by = {g["slice"]: g["states"] for g in res["slices"]}
    buy, sell = by["side:BUY"]["W"], by["side:SELL"]["W"]
    assert buy["verdict"] in ("EARLY HINT", "SUPPORTED") and buy["lean"] == "exit_now" and buy["excess"] < -3, buy
    assert sell["verdict"] != "SUPPORTED" and sell["lean"] is None, sell
    assert {"all", "side:BUY", "side:SELL", "tf:5m", "tf:15m", "regime:trending", "regime:mixed", "regime:sideways"} <= set(by)
    assert len([g for g in res["slices"] if g["kind"] == "cross"]) == 12


def test_many_slices_make_the_luck_test_stricter():
    assert BS._judge(40, [1.0, 1.2], 1.1, 0.04, 1) == "EARLY HINT"
    assert BS._judge(40, [1.0, 1.2], 1.1, 0.04, 12) == "NO CLEAR PATTERN"            # the same p is not enough when 12 things were checked
    assert BS._judge(29, [1.0, 1.2], 1.1, 0.001, 1) == "NOT ENOUGH DATA"
    assert BS._judge(120, [1.0, -1.2], 0.1, 0.001, 1) == "NO CLEAR PATTERN"          # halves disagree
    res = BS.analyze(market(700, 21, planted_buy, mix=True))
    for r in _all(res):
        if r["p"] is not None:
            assert r["p_adj"] >= r["p"] and r["tests"] >= 1


def test_nothing_is_called_supported_in_a_market_without_any_effect():
    hints = sup = 0
    for seed in range(40, 45):
        for r in _all(BS.analyze(market(600, seed, noeffect, mix=True))):
            sup += r["verdict"] == "SUPPORTED"
            hints += r["verdict"] in ("EARLY HINT", "SUPPORTED")
    assert sup == 0 and hints <= 3, (sup, hints)


def test_slices_without_enough_trades_say_not_enough_data():
    res = BS.analyze(market(60, 3, noeffect, mix=True))
    for g in res["slices"]:
        for r in g["states"].values():
            assert r["n"] >= BS.MIN_N or r["verdict"] == "NOT ENOUGH DATA"


# ---------------------------------------------------------------- 9. mistakes ledger
def test_ledger_counts_the_mistakes_exactly_and_counts_a_trade_once():
    t = lambda k: T0 + k * 3600000
    calls = (calls_of("A", t(0), [(1, "S", 4.0), (2, "T", 5.0)], -5.0, reg=2)             # STRONG but lost            -> S_lost
             + calls_of("B", t(1), [(1, "S", 4.0), (2, "T", 5.0)], 4.0)                    # STRONG and won             -> no mistake
             + calls_of("C", t(2), [(2, "W", 6.0), (3, "T", 7.0)], 9.0)                    # WEAKENING, ended better    -> W_ran
             + calls_of("D", t(3), [(2, "W", 6.0), (3, "T", 7.0)], 2.0)                    # WEAKENING, leaving was right -> no mistake
             + calls_of("E", t(4), [(2, "R", -3.0), (3, "T", 0.0)], 4.0)                   # REVERSED but recovered     -> R_ran
             + calls_of("F", t(5), [(1, "T", 1.0), (2, "T", 2.0)], -1.0)                   # STABLE but lost            -> T_lost
             + calls_of("G", t(6), [(2, "W", 6.0), (3, "W", 6.5), (4, "W", 7.0)], 12.0))   # three W calls: counted once
    led, rows = BS.ledger(calls)
    by = {r["state"]: r for r in led}
    assert (by["S"]["n"], by["S"]["mistakes"]) == (2, 1) and (by["W"]["n"], by["W"]["mistakes"]) == (3, 2)
    assert (by["R"]["n"], by["R"]["mistakes"]) == (1, 1) and by["T"]["mistakes"] >= 1
    assert {(m["id"], m["kind"]) for m in rows} >= {("A", "S_lost"), ("C", "W_ran"), ("E", "R_ran"), ("G", "W_ran"), ("F", "T_lost")}
    assert ("B", "S_lost") not in {(m["id"], m["kind"]) for m in rows} and ("D", "W_ran") not in {(m["id"], m["kind"]) for m in rows}
    assert len([m for m in rows if m["id"] == "G"]) == 1
    a = [m for m in rows if m["id"] == "A"][0]
    assert a["fin"] == -5.0 and a["roi"] == 4.0 and a["reg"] == 2 and a["tf"] == "5m" and a["d"] == 1
    assert all(r["verdict"] == "NOT ENOUGH DATA" for r in led)


def test_ledger_says_more_mistakes_than_usual_only_with_enough_trades_and_agreeing_halves():
    def rule(i, rnd, r3):                                                                 # STRONG calls lose far more often than usual
        return ("S", r3 - 15 + rnd.gauss(0, 2)) if rnd.random() < 0.5 else ("T", r3 + rnd.gauss(0, 2))
    led, _rows = BS.ledger(market(500, 31, rule))
    s = {r["state"]: r for r in led}["S"]
    assert s["verdict"] in ("EARLY HINT", "SUPPORTED") and s["diff"] > 20 and s["rate"] > s["usual"], s
    assert "More than usual" in s["text"] or "More" in s["text"]
    led2, _ = BS.ledger(market(500, 32, noeffect))
    assert all(r["verdict"] != "SUPPORTED" for r in led2)
    led3, _ = BS.ledger(market(40, 33, rule))
    small = {r["state"]: r for r in led3}["S"]                                           # about 20 STRONG calls: far below 30
    assert small["n"] < BS.MIN_N and small["verdict"] == "NOT ENOUGH DATA" and "NOT ENOUGH DATA" in small["text"]


def test_mistake_rows_are_frozen_once_written():
    base = tempfile.mkdtemp()
    row = lambda fin: ("A", "S", "S_lost", "s1", 1, 2, 4.0, fin, 5.0, -6.0, "5m", 1, 2, None, 1.0)
    assert TA.save_mistakes([row(-5.0)], base) and TA.save_mistakes([row(-99.0)], base)
    con = sqlite3.connect(os.path.join(base, "brain_archive.db"))
    assert con.execute("SELECT COUNT(*), MIN(fin) FROM mistake").fetchone() == (1, -5.0)          # the second write changed nothing


def test_stats_snapshots_are_added_only_every_ten_trades_and_never_changed():
    base = tempfile.mkdtemp()
    assert TA.save_stats_snapshot("s1", 20, '{"a":1}', 10, base) is True
    assert TA.save_stats_snapshot("s1", 25, '{"a":2}', 10, base) is False
    assert TA.save_stats_snapshot("s1", 30, '{"a":3}', 10, base) is True
    assert TA.save_stats_snapshot("s2", 5, '{"b":1}', 10, base) is True                             # a new version starts its own history
    rows = sqlite3.connect(os.path.join(base, "brain_archive.db")).execute("SELECT v, trades, js FROM learn_stats ORDER BY v, trades").fetchall()
    assert rows == [("s1", 20, '{"a":1}'), ("s1", 30, '{"a":3}'), ("s2", 5, '{"b":1}')]


# ---------------------------------------------------------------- 10. worker connection
def _real_market(seed=31):
    import test_brain_learn as TL, brain_learn as BL
    base = tempfile.mkdtemp()
    TL._market(base, seed=seed)
    BL.step(base, limit=100000)
    return base


def _fingerprint(base, db, tables):
    con = sqlite3.connect(os.path.join(base, db))
    return {t: hashlib.sha256(repr(con.execute("SELECT * FROM %s ORDER BY 1, 2" % t).fetchall()).encode()).hexdigest() for t in tables}


def test_refresh_saves_mistakes_once_and_never_changes_raw_data_or_old_results():
    base = _real_market()
    raw = _fingerprint(base, "dual_archive.db", ["obs", "trades"])
    old = _fingerprint(base, "brain_archive.db", ["journey", "call_out"])
    res = BS.refresh(base, force=True)
    assert res is not None and res["trades"] > 5
    con = sqlite3.connect(os.path.join(base, "brain_archive.db"))
    n1 = con.execute("SELECT COUNT(*) FROM mistake").fetchone()[0]
    assert n1 == len(res["mistakes"]) > 0
    first = con.execute("SELECT * FROM mistake ORDER BY id, st, kind").fetchall()
    snaps = con.execute("SELECT COUNT(*) FROM learn_stats").fetchone()[0]
    assert snaps == 1
    BS.refresh(base, force=True)
    BS.refresh(base, force=True)
    assert con.execute("SELECT * FROM mistake ORDER BY id, st, kind").fetchall() == first         # same rows, untouched (saved time included)
    assert con.execute("SELECT COUNT(*) FROM learn_stats").fetchone()[0] == snaps                 # no new trades: no new copy
    assert _fingerprint(base, "dual_archive.db", ["obs", "trades"]) == raw
    assert _fingerprint(base, "brain_archive.db", ["journey", "call_out"]) == old


def test_refresh_is_throttled_and_only_recomputes_when_the_journeys_changed():
    base = _real_market()
    calls = {"n": 0}
    real = BS.load
    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    BS.load = counting
    try:
        BS.refresh(base, force=True)
        assert calls["n"] == 1
        BS.refresh(base)
        assert calls["n"] == 1                                       # inside REFRESH_S: no work at all
        BS._C["t"] -= BS.REFRESH_S + 1
        BS.refresh(base)
        assert calls["n"] == 1                                       # time passed but the journeys are the same: no recompute
        BS._C["t"] -= BS.REFRESH_S + 1
        BS._C["key"] = (0, 0)                                        # as if new journeys had arrived
        BS.refresh(base)
        assert calls["n"] == 2
    finally:
        BS.load = real


def test_the_cache_never_mixes_two_archives():
    a, b = _real_market(31), tempfile.mkdtemp()
    sa = BS.summary(a)
    sb = BS.summary(b)
    assert sa["trades"] > 5 and sb["status"] == "collecting" and sb.get("trades", 0) == 0 and sb["err"] == ""


def test_the_view_block_is_small_plain_and_json_safe():
    base = _real_market()
    v = BS.summary(base)
    raw = json.dumps(v)
    assert len(raw) < 20000, len(raw)
    assert v["status"] in ("collecting", "measuring") and v["min_n"] == 30 and v["provisional"] is True
    assert [r["state"] for r in v["overall"]] == list("STWR") and len(v["ledger"]) == 4
    assert all(r["n"] >= 30 for r in v["slices"])
    for r in v["overall"] + v["slices"]:
        assert r["verdict"] in ("NOT ENOUGH DATA", "NO CLEAR PATTERN", "EARLY HINT", "SUPPORTED")


def test_the_brain_view_gets_the_stats_and_a_failure_never_breaks_it():
    import brain_learn as BL
    base = _real_market()
    v = BL.view_summary(base)
    assert v["stats"]["overall"] and v["status"] in ("collecting", "measuring") and v["journeys"] > 5
    empty = BL.view_summary(tempfile.mkdtemp())
    assert empty["status"] == "collecting" and "NOT ENOUGH DATA" in empty["text"] and empty["stats"]["status"] == "collecting"
    real = BS.summary
    BS.summary = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        v2 = BL.view_summary(base)
        assert v2["status"] == "collecting" and v2["stats"]["status"] == "error" and v2["journeys"] > 5
    finally:
        BS.summary = real


def test_without_regime_data_the_other_slices_still_work():
    real = BS._regimes
    BS._regimes = lambda *a, **k: {}
    try:
        base = _real_market()
        v = BS.summary(base)
        assert v["no_regime"] > 0 and v["overall"] and v["err"] == ""
        res = BS.refresh(base, force=True)
        names = {g["slice"] for g in res["slices"]}
        assert "all" in names and not any(n.startswith("regime:") for n in names)
    finally:
        BS._regimes = real


def test_a_damaged_archive_gives_a_collecting_summary_with_the_problem_named():
    base = tempfile.mkdtemp()
    open(os.path.join(base, "brain_archive.db"), "wb").write(b"not a database" * 40)
    v = BS.summary(base)
    assert v["status"] == "collecting" and v["err"]


def test_the_brain_still_decides_nothing():
    for f in ("brain_stats.py", "brain_learn.py"):
        code = re.sub(r'""".*?"""', "", open(os.path.join(HERE, f)).read(), flags=re.S)
        for bad in ("paper_trader", "strategy", "dual_lab", "market_ws", "telegram", "requests", "anthropic"):
            assert not re.search(r"^\s*(import|from)\s+%s\b" % bad, code, re.M), (f, bad)
    sb = open(os.path.join(HERE, "smart_brain.py")).read()
    assert set(re.findall(r"\bBLN\.(\w+)", sb)) == {"step", "view_summary"} and "brain_stats" not in sb      # the worker still only calls the same two functions


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")
