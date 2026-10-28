"""Tests for Batch 4d-1 (brain_shadow.py): shadow rule r1 + the evidence gate (latest frozen learn_stats copy BEFORE the candle).
Run: cd backend && python3 test_brain_shadow.py
"""
import json, os, re, sys, tempfile
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "recovered_bot"))
sys.path.insert(0, HERE)
import brain_shadow as SH
import brain_stats as BS
import test_brain_edge as TE
import test_brain_look as TL
import test_brain_stats as TS
import trade_archive as TA

SEC = 1000


def copy(rows, slice_="all"):
    """A learn_stats copy as brain_stats._snapshot writes it: rows = [(state, verdict, lean)]."""
    return json.dumps({"v": "s1", "trades": 100, "tests": 1, "ledger": [],
                       "res": [{"state": s, "n": 40, "excess": 1.0, "shrunk": 0.5, "p": 0.01, "p_adj": 0.02, "verdict": v, "lean": ln, "halves": [1, 1], "slice": slice_}
                               for s, v, ln in rows]})


def put(base, copies):
    """Test-only: writes learn_stats rows at chosen times (seconds) into a temp brain_archive.db."""
    con = TA._open(TA.BRAIN_DB, TA._BRAIN_SQL, base)
    with con:
        for t, js in copies:
            con.execute("INSERT INTO learn_stats(v, t, trades, js) VALUES('s1', ?, 100, ?)", (t, js))
    con.close()


def gates_of(copies):
    return [(t, 100, json.loads(js)) for t, js in copies]


# ---------------------------------------------------------------- 1. the rule, every combination
def test_rule_r1_gives_exactly_the_proposed_answer_for_every_combination():
    assert SH.RULE_VERSION == "r1" and SH.HINTS == ("EARLY HINT", "SUPPORTED") and SH.EVIDENCE_VERSION == "s1"
    for v in ("NO CLEAR PATTERN", "NOT ENOUGH DATA", "EARLY HINT", "SUPPORTED", None):
        for lean in ("hold", "exit_now", None):
            g = (1.0, 100, json.loads(copy([("S", v, lean)])))
            for roi in (5.0, 0.0, -3.0, None):
                want = "NO_OPINION"
                if v in ("EARLY HINT", "SUPPORTED"):
                    if lean == "hold":
                        want = "HOLD_OK"
                    elif lean == "exit_now" and roi is not None and roi > 0:
                        want = "PROTECT_LOOKS_BETTER"
                r = SH.decide("S", roi, g)
                assert r["rec"] == want and r["rec"] in SH.RECS, (v, lean, roi, r)
                assert (r["level"] == v) if v in SH.HINTS else True
                assert "shadow only" in r["text"] and not re.search(r"\b(should|buy now|sell now|close it|exit now)\b", r["text"].lower()), r["text"]
    assert SH.decide("S", 5.0, None)["rec"] == "NO_OPINION" and SH.decide("S", 5.0, None)["snap_t"] is None
    g = (1.0, 100, json.loads(copy([("T", "SUPPORTED", "hold")])))
    assert SH.decide("S", 5.0, g)["rec"] == "NO_OPINION" and SH.decide("X", 5.0, g)["rec"] == "NO_OPINION"          # state missing in the copy = under 30 trades
    sl = (1.0, 100, json.loads(copy([("S", "SUPPORTED", "hold")], slice_="BUY 5m trending")))
    assert SH.decide("S", 5.0, sl)["rec"] == "NO_OPINION"                                                           # r1 uses slice "all" only


# ---------------------------------------------------------------- 2. the gate is the latest copy strictly BEFORE the candle
def test_the_gate_is_the_latest_copy_saved_strictly_before_the_candle():
    c = [(100.0, copy([("S", "EARLY HINT", "hold")])), (200.0, copy([("S", "EARLY HINT", "exit_now")])), (300.0, copy([("S", "SUPPORTED", "hold")]))]
    g = gates_of(c)
    assert SH.gate_at(g, 99 * SEC) is None and SH.gate_at([], 10 ** 12) is None
    assert SH.gate_at(g, 100 * SEC) is None                                  # saved at the very moment the candle opened: not before it
    assert SH.gate_at(g, 100 * SEC + 1)[0] == 100.0 and SH.gate_at(g, 250 * SEC)[0] == 200.0 and SH.gate_at(g, 10 ** 12)[0] == 300.0
    assert SH.recommend("S", 2.0, 250 * SEC, g)["rec"] == "PROTECT_LOOKS_BETTER" and SH.recommend("S", 2.0, 250 * SEC, g)["snap_t"] == 200.0
    assert SH.recommend("S", -2.0, 250 * SEC, g)["rec"] == "NO_OPINION"
    assert SH.recommend("S", 2.0, 350 * SEC, g)["rec"] == "HOLD_OK" and SH.recommend("S", 2.0, 50 * SEC, g)["rec"] == "NO_OPINION"


