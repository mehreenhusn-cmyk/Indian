"""Batch 4b-1 - the TRADE JOURNEY (facts only, observation only). Run: cd backend && python3 test_brain_learn.py
Proves: journey numbers are right, NO LOOK-AHEAD in what the Brain knew at a candle, missing data is flagged not guessed, dual_archive.db is only
READ (also while the Dual worker keeps writing), the brain archive is append-only and versioned, a crash never reaches anything, no verdicts exist,
nothing that decides can read the journeys, trading output is byte-identical."""
import copy, hashlib, json, os, re, sqlite3, subprocess, sys, tempfile, time
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "recovered_bot"))
sys.path.insert(0, HERE)
import brain_edge as BE
import brain_learn as BL
import trade_archive as TA
import test_brain_edge as TE

KEYS = BE.OBS_KEYS


def fresh():
    BE._BUF[:] = []
    BE._STAT.update(dropped=0, err="")


def row(k, n, roi, mfe=0.0, ma=0, hist=1.0, ev=0, tag=None, sc=5, lag=0, t=None, gb=0.0):
    return {"k": k, "n": n, "t": 1000 + n if t is None else t, "tag": tag, "lag": lag, "ov": "o1", "bv": "b1",
            "roi": roi, "mfe": mfe, "gb": gb, "ma": ma, "hist": hist, "ev": ev, "sc": sc}


def hand():
    """entry, 5 candles, exit. ROI net: 2, 5, 8 (peak), 6, 3, then the trade ends at -2."""
    rows = [row("E", 0, -1.0, 0.0, 0, 1.0, 0, None, 5)]
    spec = [(1, 2.0, 3.0, 0, 1.0, 0, "S"), (2, 5.0, 6.0, 0, 1.0, 0, "S"), (3, 8.0, 9.0, 0, 0.8, 0, "S"),
            (4, 6.0, 9.0, 1, -0.5, 0, "W"), (5, 3.0, 9.0, 2, -1.0, 1, "W")]
    for n, roi, mfe, ma, hist, ev, tag in spec:
        rows.append(row("O", n, roi, mfe, ma, hist, ev, tag))
    rows.append(row("X", 6, -2.0, 9.0, None, -1.2, 0, "sl", None))
    return rows


TR = {"id": "T1", "t": 5, "sym": "AAAUSDT", "tf": "5m", "d": 1, "net": -2.0, "mfe": 9.0, "giveback": 11.0, "bv": "b1"}


# ---------------------------------------------------------------- 1. the numbers
def test_journey_hand_calculation():
    j, outs = BL.journey_of(TR, hand())
    exp = {"flags": "full", "n_rows": 5, "first_n": 1, "exit_n": 6, "exit_why": "sl", "net": -2.0, "mfe": 9.0, "gb": 11.0, "mfe_n": 3,
           "peak_n": 3, "peak_roi": 8.0, "gb_peak": 10.0, "hist_n": 4, "hist_roi": 6.0, "weak_n": 4, "weak_roi": 6.0, "weak_st": "W",
           "ev_n": 5, "ev_roi": 3.0, "mom_n": 4, "mom_roi": 6.0, "v": "j1"}
    for k, v in exp.items():
        assert j[k] == v, (k, j[k], v)
    assert set(j) == set(TA.JCOLS)
    assert len(outs) == 5 and all(set(o) == set(TA.OCOLS) for o in outs)
    o3 = [o for o in outs if o["n"] == 3][0]
    assert (o3["st"], o3["roi"], o3["fin"], o3["max_after"], o3["min_after"], o3["bars_left"]) == ("S", 8.0, -2.0, 6.0, -2.0, 3)
    o5 = [o for o in outs if o["n"] == 5][0]
    assert (o5["max_after"], o5["min_after"], o5["bars_left"]) == (-2.0, -2.0, 1)


def test_mfe_candle_uses_candles_since_best():
    rows = hand()
    for r in rows:                                   # the best price was made one candle BEFORE the closed candle that first showed it
        if r["k"] == "O" and r["n"] == 3:
            r["ma"] = 1
    assert BL.journey_of(TR, rows)[0]["mfe_n"] == 2


