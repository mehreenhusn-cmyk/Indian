"""Tests for Batch 4c-1 (brain_look.py): look-alike learning, past-only scaling, walk-forward, block luck test, NOT ENOUGH DATA.
Run: cd backend && python3 test_brain_look.py
"""
import json, os, random, re, sys, tempfile, time
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "recovered_bot"))
sys.path.insert(0, HERE)
import brain_look as BL
import brain_stats as BS
import brain_edge as BE
import test_brain_stats as TS

HOUR = 3600000


def trade(tid, t0, x, st, left, rnd, d=1, tf="5m", r3=None):
    r3 = rnd.uniform(-6, 14) if r3 is None else r3
    series = [(k, st if k == 3 else "T", r3 + (k - 3) * 1.0 + rnd.gauss(0, 0.5)) for k in range(1, 6)]
    cs = TS.calls_of(tid, t0, series, r3 + left, tf=tf, d=d)
    for c in cs:
        c["x"] = x
    return cs


def market(n, seed, rule, spacing=HOUR, mix=False, nulls=0.3, t_start=TS.T0, first=0):
    """Trades `spacing` apart. rule(x, st, rnd) -> what holding added after the call (`left`). Numbers are random and have nothing to do with the state."""
    rnd = random.Random(seed)
    rr = random.Random(seed + 500)
    out = []
    for i in range(first, first + n):
        x = [rnd.uniform(-2, 2) for _ in range(len(BL.FEATS))]
        if rnd.random() < nulls:
            x[3] = None                                           # zg is often missing on old candles
        st = rnd.choice("ST")
        d, tf = (rr.choice((1, -1)), rr.choice(("5m", "15m"))) if mix else (1, "5m")
        out += trade("T%04d" % i, t_start + i * spacing, x, st, rule(x, st, rnd), rnd, d, tf)
    return out


def planted(x, st, rnd):                       # STRONG calls: holding adds +6 when the first number is positive, -6 when not
    return ((6 if x[0] > 0 else -6) + rnd.gauss(0, 2)) if st == "S" else rnd.gauss(0, 3)


def noeffect(x, st, rnd):
    return rnd.gauss(0, 3)


def S(res, name="all", st="S"):
    g = next(g for g in res["slices"] if g["slice"] == name)
    return g["states"][st]


# ---------------------------------------------------------------- 1. the fixed set
def test_the_feature_set_is_exactly_the_audited_eight_and_exists_in_the_b4a_rows():
    assert BL.FEATS == ("tsi", "hist", "z", "zg", "sm", "bw", "ed", "sc") and BL.LOOK_VERSION == "l1"
    assert all(k in BE.OBS_KEYS for k in BL.FEATS)
    assert BL.analyze([])["config"]["feats"] == list(BL.FEATS)


# ---------------------------------------------------------------- 2. finds an effect, does not invent one
def test_a_planted_effect_is_found_with_the_right_direction():
    r = S(BL.analyze(market(500, 5, planted)))
    assert r["verdict"] in BL.HINTS and r["score"] > 3 and r["hit"] > 70 and r["n"] >= 60, r


def test_the_same_effect_is_not_judged_when_everything_happened_in_a_few_hours():
    r = S(BL.analyze(market(900, 5, planted, spacing=10000)))
    assert r["p"] is None and r["verdict"] == "NO CLEAR PATTERN" and "bunched" in r["text"], r