# ---------------------------------------------------------------- 3. no look-ahead
def test_nothing_from_the_future_can_change_an_older_recommendation():
    old = [(100.0, copy([("S", "EARLY HINT", "hold"), ("T", "SUPPORTED", "exit_now")])), (200.0, copy([("S", "NO CLEAR PATTERN", None)]))]
    future = [(500.0, copy([("S", "SUPPORTED", "exit_now"), ("T", "SUPPORTED", "hold")])), (900.0, copy([("S", "EARLY HINT", "hold")]))]
    times = [50, 100, 150, 250, 400, 499]
    key = lambda gs: [(s, roi, t, SH.recommend(s, roi, t * SEC, gs)) for s in "ST" for roi in (3.0, -3.0) for t in times]
    assert key(gates_of(old)) == key(gates_of(old + future))
    assert SH.recommend.__code__.co_varnames[:SH.recommend.__code__.co_argcount] == ("st", "roi", "t_ms", "gates")     # the entry point takes no outcome data at all
    base = tempfile.mkdtemp()
    put(base, old)
    a = [SH.recommend("S", 3.0, t * SEC, SH.load_gates(base)) for t in times]
    put(base, future)                                                        # later copies arrive in the archive: older candles keep their answer
    assert a == [SH.recommend("S", 3.0, t * SEC, SH.load_gates(base)) for t in times]


# ---------------------------------------------------------------- 4. not enough data behaves
def test_missing_thin_or_broken_evidence_gives_no_opinion_and_never_crashes():
    empty = tempfile.mkdtemp()
    assert SH.load_gates(empty) == [] and os.listdir(empty) == []            # no archive: nothing read, nothing created
    r = SH.run(empty)
    assert r["err"] == "" and r["copies"] == 0 and all(v == {"in_profit": "NO_OPINION", "not_in_profit": "NO_OPINION"} for v in r["table"].values()) and set(r["table"]) == set(BS.STATES)
    base = tempfile.mkdtemp()
    put(base, [(100.0, "{not json"), (150.0, json.dumps({"res": "no"})), (180.0, json.dumps([1, 2])), (190.0, copy([]))])
    g = SH.load_gates(base)
    assert [x[0] for x in g] == [190.0] and SH.recommend("S", 5.0, 1000 * SEC, g)["rec"] == "NO_OPINION"          # unreadable copies are skipped, an empty copy says nothing
    put(base, [(120.0, copy([("S", "NOT ENOUGH DATA", None), ("T", "NO CLEAR PATTERN", None)]))])
    assert all(SH.recommend(s, 5.0, 1000 * SEC, SH.load_gates(base))["rec"] == "NO_OPINION" for s in "ST")
    old = tempfile.mkdtemp()                                                 # an archive from before learn_stats existed
    import sqlite3
    sqlite3.connect(os.path.join(old, "brain_archive.db")).execute("CREATE TABLE own (id TEXT)").connection.close()
    assert SH.load_gates(old) == []


