"""Tests for Batch 4c-2 part 2: frozen look_call storage, mistake-vs-correct number gaps, view key learn.look (brain_pattern.py, trade_archive.py, brain_learn.py).
Run: cd backend && python3 test_brain_pattern2.py
"""
import hashlib, json, os, re, sqlite3, statistics, sys, tempfile, time
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "recovered_bot"))
sys.path.insert(0, HERE)
import brain_learn as BLN
import brain_look as BL
import brain_pattern as BP
import brain_stats as BS
import test_brain_edge as TE
import test_brain_look as TL
import test_brain_pattern as TP
import test_brain_stats as TS
import trade_archive as TA

GOLDEN_L1 = "dda14d98c715c92bb424a873fbc5551e1f6d0986c00149349cb0246f31bcc936"     # sha256 of brain_look.analyze on two simulated markets, made with the shipped B4c-1 file


def rows(base, table="look_call"):
    con = sqlite3.connect(os.path.join(base, "brain_archive.db"))
    try:
        return con.execute("SELECT * FROM %s ORDER BY 1, 2, 3, 4" % table).fetchall()
    finally:
        con.close()


def keyed(rs, before=None):
    return {(r[0], r[1], r[2], r[3]): r[4:8] for r in rs if before is None or r[4] < before}       # (pred, m, actual) without the `saved` time


def two_channels(calls):
    return BL.analyze(calls), BP.analyze(calls)


def hand_calls():
    """24 correct + 12 mistake STRONG calls with known numbers (all finished long ago)."""
    out = []
    for i in range(36):
        bad = i % 3 == 0
        cs = TS.calls_of("H%02d" % i, TS.T0 + i * TL.HOUR, [(3, "S", 2.0)], -4.0 if bad else 4.0)
        cs[0]["x"] = [3.0 + 0.1 * (i % 4) if bad else 0.0 + 0.1 * (i % 5),            # big gap
                      1.0 if bad else 0.9 + 0.01 * (i % 3),                            # small gap
                      -2.0 - 0.2 * (i % 3) if bad else 1.0 + 0.2 * (i % 4),            # big negative gap
                      0.5 if i % 2 else None, 0.5, 0.0 + (i % 2), None, 7.0]           # f4 no spread, f5 no gap, f6 never has a number, f7 no spread
        cs[0]["x"][3] = 0.4 + 0.3 * (i % 4) if bad else 0.6 + 0.3 * (i % 4)           # a fourth feature with a gap (only the top 3 may show)
        out += cs
    return out


def expect_gap(calls, k):
    bad = [c["x"][k] for c in calls if c["fin"] < 0]
    ok = [c["x"][k] for c in calls if c["fin"] >= 0]
    return (statistics.mean(bad) - statistics.mean(ok)) / statistics.pstdev(bad + ok)


# ---------------------------------------------------------------- 1. look_call is saved correctly
def test_look_call_rows_are_saved_with_the_right_values_and_versions():
    m = TL.market(450, 5, TP.losing_when_x0_negative, mix=True)
    roi, mis = two_channels(m)
    base = tempfile.mkdtemp()
    rs = BP.rows_of(roi, mis, 123.0)
    assert rs and TA.save_look_calls(rs, base)
    got = rows(base)
    assert len(got) == len(rs) == len(roi["targets"]) + len(mis["targets"]), (len(got), len(rs))
    assert {r[2] for r in got} == {"roi", "mistake"} and {r[3] for r in got} == {"l1", "l1.m1"} and all(r[8] == 123.0 for r in got)
    t = mis["targets"][0]
    one = next(r for r in got if r[:3] == (t["id"], t["st"], "mistake"))
    assert one[3] == "l1.m1" and one[4] == t["t"] and abs(one[5] - t["pred"]) < 1e-3 and one[6] == t["m"] and abs(one[7] - t["actual"]) < 1e-2, (one, t)


# ---------------------------------------------------------------- 2 + 3. no duplicates, old rows never change
def test_repeated_runs_make_no_duplicates_and_a_changed_row_with_the_same_key_is_ignored():
    m = TL.market(400, 7, TP.losing_when_x0_negative)
    roi, mis = two_channels(m)
    base = tempfile.mkdtemp()
    a = BP.rows_of(roi, mis, 1.0)
    TA.save_look_calls(a, base)
    first = rows(base)
    TA.save_look_calls(BP.rows_of(roi, mis, 2.0), base)                                   # same run again, later
    assert rows(base) == first
    tampered = [(r[0], r[1], r[2], r[3], r[4], 99.0, 99, -99.0, 5.0) for r in a]
    TA.save_look_calls(tampered, base)                                                    # same keys, different numbers
    assert rows(base) == first
    more = TL.market(60, 8, TL.noeffect, first=400)
    roi2, mis2 = two_channels(m + more)
    TA.save_look_calls(BP.rows_of(roi2, mis2, 3.0), base)
    after = rows(base)
    assert len(after) > len(first) and keyed(first) == {k: v for k, v in keyed(after).items() if k in keyed(first)}      # old rows byte-identical, only new ones added