def test_a_trade_that_never_made_profit_has_no_mfe_candle():
    rows = [row("E", 0, -1.0), row("O", 1, -3.0, 0.0, 1, -1.0, 0, "T"), row("X", 2, -4.0, 0.0, None, -1.0, 0, "sl", None)]
    j, outs = BL.journey_of(dict(TR, net=-4.0, mfe=0.0, giveback=0.0), rows)
    assert j["mfe_n"] is None and j["peak_n"] == 1 and j["gb_peak"] == 1.0 and j["weak_n"] is None and j["hist_n"] == 1


# ---------------------------------------------------------------- 2. no look-ahead
def test_markers_depend_only_on_rows_up_to_that_candle():
    Os = [r for r in hand() if r["k"] == "O"]
    full = BL._markers(Os)
    for cut in range(1, len(Os) + 1):
        pref = BL._markers(Os[:cut])
        last_n = Os[cut - 1]["n"]
        for name in ("hist", "weak", "ev"):
            exp = full[name] if full[name] and full[name][0] <= last_n else None
            assert pref[name] == exp, (cut, name, pref[name], exp)


def test_poisoned_future_changes_nothing_that_was_known_before():
    clean = hand()
    Os = [r for r in clean if r["k"] == "O"]
    for cut in range(1, len(Os)):
        pois = copy.deepcopy(clean)
        for r in pois:
            if r["k"] in ("O", "X") and r["n"] > Os[cut - 1]["n"]:
                r.update(roi=999.0, hist=-9.0, ev=7, tag="R", sc=0, mfe=999.0)
        before = BL._markers(Os[:cut])
        after = BL._markers([r for r in pois if r["k"] == "O"])
        for name in ("hist", "weak", "ev"):
            if before[name] is not None:
                assert after[name] == before[name], (cut, name)
        _, oc = BL.journey_of(TR, clean)
        _, op = BL.journey_of(TR, pois)
        for a, b in zip(oc[:cut], op[:cut]):             # what the Brain said and saw AT the candle is its own row, never the future
            assert (a["n"], a["t"], a["st"], a["roi"], a["sc"]) == (b["n"], b["t"], b["st"], b["roi"], b["sc"])


# ---------------------------------------------------------------- 3. missing data is flagged, never guessed
def test_flags_for_gaps_late_start_missing_ends_and_no_rows():
    rows = [r for r in hand() if not (r["k"] == "O" and r["n"] == 3)]
    assert BL.journey_of(TR, rows)[0]["flags"] == "gaps:1"
    rows = [r for r in hand() if not (r["k"] == "O" and r["n"] < 3)]
    j = BL.journey_of(TR, rows)[0]
    assert "late:2" in j["flags"] and j["first_n"] == 3
    rows = [r for r in hand() if r["k"] != "E"]
    assert BL.journey_of(TR, rows)[0]["flags"] == "no_entry"
    rows = [r for r in hand() if r["k"] != "X"]
    j, outs = BL.journey_of(TR, rows)
    assert j["flags"] == "no_exit" and outs == [] and j["exit_n"] is None and j["net"] == -2.0         # no exit row: no outcome rows, nothing guessed
    j, outs = BL.journey_of(TR, [])
    assert j["flags"] == "no_obs" and outs == [] and j["net"] == -2.0 and j["mfe"] == 9.0 and j["peak_n"] is None
    rows = hand()
    rows[3]["lag"] = 7
    assert "lag:7" in BL.journey_of(TR, rows)[0]["flags"]
    assert "net_diff" in BL.journey_of(dict(TR, net=5.0), hand())[0]["flags"]
    j, _ = BL.journey_of(dict(TR, net=None, mfe=None, giveback=None), hand())              # result of record missing: the exit row is used
    assert j["net"] == -2.0 and j["mfe"] == 9.0


def test_odd_numbers_never_raise():
    rows = [row("E", 0, None), row("O", 1, None, None, None, None, None, None, None), row("X", 2, None)]
    j, outs = BL.journey_of(dict(TR, net=None), rows)
    assert j["id"] == "T1" and outs == []


# ---------------------------------------------------------------- 4. real pipeline: market run -> archive -> journeys
def _market(base, seed=23):
    fresh()
    d = TE._run_market(seed, "5m", step=1)
    assert TA.save_dual(d, {}, base=base) is True
    return d