# ---------------------------------------------------------------- 5. works on the REAL copy format
def test_it_reads_a_real_brain_stats_copy_and_follows_its_verdict_and_lean():
    hold = lambda x, st, rnd: (6.0 if st == "S" else 0.0) + rnd.gauss(0, 2)      # STRONG: holding adds
    leave = lambda x, st, rnd: (-6.0 if st == "S" else 0.0) + rnd.gauss(0, 2)    # STRONG: leaving adds
    r1, r2 = BS.analyze(TL.market(500, 5, hold, mix=True)), BS.analyze(TL.market(500, 6, leave, mix=True))
    s1, s2 = (next(r for r in x["slices"][0]["states"].values() if r["state"] == "S") for x in (r1, r2))
    assert s1["verdict"] in SH.HINTS and s1["lean"] == "hold" and s2["verdict"] in SH.HINTS and s2["lean"] == "exit_now", (s1, s2)
    base = tempfile.mkdtemp()
    put(base, [(1000.0, BS._snapshot(r1)), (2000.0, BS._snapshot(r2))])
    g = SH.load_gates(base)
    assert len(g) == 2
    a = SH.recommend("S", -1.0, 1500 * SEC, g)                                   # between the two copies: the first one rules
    assert a["rec"] == "HOLD_OK" and a["level"] == s1["verdict"] and a["snap_t"] == 1000.0 and a["rule"] == "r1"
    b, c = SH.recommend("S", 2.0, 2500 * SEC, g), SH.recommend("S", -2.0, 2500 * SEC, g)
    assert b["rec"] == "PROTECT_LOOKS_BETTER" and b["level"] == s2["verdict"] and c["rec"] == "NO_OPINION"
    assert SH.recommend("S", 2.0, 999 * SEC, g)["rec"] == "NO_OPINION"           # before any copy existed


# ---------------------------------------------------------------- 6. raw data is unchanged
def test_a_real_archive_is_read_only_and_everything_in_it_stays_identical():
    base = TS._real_market()
    BS.refresh(base, force=True)
    put(base, [(5.0, copy([("S", "SUPPORTED", "hold")]))])
    raw = TS._fingerprint(base, "dual_archive.db", ["obs", "trades"])
    old = TS._fingerprint(base, "brain_archive.db", ["journey", "call_out", "mistake", "learn_stats"])
    files, sr = sorted(os.listdir(base)), TS._fingerprint(base, "brain_archive.db", ["shadow_rec"])
    r = SH.run(base)
    assert r["err"] == "" and r["copies"] >= 1 and SH.recommend("S", 1.0, 10 ** 13, SH.load_gates(base))["rec"] in SH.RECS
    assert TS._fingerprint(base, "dual_archive.db", ["obs", "trades"]) == raw and TS._fingerprint(base, "brain_archive.db", ["journey", "call_out", "mistake", "learn_stats"]) == old
    assert sorted(os.listdir(base)) == files and TS._fingerprint(base, "brain_archive.db", ["shadow_rec"]) == sr     # the hand run stores nothing (the 4d-2 table exists since then)


# ---------------------------------------------------------------- 7. trading is unchanged
def test_trading_output_is_identical_with_4d1_in_place():
    TE.test_process_results_identical_with_and_without_the_hook()            # same golden sha256 of 2700 runs as before Batch 2
    import test_brain_memory as TM
    assert TM.GOLDEN == "8d35375a68319106dc92c0a7f88b19f744c5617ce03749f33de334d6fbd1aee7"


# ---------------------------------------------------------------- 8. guards: read only, not connected, locked
def test_source_guards_read_only_not_connected_and_nothing_stored_or_decided():
    code = re.sub(r'""".*?"""', "", open(os.path.join(HERE, "brain_shadow.py")).read(), flags=re.S)
    assert not re.search(r"delete\s+from|drop\s+table|update\s+\w+\s+set|insert\s|create\s+table|sqlite3|open\(", code, re.I)
    for bad in ("requests", "urllib", "anthropic", "websocket", "paper_trader", "strategy", "dual_lab", "market_ws", "telegram", "smart_brain", "random", "brain_look", "brain_pattern"):
        assert not re.search(r"^\s*(import|from)\s+%s\b" % bad, code, re.M), bad
    ta = open(os.path.join(HERE, "trade_archive.py")).read()
    fn = ta[ta.index("def learn_snapshots"):ta.index("def learn_counts")]
    assert "SELECT" in fn and not re.search(r"INSERT|UPDATE|DELETE|DROP|CREATE|REPLACE", fn) and "open_brain_ro" in fn and "shadow_rec" not in fn
    for f in os.listdir(HERE):
        if f.endswith(".py") and f not in ("brain_shadow.py", "test_brain_shadow.py", "test_brain_shadow2.py", "brain_learn.py", "trade_archive.py"):
            src = open(os.path.join(HERE, f)).read()
            assert not re.search(r"^\s*(import|from)\s+brain_shadow\b|brain_shadow\.", src, re.M) and "shadow_rec" not in src, f        # connected only by brain_learn (4d-2); the writer itself is tested in test_brain_shadow2.py


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")