def synthetic_refresh(m, base, **kw):
    """BP.refresh on simulated calls (the small real-archive fixture has too few finished trades to score anything)."""
    keep = BL.load
    try:
        BL.load = lambda b=None: (m, {"left_out": 0, "no_feats": 0})
        return BP.refresh(base, **kw)
    finally:
        BL.load = keep


def test_refresh_is_idempotent_is_cached_and_never_touches_the_older_tables():
    base = TS._real_market()                                                              # real archive layout, but only ~86 trades: nothing can be scored yet
    BS.refresh(base, force=True)                                                          # the B4b ledger writes its own rows first
    raw = TS._fingerprint(base, "dual_archive.db", ["obs", "trades"])
    old = TS._fingerprint(base, "brain_archive.db", ["journey", "call_out", "mistake", "learn_stats"])
    res = BP.refresh(base, force=True)
    assert res is not None and BP._C["err"] == "" and res["rows"] == 0 and rows(base) == []
    assert all(r["verdict"] == "NOT ENOUGH DATA" for r in res["mistake"]["slices"][0]["states"].values()) and res["gaps"] == {}
    m = TL.market(450, 5, TP.losing_when_x0_negative, mix=True)                           # enough trades: rows are frozen
    res = synthetic_refresh(m, base, force=True)
    assert res is not None and res["rows"] > 50 and BP._C["err"] == ""
    n1 = rows(base)
    assert len(n1) == res["rows"]
    for _ in range(2):
        assert synthetic_refresh(m, base, force=True) is not None
    after = rows(base)
    assert len(after) == len(n1) and keyed(after) == keyed(n1) and [r[8] for r in after] == [r[8] for r in n1]     # same rows, same first `saved` time
    assert TS._fingerprint(base, "dual_archive.db", ["obs", "trades"]) == raw
    assert TS._fingerprint(base, "brain_archive.db", ["journey", "call_out", "mistake", "learn_stats"]) == old
    t0 = BP._C["t"]
    BP.refresh(base)                                                                      # inside the 10 minute window: cached, nothing recomputed
    assert BP._C["t"] == t0 and len(rows(base)) == len(n1)


# ---------------------------------------------------------------- 4. the future cannot change an older result
def test_future_trades_with_absurd_results_and_numbers_never_change_an_older_row_or_gap():
    base_m = TL.market(400, 7, TP.losing_when_x0_negative)
    start = TS.T0 + 400 * TL.HOUR
    fut = TL.market(120, 8, lambda x, st, rnd: -900.0 if st != "R" else 900.0, first=400, nulls=0.0)
    for c in fut:
        c["x"] = [1e6 * (i + 1) for i in range(8)]
    a = keyed(BP.rows_of(*two_channels(base_m), 1.0), start)
    b = keyed(BP.rows_of(*two_channels(base_m + fut), 2.0), start)
    assert a and a == b, (len(a), len(b))
    cut = max(c["xc"] for c in base_m)
    assert BP.gaps(base_m, "S") and BP.gaps(base_m, "S", cutoff=cut) == BP.gaps(base_m + fut, "S", cutoff=cut)       # a gap picture of the past stays the same


# ---------------------------------------------------------------- 5. gaps are calculated correctly
def test_gaps_match_a_hand_calculation_top_three_only_and_skip_thin_numbers():
    cs = hand_calls()
    g = BP.gaps(cs, "S")
    assert len(g) == BP.TOP_GAPS == 3 and [r["feat"] for r in g] == sorted([r["feat"] for r in g], key=lambda f: -abs(next(x for x in g if x["feat"] == f)["gap"]))
    for r in g:
        k = BL.FEATS.index(r["feat"])
        assert abs(r["gap"] - round(expect_gap(cs, k), 2)) < 0.011, (r, expect_gap(cs, k))
        assert r["mistakes"] + r["correct"] <= 36 and r["mistakes"] >= BS.MIN_HALF and r["correct"] >= BS.MIN_HALF
    allg = {BL.FEATS[k]: abs(expect_gap(cs, k)) for k in (0, 1, 2, 3)}
    assert {r["feat"] for r in g} == set(sorted(allg, key=lambda f: -allg[f])[:3]), (g, allg)
    assert BP.gaps(cs, "T") == [] and BP.gaps([], "S") == []                                # no calls of that state / no calls at all
    few = hand_calls()[:15]                                                               # 5 mistakes only: under MIN_HALF, nothing is shown
    assert BP.gaps(few, "S") == []


# ---------------------------------------------------------------- 6. not enough data
def test_too_little_data_says_not_enough_data_everywhere_and_shows_no_gaps():
    base = tempfile.mkdtemp()
    s = BP.summary(base)                                                                  # no archive at all
    assert s["status"] in ("collecting",) and "NOT ENOUGH DATA" in s["text"] and s["gaps"] == {}
    assert all(r["verdict"] == "NOT ENOUGH DATA" for k in ("roi", "mistake") for r in s[k]["overall"]) and s["roi"]["slices"] == []
    small = TL.market(40, 2, TP.losing_when_x0_negative)
    roi, mis = two_channels(small)
    assert all(r["verdict"] == "NOT ENOUGH DATA" for res in (roi, mis) for r in res["slices"][0]["states"].values())
    assert os.listdir(base) == [] or not rows(base, "look_call")                          # nothing scored, nothing frozen