def test_real_run_journeys_match_the_archive_and_are_idempotent():
    base = tempfile.mkdtemp()
    d = _market(base)
    con = sqlite3.connect(os.path.join(base, "dual_archive.db"))
    closed = con.execute("SELECT COUNT(*) FROM trades WHERE status='closed'").fetchone()[0]
    r = BL.step(base, limit=100000)
    assert r["err"] == "" and r["new"] == closed and closed > 5, (r, closed)
    bc = sqlite3.connect(os.path.join(base, "brain_archive.db"))
    assert bc.execute("SELECT COUNT(*) FROM journey").fetchone()[0] == closed
    full = bc.execute("SELECT COUNT(*) FROM journey WHERE flags='full'").fetchone()[0]
    assert full >= 1
    for jid, net, n_rows in bc.execute("SELECT id, net, n_rows FROM journey WHERE flags='full'"):
        assert con.execute("SELECT net FROM trades WHERE id=?", (jid,)).fetchone()[0] == net
        assert bc.execute("SELECT COUNT(*) FROM call_out WHERE id=?", (jid,)).fetchone()[0] == n_rows      # every closed candle became a call row
    for jid, in bc.execute("SELECT id FROM journey WHERE flags LIKE '%no_entry%' OR flags LIKE '%no_obs%'"):
        assert bc.execute("SELECT COUNT(*) FROM call_out WHERE id=?", (jid,)).fetchone()[0] >= 0
    print("   %d closed trades -> %d journeys (%d complete), %d call rows" % (closed, closed, full, bc.execute("SELECT COUNT(*) FROM call_out").fetchone()[0]))
    assert BL.step(base)["new"] == 0                                                          # nothing is done twice
    v = BL.view_summary(base)
    assert v["journeys"] == closed and v["full"] == full


def test_a_new_version_appends_and_old_rows_never_change():
    base = tempfile.mkdtemp()
    _market(base, seed=31)
    BL.step(base, limit=100000)
    bc = sqlite3.connect(os.path.join(base, "brain_archive.db"))
    old_j = bc.execute("SELECT * FROM journey ORDER BY id").fetchall()
    old_o = bc.execute("SELECT * FROM call_out ORDER BY id, t").fetchall()
    keep = BL.LEARN_VERSION
    try:
        BL.LEARN_VERSION = "j2"
        assert BL.step(base, limit=100000)["new"] == len(old_j)
    finally:
        BL.LEARN_VERSION = keep
    assert bc.execute("SELECT COUNT(*) FROM journey").fetchone()[0] == 2 * len(old_j)
    assert bc.execute("SELECT * FROM journey WHERE v='j1' ORDER BY id").fetchall() == old_j
    assert bc.execute("SELECT * FROM call_out WHERE v='j1' ORDER BY id, t").fetchall() == old_o
    assert BL.view_summary(base)["journeys"] == len(old_j)                                  # the view counts only the running version


def test_saving_the_same_journey_again_never_overwrites():
    base = tempfile.mkdtemp()
    j, outs = BL.journey_of(TR, hand())
    j["saved"] = 1.0
    assert TA.save_learn([tuple(j[c] for c in TA.JCOLS)], [tuple(o[c] for c in TA.OCOLS) for o in outs], base)
    j2 = dict(j, net=99.0)
    assert TA.save_learn([tuple(j2[c] for c in TA.JCOLS)], [], base)
    bc = sqlite3.connect(os.path.join(base, "brain_archive.db"))
    assert bc.execute("SELECT net FROM journey WHERE id='T1'").fetchone()[0] == -2.0