def test_no_effect_is_never_supported_and_early_hints_by_luck_stay_rare_and_p_is_fair():
    """EARLY HINT is the weak label by design (p_adj <= 0.20, agreeing halves), so luck can give a few; SUPPORTED (100 calls, p_adj <= 0.05) must
    never appear in a market without an effect, and the luck-test p must be spread fairly (not piled up near 0)."""
    sup = hint_all = tot_all = hint_sl = tot_sl = 0
    ps = []
    for seed in range(100, 140):
        res = BL.analyze(market(450, seed, noeffect, mix=True))
        for g in res["slices"]:
            for r in g["states"].values():
                if r["n"] < BS.MIN_N:
                    continue
                sup += r["verdict"] == "SUPPORTED"
                if g["slice"] == "all":
                    tot_all += 1
                    hint_all += r["verdict"] == "EARLY HINT"
                    ps += [r["p"]] if r["p"] is not None else []
                else:
                    tot_sl += 1
                    hint_sl += r["verdict"] == "EARLY HINT"
    ps.sort()
    assert sup == 0 and tot_all > 30 and tot_sl > 100, (sup, tot_all, tot_sl)
    assert hint_all <= 0.15 * tot_all and hint_sl <= 0.05 * tot_sl, (hint_all, tot_all, hint_sl, tot_sl)
    assert ps[len(ps) // 10] > 0.04 and 0.35 < ps[len(ps) // 2] < 0.75, (ps[len(ps) // 10], ps[len(ps) // 2])


def test_a_score_below_zero_is_never_a_hint():
    r = {"state": "S", "name": "STRONG", "n": 120, "judged": 150, "halves": [-2.0, -3.0], "p": 0.001, "score": -2.5, "_score": -2.5, "hit": 40}
    BL._finish(r, 1)
    assert r["verdict"] == "NO CLEAR PATTERN"


# ---------------------------------------------------------------- 3. small samples
def test_few_trades_say_not_enough_data_and_nothing_at_all_does_not_crash():
    for r in BL.analyze(market(40, 2, planted))["slices"][0]["states"].values():
        assert r["verdict"] == "NOT ENOUGH DATA" and r["p"] is None and "NOT ENOUGH DATA" in r["text"], r
    res = BL.analyze([])
    assert res["trades"] == 0 and all(r["verdict"] == "NOT ENOUGH DATA" for r in res["slices"][0]["states"].values())


def test_a_call_needs_enough_earlier_trades_and_look_alikes_else_it_is_not_scored():
    res = BL.analyze(market(500, 5, planted))
    cv = res["coverage"]["S"]
    assert cv["judged"] > cv["scored"] > 0 and cv["nolook"] == cv["judged"] - cv["scored"] - cv["nofeat"], cv
    assert all(t["m"] >= BL.MIN_LOOK for t in res["targets"])


# ---------------------------------------------------------------- 4. one trade = one piece of evidence
def test_a_long_trade_with_many_calls_of_one_state_is_one_target_at_most():
    base = market(300, 3, noeffect)
    x = [0.1] * 8
    long = TS.calls_of("LONG", TS.T0 + 900 * HOUR, [(n, "S", 4.0) for n in range(1, 8)], 1.0)
    for c in long:
        c["x"] = x
    a, b = BL.analyze(base), BL.analyze(base + long)
    assert b["coverage"]["S"]["judged"] <= a["coverage"]["S"]["judged"] + 1
    ids = [t["id"] for t in b["targets"] if t["st"] == "S"]
    assert len(ids) == len(set(ids)) and ids.count("LONG") <= 1


def test_a_pool_never_holds_the_same_trade_twice():
    base = market(200, 3, noeffect)
    rows, _n = BS.judged(base, "S")
    ids = [c["id"] for c, _e, _b in rows]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------- 5. look-ahead
def test_future_trades_with_absurd_results_and_numbers_never_change_older_guesses():
    base = market(400, 7, planted)
    start = TS.T0 + 400 * HOUR
    fut = market(120, 8, lambda x, st, rnd: -900.0 if st == "S" else 900.0, first=400, nulls=0.0)
    for c in fut:
        c["x"] = [1e6 * (i + 1) for i in range(8)]                   # absurd numbers too: the scaling must not see them
    a = {(t["id"], t["st"]): (t["pred"], t["actual"], t["m"]) for t in BL.analyze(base)["targets"]}
    b = {(t["id"], t["st"]): (t["pred"], t["actual"], t["m"]) for t in BL.analyze(base + fut)["targets"] if t["t"] < start}
    assert a and a == b, (len(a), len(b))


def test_a_trade_still_open_at_the_call_is_not_a_look_alike_even_if_it_started_earlier():
    base = market(400, 9, planted)
    tg = next(t for t in BL.analyze(base)["targets"] if t["st"] == "S" and t["id"] > "T0300")
    x = next(c["x"] for c in base if c["id"] == tg["id"])
    ms = 300000
    series = [(1, "T", 5.0), (2, "T", 5.0), (3, "S", 5.0), (4, "T", 5.0), (5, "T", 5.0)]
    over = TS.calls_of("OVER", tg["t"] - 4 * ms, series, 5.0 + 1000.0)       # first S call one candle before the target, exit candle after it
    for c in over:
        c["x"] = x
    assert min(c["t"] for c in over if c["st"] == "S") < tg["t"] < over[0]["xc"]
    pick = lambda res: next(t["pred"] for t in res["targets"] if t["id"] == tg["id"] and t["st"] == "S")
    assert pick(BL.analyze(base)) == pick(BL.analyze(base + over))


def test_the_spread_used_for_the_distance_comes_from_the_pool_window_only():
    win = [(i, {"x": [float(i % 5)] + [None] * 7}, 0.0) for i in range(30)]
    sd = BL._spread(win)
    assert sd[0] is not None and abs(sd[0] - 1.414) < 0.01 and sd[1:] == [None] * 7
    win2 = win + [(99, {"x": [1e9] + [None] * 7}, 0.0)]
    assert BL._spread(win2)[0] > 1e6                                           # the function only knows what it is given: callers hand it the past


def test_the_pool_window_is_cut_at_the_call_candle_in_the_source():
    src = open(os.path.join(HERE, "brain_look.py")).read()
    assert "bisect.bisect_right(xcs[k], c[\"t\"])" in src and "groups[k][max(0, j - POOL_MAX):j]" in src


# ---------------------------------------------------------------- 6. missing numbers
def test_calls_without_numbers_are_counted_and_calls_with_too_few_common_numbers_are_not_look_alikes():
    m = market(300, 4, planted, nulls=0.0)
    for c in m:
        c["x"] = None
    res = BL.analyze(m)
    cv = res["coverage"]["S"]
    assert cv["scored"] == 0 and cv["nofeat"] == cv["judged"] > 0
    m = market(300, 4, planted, nulls=0.0)
    for c in m:
        c["x"] = c["x"][:5] + [None] * 3                                       # 5 numbers < MIN_COMMON
    assert BL.analyze(m)["coverage"]["S"]["scored"] == 0


def test_a_number_that_never_changes_is_skipped_not_divided_by_zero():
    m = market(300, 4, planted)
    for c in m:
        c["x"] = c["x"][:7] + [3.0]
    assert S(BL.analyze(m))["verdict"] in BL.HINTS + ("NO CLEAR PATTERN", "NOT ENOUGH DATA")


# ---------------------------------------------------------------- 7. luck test with market-move protection
def test_the_luck_test_pairs_a_guess_only_with_a_result_from_another_market_move():
    n = 120
    ts = [i * HOUR for i in range(n)]
    rnd = random.Random(3)
    sg = [rnd.choice((1, -1)) for _ in range(n)]
    good = [s * 5 + rnd.gauss(0, 1) for s in sg]
    assert BL._shift_p(sg, good, ts) < 0.05
    assert BL._shift_p(sg, [rnd.gauss(0, 5) for _ in range(n)], ts) > 0.2
    assert BL._shift_p(sg[:30], good[:30], [i * 60000 for i in range(30)]) is None        # all in one block: no safe shift
    assert BL._shift_p(sg[:20], good[:20], ts[:20]) is None                               # under MIN_N


def test_trends_that_run_through_time_do_not_fool_the_luck_test():
    n = 150
    ts = [i * HOUR for i in range(n)]
    rnd = random.Random(5)
    sg = [1 if (i // 25) % 2 == 0 else -1 for i in range(n)]                 # guess flips in long runs
    ac = [(1 if (i // 25) % 2 == 0 else -1) * 0.5 + rnd.gauss(0, 4) for i in range(n)]
    p = BL._shift_p(sg, ac, ts)
    assert p is None or p > 0.05 or abs(sum(s * a for s, a in zip(sg, ac)) / n) > 0.3


# ---------------------------------------------------------------- 8. results are repeatable and slices are the 2b slices
def test_same_input_gives_the_same_output_and_slices_follow_brain_stats():
    m = market(300, 6, planted, mix=True)
    a, b = BL.analyze(m), BL.analyze(m)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    assert [g["slice"] for g in a["slices"]] == [g[0] for g in BS._groups(m) if g[0] == "all" or any(g[2](t) for t in a["targets"])]


def test_many_slices_make_the_luck_test_stricter():
    res = BL.analyze(market(600, 5, planted, mix=True))
    assert res["tests"] >= 1
    for g in res["slices"]:
        for r in g["states"].values():
            if r["p"] is not None:
                assert r["p_adj"] >= r["p"] and r["tests"] >= 1


def test_texts_are_plain_and_never_advice():
    res = BL.analyze(market(500, 5, planted, mix=True))
    for g in res["slices"]:
        for r in g["states"].values():
            t = r["text"].lower()
            assert "not advice" in t or "not enough data" in t or "no clear pattern" in t or "bunched" in t, t
            assert not re.search(r"\b(should|recommend|buy now|sell now|close it|exit now)\b", t), t


def test_one_thousand_two_hundred_trades_stay_fast_enough_for_the_worker():
    m = market(1200, 5, planted, mix=True)
    t = time.time()
    BL.analyze(m)
    assert time.time() - t < 20, time.time() - t


# ---------------------------------------------------------------- 9. archive: read-only, immutable, failures are reported
def test_load_reads_the_eight_numbers_from_obs_without_writing_and_results_leave_everything_unchanged():
    base = TS._real_market()
    raw = TS._fingerprint(base, "dual_archive.db", ["obs", "trades"])
    old = TS._fingerprint(base, "brain_archive.db", ["journey", "call_out"])
    calls, info = BL.load(base)
    import sqlite3
    con = sqlite3.connect(os.path.join(base, "dual_archive.db"))
    keys = json.loads(con.execute("SELECT v FROM meta WHERE k LIKE 'obs_keys_%'").fetchone()[0])
    got = 0
    for c in calls[:60]:
        f = json.loads(con.execute("SELECT f FROM obs WHERE id = ? AND t = ? AND k = 'O'", (c["id"], c["t"])).fetchone()[0])
        want = [None if f[keys.index(k)] is None else float(f[keys.index(k)]) for k in BL.FEATS]
        assert c["x"] == want, (c["x"], want)
        got += 1
    assert got and info["no_feats"] == 0, info
    out = BL.run(base)
    assert out["err"] == "" and set(out["states"]) == set(BS.STATES)
    assert all(r["verdict"] in ("NOT ENOUGH DATA", "NO CLEAR PATTERN") + BL.HINTS for r in out["states"].values())
    assert TS._fingerprint(base, "dual_archive.db", ["obs", "trades"]) == raw
    assert TS._fingerprint(base, "brain_archive.db", ["journey", "call_out"]) == old


def test_features_reader_gives_none_for_a_missing_key_and_nothing_for_a_missing_archive():
    base = TS._real_market()
    calls, _i = BS.load(base)
    f = BS.features(base, {c["id"] for c in calls}, ("sm", "no_such_key"))
    assert f and all(v[1] is None for v in f.values())
    empty = tempfile.mkdtemp()
    assert BS.features(empty, ["x"], ("sm",)) == {} and os.listdir(empty) == []


def test_a_missing_archive_makes_no_file_and_a_damaged_one_is_reported_not_raised():
    empty = tempfile.mkdtemp()
    r = BL.run(empty)
    assert r["trades"] == 0 and r["err"] == "" and os.listdir(empty) == []
    bad = tempfile.mkdtemp()
    open(os.path.join(bad, "brain_archive.db"), "wb").write(b"not a database" * 200)
    r = BL.run(bad)
    assert isinstance(r, dict) and r["trades"] == 0


# ---------------------------------------------------------------- 10. the Brain still decides nothing
def test_source_guards_and_nothing_else_knows_this_module():
    code = re.sub(r'""".*?"""', "", open(os.path.join(HERE, "brain_look.py")).read(), flags=re.S)
    assert not re.search(r"delete\s+from|drop\s+table|update\s+\w+\s+set|insert\s+(or\s+\w+\s+)?into|create\s+table", code, re.I)
    for bad in ("requests", "urllib", "anthropic", "websocket", "paper_trader", "strategy", "dual_lab", "market_ws", "telegram", "smart_brain", "random"):
        assert not re.search(r"^\s*(import|from)\s+%s\b" % bad, code, re.M), bad
    for f in os.listdir(HERE):
        if f.endswith(".py") and f not in ("brain_look.py", "test_brain_look.py", "brain_pattern.py", "test_brain_pattern.py", "test_brain_pattern2.py"):      # brain_pattern (B4c-2 part 1) is the one allowed user
            assert not re.search(r"^\s*(import|from)\s+brain_look\b|\bBLK\.|brain_look\.", open(os.path.join(HERE, f)).read(), re.M), f      # B4c-1 is not connected to anything (B4c-2 does that)


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")
