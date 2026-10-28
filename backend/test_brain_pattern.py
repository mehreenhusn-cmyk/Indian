"""Tests for Batch 4c-2 part 1 (brain_pattern.py): mistake risk from look-alikes, same protections as brain_look / brain_stats.
Run: cd backend && python3 test_brain_pattern.py
"""
import json, os, re, sys, tempfile
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "recovered_bot"))
sys.path.insert(0, HERE)
import brain_look as BL
import brain_pattern as BP
import brain_stats as BS
import test_brain_look as TL
import test_brain_stats as TS

HINTS = ("EARLY HINT", "SUPPORTED")


def losing_when_x0_negative(x, st, rnd):      # STRONG calls end in a loss when the first number is negative, in a profit when positive
    return ((-30 if x[0] < 0 else 30) + rnd.gauss(0, 2)) if st == "S" else rnd.gauss(0, 3)


def S(res, st="S", name="all"):
    return next(g for g in res["slices"] if g["slice"] == name)["states"][st]


def test_a_planted_mistake_pattern_is_detected_with_the_right_direction():
    r = S(BP.analyze(TL.market(500, 5, losing_when_x0_negative)))
    assert r["verdict"] in HINTS and r["score"] > 15 and r["n"] >= 60, r
    assert r["risky_ex"] > 20 and r["safe_ex"] < -20 and r["risky_n"] > 10 and r["safe_n"] > 10, r       # risky guesses erred more, reliable ones less
    assert r["kind"] == "S_lost" and "STRONG but the trade lost" in r["text"] and "Not advice" in r["text"], r["text"]


def test_no_effect_is_never_supported_and_early_hints_by_luck_stay_rare():
    sup = hint = tot = hint_sl = tot_sl = 0
    for seed in range(200, 230):
        res = BP.analyze(TL.market(450, seed, TL.noeffect, mix=True))
        for g in res["slices"]:
            for r in g["states"].values():
                if r["n"] < BS.MIN_N:
                    continue
                sup += r["verdict"] == "SUPPORTED"
                if g["slice"] == "all":
                    tot += 1
                    hint += r["verdict"] == "EARLY HINT"
                else:
                    tot_sl += 1
                    hint_sl += r["verdict"] == "EARLY HINT"
    assert sup == 0 and tot > 20 and tot_sl > 80, (sup, tot, tot_sl)
    assert hint <= 0.15 * tot and hint_sl <= 0.05 * tot_sl, (hint, tot, hint_sl, tot_sl)


def test_future_trades_with_absurd_results_and_numbers_never_change_an_older_result():
    base = TL.market(400, 7, losing_when_x0_negative)
    start = TS.T0 + 400 * TL.HOUR
    fut = TL.market(120, 8, lambda x, st, rnd: -900.0 if st != "R" else 900.0, first=400, nulls=0.0)
    for c in fut:
        c["x"] = [1e6 * (i + 1) for i in range(8)]
    key = lambda res: {(t["id"], t["st"]): (t["pred"], t["actual"], t["m"]) for t in res["targets"] if t["t"] < start}
    a, b = key(BP.analyze(base)), key(BP.analyze(base + fut))
    assert a and a == b, (len(a), len(b))


def test_under_thirty_calls_say_not_enough_data_and_nothing_at_all_does_not_crash():
    for r in BP.analyze(TL.market(40, 2, losing_when_x0_negative))["slices"][0]["states"].values():
        assert r["verdict"] == "NOT ENOUGH DATA" and r["p"] is None and "NOT ENOUGH DATA" in r["text"], r
    res = BP.analyze([])
    assert res["trades"] == 0 and all(r["verdict"] == "NOT ENOUGH DATA" for r in res["slices"][0]["states"].values())


def test_a_long_trade_with_many_calls_of_one_state_counts_once():
    base = TL.market(300, 3, TL.noeffect)
    long = TS.calls_of("LONG", TS.T0 + 900 * TL.HOUR, [(n, "S", 4.0) for n in range(1, 8)], -3.0)
    for c in long:
        c["x"] = [0.1] * 8
    a, b = BP.analyze(base), BP.analyze(base + long)
    assert b["coverage"]["S"]["judged"] <= a["coverage"]["S"]["judged"] + 1
    ids = [t["id"] for t in b["targets"] if t["st"] == "S"]
    assert len(ids) == len(set(ids)) and ids.count("LONG") <= 1