def test_old_trades_without_candle_rows_keep_their_result_only():
    base = tempfile.mkdtemp()
    con = sqlite3.connect(os.path.join(base, "dual_archive.db"))                              # layout from before Batch 2 / 4a: no obs, no mfe column
    con.executescript("""CREATE TABLE trades (id TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, side INTEGER, src TEXT, status TEXT, net REAL,
      exit_rule TEXT, mode TEXT, saved REAL, js TEXT); CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
      INSERT INTO trades VALUES ('OLD', 1, 'XUSDT', '5m', 1, 'Z', 'closed', 3.5, 'x', 'm', 1.0, '{}');
      INSERT INTO trades VALUES ('SKP', 2, 'XUSDT', '5m', 1, 'Z', 'skipped_done', -3.0, 'x', 'm', 1.0, '{}');
      INSERT INTO trades VALUES ('OPN', 3, 'XUSDT', '5m', 1, 'Z', 'open', NULL, 'x', 'm', 1.0, '{}');""")
    con.commit(); con.close()
    r = BL.step(base)
    assert r["err"] == "" and r["new"] == 1                                                   # only the finished taken trade
    bc = sqlite3.connect(os.path.join(base, "brain_archive.db"))
    assert bc.execute("SELECT flags, net, mfe, n_rows FROM journey WHERE id='OLD'").fetchone() == ("no_obs", 3.5, None, 0)
    assert bc.execute("SELECT COUNT(*) FROM call_out").fetchone()[0] == 0


# ---------------------------------------------------------------- 5. read-only, also while Dual writes
def test_dual_archive_is_opened_read_only_and_not_changed():
    base = tempfile.mkdtemp()
    assert TA.open_dual_ro(base) is None and BL.step(base) == {"new": 0, "err": ""}          # no file yet: nothing happens, nothing is created
    assert not os.path.exists(os.path.join(base, "dual_archive.db"))
    _market(base)
    p = os.path.join(base, "dual_archive.db")
    con = TA.open_dual_ro(base)
    try:
        for sql in ("INSERT INTO meta(k, v) VALUES('x','y')", "CREATE TABLE zz (a INT)", "UPDATE trades SET net = 0"):
            try:
                con.execute(sql)
                raise AssertionError("write was allowed: " + sql)
            except sqlite3.OperationalError:
                pass
    finally:
        con.close()
    h = lambda: hashlib.sha256(open(p, "rb").read()).hexdigest()
    before = h()
    assert BL.step(base, limit=100000)["err"] == ""
    assert h() == before                                                                      # not one byte of the Dual archive changed


WRITER = r'''
import json, sqlite3, sys, time
base, n_trades, keys = sys.argv[1], int(sys.argv[2]), json.loads(sys.argv[3])
con = sqlite3.connect(base + "/dual_archive.db", timeout=20)
con.execute("PRAGMA journal_mode=WAL"); con.execute("PRAGMA synchronous=NORMAL")
K = {k: i for i, k in enumerate(keys)}
def f(roi, mfe, gb, ma):
    v = [0.5] * len(keys)
    v[K["roi"]], v[K["mfe"]], v[K["gb"]], v[K["ma"]], v[K["hist"]], v[K["ev"]], v[K["sc"]] = roi, mfe, gb, ma, 0.4, 0, 5
    return json.dumps(v)
con.execute("INSERT OR IGNORE INTO meta(k, v) VALUES('obs_keys_o1', ?)", (json.dumps(keys),))
con.commit()
for i in range(n_trades):
    tid = "W%04d" % i
    with con:                                   # like save_dual: the trade and ALL its rows in ONE transaction
        con.execute("INSERT INTO trades(id, t, sym, tf, side, src, status, net, exit_rule, mode, saved, js, mfe, giveback, brain_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tid, i, "WWWUSDT", "5m", 1, "Z", "closed", -2.0, "x", "m", 0.0, "{}", 9.0, 11.0, "b1"))
        con.execute("INSERT INTO obs(id,t,k,n,sym,tf,d,v,bv,tag,lag,f) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (tid, 1000 * i, "E", 0, "WWWUSDT", "5m", 1, "o1", "b1", None, 1, f(-1.0, 0.0, 0.0, 0)))
        for n in range(1, 5):
            con.execute("INSERT INTO obs(id,t,k,n,sym,tf,d,v,bv,tag,lag,f) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (tid, 1000 * i + n, "O", n, "WWWUSDT", "5m", 1, "o1", "b1", "S", 0, f(2.0 * n, 2.0 * n + 1, 0.0, 0)))
        con.execute("INSERT INTO obs(id,t,k,n,sym,tf,d,v,bv,tag,lag,f) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (tid, 1000 * i + 5, "X", 5, "WWWUSDT", "5m", 1, "o1", "b1", "sl", 0, f(-2.0, 9.0, 11.0, None)))
    time.sleep(0.004)
con.close()
'''