# ---------------------------------------------------------------- 7. learn.look is valid and cannot break the Brain view
def test_learn_look_is_valid_small_json_with_gaps_only_for_hints_and_a_failure_never_breaks_the_view():
    m = TL.market(500, 5, TP.losing_when_x0_negative, mix=True)
    keep = BL.load
    try:
        BL.load = lambda base=None: (m, {"left_out": 0, "no_feats": 0})
        base = tempfile.mkdtemp()
        BP._C.update(res=None)
        s = BP.summary(base)
        assert BP._C["err"] == "", BP._C["err"]
    finally:
        BL.load = keep
    js = json.dumps(s)
    assert json.loads(js) == s and len(js) < 40000, len(js)
    assert s["status"] == "measuring" and "Not advice" in json.dumps(s["mistake"]["overall"]) and s["provisional"] is True
    hints = {r["state"] for r in s["mistake"]["overall"] if r["verdict"] in BL.HINTS}
    assert hints and set(s["gaps"]) == hints and all(len(v) <= BP.TOP_GAPS for v in s["gaps"].values()), (hints, s["gaps"])
    assert "x0" not in js and "should" not in js.lower().replace("shouldn", "")
    base = TS._real_market()
    v = BLN.view_summary(base)
    assert json.loads(json.dumps(v)) and "look" in v and "stats" in v and v["journeys"] > 5 and v["look"]["status"] in ("collecting", "measuring")
    keep = BP.summary
    try:
        BP.summary = lambda base=None: 1 / 0
        v2 = BLN.view_summary(base)
    finally:
        BP.summary = keep
    assert v2["look"]["status"] == "error" and v2["stats"] == v["stats"] and v2["journeys"] == v["journeys"] and v2["status"] == v["status"]


# ---------------------------------------------------------------- 8. B4c-1 output unchanged
def test_the_b4c1_output_is_identical_to_the_shipped_file_and_not_changed_by_part_two():
    ms = [TL.market(300, 6, TL.planted, mix=True), TL.market(300, 9, TL.noeffect, mix=True)]
    digest = lambda: hashlib.sha256(json.dumps([BL.analyze(m) for m in ms], sort_keys=True, default=str).encode()).hexdigest()
    assert digest() == GOLDEN_L1
    BP.refresh(TS._real_market(), force=True)                                             # running part 2 must not leave anything behind in brain_look
    assert digest() == GOLDEN_L1
    assert BL.CONFIG["feats"] == list(BL.FEATS) and BL.LOOK_VERSION == "l1" and BP.PATTERN_VERSION == "m1"


# ---------------------------------------------------------------- 9. trading is unchanged
def test_trading_output_is_identical_with_part_two_in_place():
    TE.test_process_results_identical_with_and_without_the_hook()                        # same golden sha256 of 2700 runs as before Batch 2
    import test_brain_memory as TM
    assert TM.GOLDEN == "8d35375a68319106dc92c0a7f88b19f744c5617ce03749f33de334d6fbd1aee7"


def test_source_guards_look_call_is_insert_only_and_nothing_that_trades_knows_it():
    pat = open(os.path.join(HERE, "brain_pattern.py")).read()
    code = re.sub(r'""".*?"""', "", pat, flags=re.S)
    assert not re.search(r"delete\s+from|drop\s+table|update\s+\w+\s+set|insert\s|create\s+table|sqlite3", code, re.I)
    ta = open(os.path.join(HERE, "trade_archive.py")).read()
    assert "INSERT OR IGNORE INTO look_call" in ta and not re.search(r"(UPDATE|DELETE\s+FROM|DROP\s+TABLE|REPLACE\s+INTO)\s+look_call", ta, re.I)
    assert not re.search(r"INSERT\s+OR\s+REPLACE", ta, re.I)
    for bad in ("requests", "urllib", "anthropic", "websocket", "paper_trader", "strategy", "dual_lab", "market_ws", "telegram", "smart_brain", "random"):
        assert not re.search(r"^\s*(import|from)\s+%s\b" % bad, code, re.M), bad
    assert not re.search(r"def (_shift_p|_guess|_spread|_dist|_stat|_finish|_judge|_luck_p|_Base|judged|evaluate|load)\b", code)       # reuses, never copies
    for f in os.listdir(HERE):
        if f.endswith(".py") and f not in ("brain_pattern.py", "brain_learn.py", "test_brain_pattern.py", "test_brain_pattern2.py", "test_brain_look.py"):
            assert not re.search(r"^\s*(import|from)\s+brain_pattern\b|\bBP\.|brain_pattern\.", open(os.path.join(HERE, f)).read(), re.M), f
    sb = open(os.path.join(HERE, "smart_brain.py")).read()
    assert "brain_pattern" not in sb and "look_call" not in sb


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")
