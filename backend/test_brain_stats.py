"""Tests for Batch 4b-2a (brain_stats.py): what happened after each Brain state, against a baseline, walk-forward, with small-sample rules.
Run: cd backend && python3 test_brain_stats.py
"""
import os, random, re, sqlite3, sys, tempfile
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import brain_stats as BS
import trade_archive as TA

MS = 300000                      # 5m
T0 = 1_700_000_000_000


def calls_of(tid, t0, series, fin, tf="5m", d=1, flags="full"):
    """series = [(n, state, roi)] -> call dicts exactly like brain_stats.load() makes them."""
    ms = 300000 if tf == "5m" else 900000
    exit_n = series[-1][0] + 1
    out = []
    for q, (n, st, roi) in enumerate(series):
        later = [r for _n, _s, r in series[q + 1:]] + [fin]
        out.append({"id": tid, "t": t0 + n * ms, "n": n, "st": st, "roi": float(roi), "fin": float(fin), "mx": max(later), "mn": min(later),
                    "left": fin - roi, "d": d, "tf": tf, "sym": "X", "xc": t0 + exit_n * ms + ms})
    return out


def market(n_trades, seed, rule):
    """Trades one hour apart, each lives 6 candles (40 min), so every older trade has finished before a newer trade starts.
    rule(i, rnd, roi3) -> (state at candle 3, final result)."""
    rnd = random.Random(seed)
    calls = []
    for i in range(n_trades):
        r3 = rnd.uniform(-6, 14)
        st, fin = rule(i, rnd, r3)
        series = [(n, st if n == 3 else "T", r3 + (n - 3) * 1.0 + rnd.gauss(0, 0.5)) for n in range(1, 6)]
        calls += calls_of("T%04d" % i, T0 + i * 3600000, series, fin)
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


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")