def test_reading_while_the_dual_worker_keeps_writing():
    base = tempfile.mkdtemp()
    TA._open(TA.DUAL_DB, TA._DUAL_SQL, base).close()                                          # the schema the Dual worker really uses
    n = 120
    t0 = time.time()
    p = subprocess.Popen([sys.executable, "-c", WRITER, base, str(n), json.dumps(list(KEYS))])
    errs, steps, new = [], 0, 0
    while p.poll() is None:
        r = BL.step(base, limit=7)
        steps += 1
        new += r["new"]
        if r["err"]:
            errs.append(r["err"])
        time.sleep(0.02)
    assert p.returncode == 0
    while True:
        r = BL.step(base, limit=1000)
        new += r["new"]
        if r["err"]:
            errs.append(r["err"])
        if r["new"] == 0:
            break
    print("   writer %.1f s, %d reader steps while it wrote, %d journeys" % (time.time() - t0, steps, new))
    assert errs == [], errs[:3]
    assert new == n
    bc = sqlite3.connect(os.path.join(base, "brain_archive.db"))
    assert bc.execute("SELECT COUNT(*) FROM journey").fetchone()[0] == n
    assert bc.execute("SELECT COUNT(*) FROM journey WHERE flags='full'").fetchone()[0] == n   # never a half-written trade: all rows arrive with the trade
    assert bc.execute("SELECT COUNT(*) FROM call_out").fetchone()[0] == 4 * n
    assert bc.execute("SELECT mfe_n, peak_n, net, gb_peak FROM journey WHERE id='W0007'").fetchone() == (4, 4, -2.0, 10.0)
    assert steps >= 3                                                                          # the reader really ran during the writing


# ---------------------------------------------------------------- 6. crash safety
def test_crashes_are_caught_and_remembered_never_raised():
    bad = tempfile.NamedTemporaryFile(delete=False).name                                      # a FILE where the folder should be
    r = BL.step(bad)
    assert r["new"] == 0 and r["err"]
    assert BL.view_summary(bad)["status"] == "collecting"


def test_damaged_and_unknown_rows_are_flagged_not_guessed():
    base = tempfile.mkdtemp()
    _market(base, seed=11)
    con = sqlite3.connect(os.path.join(base, "dual_archive.db"))
    tid = con.execute("SELECT id FROM trades WHERE status='closed' AND id IN (SELECT id FROM obs WHERE k='X') AND id IN (SELECT id FROM obs WHERE k='E') "
                      "AND id IN (SELECT id FROM obs WHERE k='O' AND n=1) ORDER BY t LIMIT 1").fetchone()[0]
    con.execute("UPDATE obs SET f = 'not json' WHERE id = ? AND k = 'O' AND n = 1", (tid,))
    con.execute("UPDATE obs SET f = '[1,2]' WHERE id = ? AND k = 'X'", (tid,))
    con.execute("UPDATE obs SET v = 'o9' WHERE id = ? AND k = 'E'", (tid,))                  # a layout this code does not know
    con.commit(); con.close()
    assert BL.step(base, limit=100000)["err"] == ""
    bc = sqlite3.connect(os.path.join(base, "brain_archive.db"))
    flags = bc.execute("SELECT flags FROM journey WHERE id = ?", (tid,)).fetchone()[0]
    assert "bad_rows:2" in flags and "layout:1" in flags and "no_exit" in flags, flags
    assert bc.execute("SELECT COUNT(*) FROM call_out WHERE id = ?", (tid,)).fetchone()[0] == 0   # no exit row: no outcomes invented


def test_a_failed_save_marks_nothing_done_and_the_next_cycle_retries():
    base = tempfile.mkdtemp()
    _market(base, seed=23)
    real = TA.save_learn
    try:
        TA.save_learn = lambda *a, **k: False
        r = BL.step(base, limit=100000)
        assert r["new"] == 0 and r["err"]
    finally:
        TA.save_learn = real
    r = BL.step(base, limit=100000)
    assert r["err"] == "" and r["new"] > 5
    assert BL.step(base)["new"] == 0


