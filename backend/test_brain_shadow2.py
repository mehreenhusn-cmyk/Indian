"""Tests for Batch 4d-2 (brain_shadow.step): the live shadow writer + the insert-only shadow_rec table. Run: cd backend && python3 test_brain_shadow2.py [timing_trades]"""
import hashlib, json, os, re, sqlite3, stat, sys, tempfile, time
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "recovered_bot"))
sys.path.insert(0, HERE)
import brain_edge as BE
import brain_learn as BL
import brain_shadow as SH
import test_brain_edge as TE
import test_brain_shadow as T1
import test_brain_stats as TS
import trade_archive as TA

T0, MS = 1_700_000_000_000, 300000
SEC0 = T0 // 1000
SH.MAX_AGE_C = 10 ** 7                                           # the age rule has its own test; the others see every candle


def obs(tid, n, roi, tag="S", k="O", lag=0, ov="o1", f=None):
    f = f or [0.0] * len(BE.OBS_KEYS)
    f[BE.OBS_KEYS.index("roi")] = roi
    return (tid, T0 + n * MS, k, n, "XUSDT", "5m", 1, ov, "b1", tag, lag, json.dumps(f))


def dual(base, trades=(), rows=()):
    """Test-only: writes trades [(id, status, net)] and obs rows into a temp dual_archive.db."""
    con = TA._open(TA.DUAL_DB, TA._DUAL_SQL, base)
    with con:
        con.executemany("INSERT OR IGNORE INTO trades(id,t,sym,tf,side,src,status,net,exit_rule,mode,saved,js) VALUES(?,?,'XUSDT','5m',1,'Z',?,?,'x','m',1.0,'{}')", [(i, 1, s, n) for i, s, n in trades])
        con.executemany("INSERT OR IGNORE INTO obs(id,t,k,n,sym,tf,d,v,bv,tag,lag,f) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute("INSERT OR IGNORE INTO meta(k,v) VALUES(?,?)", ("obs_keys_o1", json.dumps(list(BE.OBS_KEYS))))
    con.close()


COPIES = [(SEC0 + 100, T1.copy([("S", "EARLY HINT", "hold")])), (SEC0 + 1000, T1.copy([("S", "SUPPORTED", "exit_now")]))]
ROIS = [2.0, 3.0, -1.0, 2.0, 4.0, -2.0]


def recs(base, cols="id, t, rule, st, roi, tf, d, rec, level, lean, ev, snap_t, snap_trades"):
    try:
        return sqlite3.connect(os.path.join(base, "brain_archive.db")).execute("SELECT %s FROM shadow_rec ORDER BY id, t" % cols).fetchall()
    except Exception:
        return []


def world(n=6):
    base = tempfile.mkdtemp()
    dual(base, [("OP", "open", None)], [obs("OP", i + 1, r) for i, r in enumerate(ROIS[:n])])
    T1.put(base, COPIES)
    return base


# ---------------------------------------------------------------- 1. saved correctly
def test_shadow_rec_rows_hold_the_right_values():
    base = world()
    r = SH.step(base)
    assert r == {"seen": 6, "err": ""}, r
    got = recs(base)
    assert [x[7] for x in got] == ["HOLD_OK"] * 3 + ["PROTECT_LOOKS_BETTER"] * 2 + ["NO_OPINION"]            # copy 1 rules until +1000 s, then copy 2
    assert [x[4] for x in got] == ROIS and all(x[:4] == ("OP", T0 + (i + 1) * MS, "r1", "S") and x[5:7] == ("5m", 1) for i, x in enumerate(got))
    assert got[0][8:] == ("EARLY HINT", "hold", "s1", SEC0 + 100.0, 100) and got[3][8] == "SUPPORTED" and got[3][11] == SEC0 + 1000.0
    assert set(TA.SCOLS) == {c[1] for c in sqlite3.connect(os.path.join(base, "brain_archive.db")).execute("PRAGMA table_info(shadow_rec)")}
    for t, rec, why in sqlite3.connect(os.path.join(base, "brain_archive.db")).execute("SELECT t, rec, why FROM shadow_rec"):
        assert rec in SH.RECS and why and not re.search(r"\b(final|mfe|later)\b", why)                          # no outcome words in what was frozen


def test_no_opinion_rows_are_stored_too_and_say_why():
    base = tempfile.mkdtemp()
    dual(base, [("OP", "open", None)], [obs("OP", 1, 2.0), obs("OP", 2, 1.0, tag="T")])
    SH.step(base)                                                                                             # no evidence copy at all yet
    got = recs(base, "rec, snap_t, level")
    assert got == [("NO_OPINION", None, None)] * 2 and "no evidence copy" in sqlite3.connect(os.path.join(base, "brain_archive.db")).execute("SELECT why FROM shadow_rec").fetchone()[0]
    T1.put(base, COPIES[:1])
    SH.step(base)
    assert [x[0] for x in recs(base, "rec")] == ["NO_OPINION"] * 2                                          # the old rows are frozen, a copy that came later changes nothing


# ---------------------------------------------------------------- 2/3. no duplicates, rows never change
def test_repeated_runs_make_no_duplicates_and_a_tamper_attempt_is_ignored():
    base = world()
    SH.step(base)
    first = recs(base, "*")
    for _ in range(3):
        SH.step(base)
    assert recs(base, "*") == first                                                                           # same rows, saved time included
    bad = [tuple("HACK" if c == "rec" else 99.0 if c in ("roi", "saved") else v for c, v in zip(TA.SCOLS, first[0]))]
    assert TA.save_shadow_recs(bad, base) is True and recs(base, "*") == first


# ---------------------------------------------------------------- 4. no look-ahead
def test_future_candles_verdicts_and_results_never_change_an_old_row():
    base = world(4)
    SH.step(base)
    old = recs(base, "*")
    dual(base, [], [obs("OP", 5, 999.0), obs("OP", 6, -999.0, tag="R")])                                     # later candles with absurd numbers
    T1.put(base, [(SEC0 + 5000, T1.copy([("S", "SUPPORTED", "hold")])), (SEC0 + 9000, T1.copy([("S", "EARLY HINT", "exit_now")]))])
    SH.step(base)
    assert recs(base, "*")[:4] == old and len(recs(base)) == 6
    dual(base, [], [obs("OP", 7, -50.0, tag="sl", k="X")])
    con = sqlite3.connect(os.path.join(base, "dual_archive.db"))
    con.execute("UPDATE trades SET status = 'closed', net = -50.0 WHERE id = 'OP'")                         # the trade finished badly
    con.commit()
    con.close()
    SH.step(base)
    assert recs(base, "*")[:4] == old and len(recs(base)) == 6                                                # nothing new, nothing changed
    assert SH.step.__code__.co_varnames[:2] == ("base", "now_ms")


def test_candle_by_candle_equals_one_run_at_the_end():
    a, b = tempfile.mkdtemp(), world()
    T1.put(a, COPIES)
    for i, r in enumerate(ROIS):
        dual(a, [("OP", "open", None)], [obs("OP", i + 1, r)])
        SH.step(a)
    SH.step(b)
    strip = lambda x: [r[:-1] for r in recs(x, "*")]
    assert strip(a) == strip(b) and len(strip(a)) == 6


# ---------------------------------------------------------------- 5. what is observed
def test_only_open_trades_fresh_known_rows_are_observed():
    base = tempfile.mkdtemp()
    ok = [obs("OP", 1, 1.0), obs("OP", 2, 2.0, lag=2)]
    skip = [obs("OP", 3, 3.0, lag=3), obs("OP", 4, 4.0, k="X"), obs("OP", 5, 5.0, ov="o9"), obs("OP", 6, 6.0, tag=None), obs("OP", 7, 7.0, tag="Z")]
    dual(base, [("OP", "open", None), ("CL", "closed", 1.0), ("SK", "skipped", None), ("SD", "skipped_done", -1.0)],
         ok + skip + [obs(i, 1, 1.0) for i in ("CL", "SK", "SD")])
    assert SH.step(base)["seen"] == 2 and [(x[0], x[1]) for x in recs(base)] == [("OP", T0 + MS), ("OP", T0 + 2 * MS)]
    old, SH.MAX_AGE_C = SH.MAX_AGE_C, 3                                                                       # default: live only, no back-fill
    try:
        b2, b3 = world(), world()
        assert SH.step(b2, now_ms=T0 + 6 * MS + 1)["seen"] == 4 and [x[1] for x in recs(b2)] == [T0 + n * MS for n in (3, 4, 5, 6)]
        assert SH.step(b3, now_ms=T0 + 20 * MS)["seen"] == 0 and recs(b3) == []                                 # worker was down for a long time: nothing back-filled
    finally:
        SH.MAX_AGE_C = old


def test_the_since_option_gives_the_same_gate_as_loading_everything():
    base = tempfile.mkdtemp()
    T1.put(base, [(SEC0 + 100 * i, T1.copy([("S", "EARLY HINT", "hold" if i % 2 else "exit_now")])) for i in range(1, 30)])
    full = SH.load_gates(base)
    for since in (SEC0 + 5, SEC0 + 100, SEC0 + 1550, SEC0 + 99999):
        part = SH.load_gates(base, since)
        for t in (since, since + 1, since + 777):
            assert (SH.gate_at(part, t * 1000) or (None,))[0] == (SH.gate_at(full, t * 1000) or (None,))[0], (since, t)         # None = no copy before it, in both
    assert len(SH.load_gates(base, SEC0 + 2000)) < len(full)


# ---------------------------------------------------------------- 6. a failure cannot break the Brain
def test_archive_or_rule_failures_never_break_step_or_the_brain_view():
    base = TS._real_market()
    before = recs(base, "*")                                                                                  # the real run already has shadow rows of its open trades
    dual(base, [("OP", "open", None)], [obs("OP", 1, 1.0)])
    keep = SH.decide
    def boom(*a):
        raise RuntimeError("rule failed")
    SH.decide = boom
    try:
        assert SH.step(base)["err"].startswith("RuntimeError") and BL.step(base) == {"new": 0, "err": ""}
        assert BL.view_summary(base)["journeys"] > 5 and recs(base, "*") == before
    finally:
        SH.decide = keep
    for victim in ("brain_archive.db", "dual_archive.db"):                                                    # a corrupt file
        b = world()
        open(os.path.join(b, victim), "wb").write(b"not a database" * 50)
        assert SH.step(b)["err"] != ""
        r = BL.step(b)
        assert set(r) == {"new", "err"} and set(BL.view_summary(b)) >= {"journeys", "stats", "look"}
    b = world()
    os.chmod(b, stat.S_IRUSR | stat.S_IXUSR)                                                                  # a read-only folder
    try:
        assert set(SH.step(b)) == {"seen", "err"} and set(BL.step(b)) == {"new", "err"}
    finally:
        os.chmod(b, stat.S_IRWXU)
    assert SH.step(tempfile.mkdtemp()) == {"seen": 0, "err": ""}                                              # no Dual archive: nothing happens, no file appears


def test_the_brain_cycle_runs_the_writer_and_keeps_its_own_result_unchanged():
    base = TS._real_market()
    assert BL.step(base) == {"new": 0, "err": ""} and len(recs(base)) > 0                                     # real Dual output: open trades' rows were read and frozen
    dual(base, [("OP", "open", None)], [obs("OP", 1, 1.0)])
    T1.put(base, COPIES[:1])
    assert BL.step(base) == {"new": 0, "err": ""} and [x[7] for x in recs(base) if x[0] == "OP"] == ["HOLD_OK"]   # hooked: ran although there was no new journey


# ---------------------------------------------------------------- 7. raw data, trading, guards
def test_raw_tables_are_byte_identical_and_trading_output_is_unchanged():
    base = TS._real_market()
    raw, old = TS._fingerprint(base, "dual_archive.db", ["obs", "trades"]), TS._fingerprint(base, "brain_archive.db", ["journey", "call_out", "mistake", "learn_stats", "look_call"])
    dual(base, [("OP", "open", None)], [obs("OP", 1, 1.0)])
    raw = TS._fingerprint(base, "dual_archive.db", ["obs", "trades"])
    SH.step(base)
    assert TS._fingerprint(base, "dual_archive.db", ["obs", "trades"]) == raw and TS._fingerprint(base, "brain_archive.db", ["journey", "call_out", "mistake", "learn_stats", "look_call"]) == old
    T1.test_trading_output_is_identical_with_4d1_in_place()


def test_source_guards_writes_only_through_trade_archive_and_nothing_trades():
    code = re.sub(r'""".*?"""', "", open(os.path.join(HERE, "brain_shadow.py")).read(), flags=re.S)
    assert not re.search(r"delete\s+from|drop\s+table|update\s+\w+\s+set|insert\s|create\s+table|sqlite3|open\(", code, re.I) and set(re.findall(r"\bTA\.(\w+)", code)) == {"learn_snapshots", "open_dual_ro", "save_shadow_recs", "_S"}
    for bad in ("requests", "urllib", "anthropic", "websocket", "paper_trader", "strategy", "dual_lab", "market_ws", "telegram", "smart_brain", "random", "sklearn", "numpy"):
        assert not re.search(r"^\s*(import|from)\s+%s\b" % bad, code, re.M), bad
    ta = open(os.path.join(HERE, "trade_archive.py")).read()
    assert not re.search(r"delete\s+from|drop\s+table", ta, re.I) and "INSERT OR IGNORE INTO shadow_rec" in ta and not re.search(r"(UPDATE|REPLACE)[^\n]*shadow_rec", ta)
    assert "brain_shadow" not in open(os.path.join(HERE, "smart_brain.py")).read()
    assert len(re.findall(r"brain_shadow", open(os.path.join(HERE, "brain_learn.py")).read())) == 1                  # one lazy import, one call


# ---------------------------------------------------------------- 8. speed on a bigger archive
def timing(n_trades, opens=40, rows_each=20):
    """n_trades finished trades = n_trades / 10 frozen evidence copies; `opens` open trades. -> ms for one writer cycle and for one Brain cycle."""
    base = tempfile.mkdtemp()
    T1.put(base, [(SEC0 + 60 * i, T1.copy([(s, "EARLY HINT", "hold") for s in "STWR"])) for i in range(max(1, n_trades // 10))])
    dual(base, [("O%d" % i, "open", None) for i in range(opens)], [obs("O%d" % i, n, 1.0 + n % 3) for i in range(opens) for n in range(1, rows_each + 1)])
    t = time.time(); r = SH.step(base); a = (time.time() - t) * 1000
    t = time.time(); BL.step(base); b = (time.time() - t) * 1000
    t = time.time(); SH.step(base); c = (time.time() - t) * 1000
    assert r["err"] == "" and r["seen"] == opens * rows_each and len(recs(base)) == opens * rows_each
    return round(a), round(b), round(c)


def test_one_cycle_is_fast_on_1200_trades():
    a, b, c = timing(1200)
    print("   1,200 trades: first writer cycle %d ms, brain cycle %d ms, repeat cycle %d ms" % (a, b, c))
    assert a < 1500 and c < 1500


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print("timing", sys.argv[1], "trades (first, brain cycle, repeat ms):", timing(int(sys.argv[1])))
        sys.exit(0)
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")