def test_the_mistake_rule_is_exactly_the_b4b_ledger_rule_for_every_call():
    series = [(1, "T", 2.0), (2, "W", 6.0), (3, "T", 1.0)]
    for fin in (-4.0, 0.0, 9.0, 3.0):
        for c in TS.calls_of("A", TS.T0, series, fin):
            for s in BS.STATES:
                assert (BP.flag(c, s) == 100.0) == bool(BS.KINDS[s][2](c)), (c, s)


def test_the_default_look_alike_measure_is_unchanged_by_the_new_option():
    m = TL.market(300, 6, TL.planted, mix=True)
    a = json.dumps(BL.analyze(m), sort_keys=True, default=str)
    assert a == json.dumps(BL.analyze(m, flag=None), sort_keys=True, default=str)
    assert BP.analyze(m)["channel"] == "mistake" and BL.analyze(m).get("channel") is None


def test_the_usual_rate_is_made_from_finished_trades_only_and_the_old_measure_is_not_touched():
    m = TL.market(300, 6, losing_when_x0_negative)
    before = json.dumps(m, sort_keys=True, default=str)
    BP.analyze(m)
    assert json.dumps(m, sort_keys=True, default=str) == before                      # the input calls are never changed


def test_a_real_archive_is_read_only_and_everything_in_it_stays_identical():
    base = TS._real_market()
    raw = TS._fingerprint(base, "dual_archive.db", ["obs", "trades"])
    old = TS._fingerprint(base, "brain_archive.db", ["journey", "call_out"])
    out = BP.run(base)
    assert out["err"] == "" and set(out["states"]) == set(BS.STATES) and out["channel"] == "mistake"
    assert all(r["verdict"] in ("NOT ENOUGH DATA", "NO CLEAR PATTERN") + HINTS for r in out["states"].values())
    assert TS._fingerprint(base, "dual_archive.db", ["obs", "trades"]) == raw and TS._fingerprint(base, "brain_archive.db", ["journey", "call_out"]) == old
    empty = tempfile.mkdtemp()
    assert BP.run(empty)["trades"] == 0 and os.listdir(empty) == []


def test_texts_are_plain_and_never_advice():
    res = BP.analyze(TL.market(500, 5, losing_when_x0_negative, mix=True))
    for g in res["slices"]:
        for r in g["states"].values():
            t = r["text"].lower()
            assert "not advice" in t or "not enough data" in t or "no clear pattern" in t or "bunched" in t, t
            assert not re.search(r"\b(should|recommend|buy now|sell now|close it|exit now)\b", t), t


def test_source_guards_no_network_no_trading_no_writes_and_no_copied_logic():
    code = re.sub(r'""".*?"""', "", open(os.path.join(HERE, "brain_pattern.py")).read(), flags=re.S)
    assert not re.search(r"delete\s+from|drop\s+table|update\s+\w+\s+set|insert\s+(or\s+\w+\s+)?into|create\s+table", code, re.I)
    for bad in ("requests", "urllib", "anthropic", "websocket", "paper_trader", "strategy", "dual_lab", "market_ws", "telegram", "smart_brain", "random", "sqlite3"):
        assert not re.search(r"^\s*(import|from)\s+%s\b" % bad, code, re.M), bad
    assert not re.search(r"def (_shift_p|_guess|_spread|_dist|_stat|_finish|_judge|_luck_p|_Base|judged|evaluate)\b", code)    # reuses, never copies
    for f in os.listdir(HERE):
        if f.endswith(".py") and f not in ("brain_pattern.py", "test_brain_pattern.py", "test_brain_look.py"):
            assert not re.search(r"^\s*(import|from)\s+brain_pattern\b|brain_pattern\.", open(os.path.join(HERE, f)).read(), re.M), f      # not connected yet (Part 2)


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")