def test_limit_keeps_each_cycle_small():
    base = tempfile.mkdtemp()
    _market(base, seed=23)
    total = sqlite3.connect(os.path.join(base, "dual_archive.db")).execute("SELECT COUNT(*) FROM trades WHERE status='closed'").fetchone()[0]
    assert total > BL.MAX_PER_STEP // 4
    assert BL.step(base, limit=3)["new"] == 3 and BL.step(base, limit=3)["new"] == 3
    assert BL.view_summary(base)["journeys"] == 6


def test_cost_of_one_cycle():
    base = tempfile.mkdtemp()
    con = TA._open(TA.DUAL_DB, TA._DUAL_SQL, base)
    con.execute("INSERT INTO meta(k, v) VALUES('obs_keys_o1', ?)", (json.dumps(list(KEYS)),))
    f = json.dumps([0.5] * len(KEYS))
    with con:
        for i in range(BL.MAX_PER_STEP):
            tid = "C%03d" % i
            con.execute("INSERT INTO trades(id, t, sym, tf, side, src, status, net, exit_rule, mode, saved, js) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (tid, i, "CCCUSDT", "5m", 1, "Z", "closed", 1.0, "x", "m", 0.0, "{}"))
            con.executemany("INSERT INTO obs(id,t,k,n,sym,tf,d,v,bv,tag,lag,f) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            [(tid, 1000 * i + n, "X" if n == 80 else "O", n, "CCCUSDT", "5m", 1, "o1", "b1", "S", 0, f) for n in range(1, 81)])
    con.close()
    t0 = time.perf_counter()
    r = BL.step(base)
    ms = (time.perf_counter() - t0) * 1000.0
    print("   one cycle: %d trades x 80 rows -> %.0f ms" % (r["new"], ms))
    assert r["new"] == BL.MAX_PER_STEP and ms < 3000.0, ms


# ---------------------------------------------------------------- 7. no verdicts, nothing decides from it, trading untouched
def test_the_view_has_facts_only_and_says_not_enough_data():
    v = BL.view_summary(tempfile.mkdtemp())
    assert v["journeys"] == 0 and "NOT ENOUGH DATA" in v["text"] and v["status"] == "collecting"
    assert not any(w in " ".join(v) for w in ("verdict", "recommend", "confidence", "hold", "protect", "edge", "score"))


def test_source_guards():
    for f in ("brain_learn.py", "trade_archive.py"):
        src = open(os.path.join(HERE, f)).read()
        assert re.search(r"\b(delete\s+from|drop\s+table|truncate|vacuum)\b", src, re.I) is None, f
    src = open(os.path.join(HERE, "brain_learn.py")).read()
    assert re.search(r"\b(insert|update|replace)\s", src.replace("INSERT OR IGNORE", ""), re.I) is None, "brain_learn writes only through trade_archive"
    assert "sqlite3.connect" not in src and "import sqlite3" not in src and "DUAL_DB" not in src      # it opens no database itself: only TA.open_dual_ro (read-only)
    ta = open(os.path.join(HERE, "trade_archive.py")).read()
    assert "mode=ro" in ta.split("def open_dual_ro")[1].split("def learn_done_ids")[0]
    for f in ("strategy.py", "paper_trader.py", "market_ws.py", "tag_lab.py", "filter_lab.py", "brain_own.py", "brain_exit.py", "brain_exit_pick.py",
              "brain_tp_hold.py", "brain_ready.py", "brain_retest.py", "brain_follow.py", "dual_tp_ext.py", "dual_lab.py", "brain_edge.py", "brain_meta.py"):
        p = os.path.join(HERE, f) if os.path.exists(os.path.join(HERE, f)) else os.path.join(HERE, "recovered_bot", f)
        if os.path.exists(p):
            assert "brain_learn" not in open(p).read(), f                                      # nothing that decides or trades can read the journeys
    sb = open(os.path.join(HERE, "smart_brain.py")).read()
    assert set(re.findall(r"\bBLN\.(\w+)", sb)) == {"step", "view_summary"}
    assert set(re.findall(r"\bTA\.(\w+)", src)) <= {"JCOLS", "OCOLS", "open_dual_ro", "learn_done_ids", "save_learn", "learn_counts", "_L"}


def test_trading_output_identical():
    TE.test_process_results_identical_with_and_without_the_hook()                             # same golden sha256 as before Batch 3a / 4a


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")
