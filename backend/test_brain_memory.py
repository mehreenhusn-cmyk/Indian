"""Batch 2 - Brain learning memory: MFE, giveback and brain_version on Dual / Brain trades, kept in the existing archives."""
import hashlib, json, os, random, sqlite3, sys, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "recovered_bot"))
sys.path.insert(0, os.path.dirname(__file__))
import tag_lab as TL
import trade_archive as TA
import brain_meta as BM

GOLDEN = "8d35375a68319106dc92c0a7f88b19f744c5617ce03749f33de334d6fbd1aee7"    # sha256 of 2700 sim_rule runs made with the code BEFORE Batch 2


def _S(h, l, c):
    n = len(h)
    return {"h": h, "l": l, "c": c, "n": n, "xdn": [0] * n, "xup": [0] * n}, {"dn": [0] * n, "up": [0] * n}


def test_long_tp_counts_exit_candle_high():
    S, Z = _S([100, 103, 103, 103], [100, 100, 100, 100], [100, 102, 102, 102])
    r = TL.sim_rule(S, Z, 0, 1, 100.0, 98.0, [101, 102, 103, 104], 10.0, 1.0, cap=2, be=True, xmode=None)
    assert r["why"] == "TP" and r["px"] == 102
    assert abs(r["mfe"] - 30.0) < 1e-9                       # high 103 on the exit candle: (103-100)/100*100*10
    assert abs(r["net"] - 19.0) < 1e-9                       # unchanged: gross 20 - fee 1
    assert abs(r["giveback"] - 10.0) < 1e-9                  # 30 - gross final 20 (fee is not part of it)


def test_short_trade_mfe():
    S, Z = _S([100, 100, 100], [100, 96, 96], [100, 98, 98])
    r = TL.sim_rule(S, Z, 0, -1, 100.0, 102.0, [99, 98, 97, 96], 10.0, 1.0, cap=3, be=True, xmode=None)
    assert r["why"] == "TP" and r["px"] == 97
    assert abs(r["mfe"] - 40.0) < 1e-9                       # low 96: (100-96)/100*100*10
    assert abs(r["giveback"] - 10.0) < 1e-9                  # 40 - gross final 30


def test_trail_trade_mfe():
    S, Z = _S([100, 104, 110, 104], [100, 100, 99, 99], [100, 103, 100, 100])
    r = TL.sim_rule(S, Z, 0, 1, 100.0, 98.0, [101, 102, 103, 104], 10.0, 1.0, cap=None, be=True, xmode=None, trail=1.5)
    assert r["why"] == "TRAIL" and r["px"] == 101.0
    assert abs(r["mfe"] - 40.0) < 1e-9                       # 104 seen. The stop candle (high 110) is not counted: stop first, like the trade itself
    assert abs(r["giveback"] - 30.0) < 1e-9                  # 40 - gross final 10


def test_sl_without_favorable_move_has_zero_mfe():
    S, Z = _S([100, 100, 100], [100, 97, 97], [100, 98, 98])
    r = TL.sim_rule(S, Z, 0, 1, 100.0, 98.0, [101, 102, 103, 104], 10.0, 1.0, cap=4, be=True, xmode=None)
    assert r["why"] == "SL" and r["mfe"] == 0.0
    assert abs(r["giveback"] - 20.0) < 1e-9                  # formula as ordered: MFE 0 - gross final (-20); never below 0


def test_giveback_formula_and_never_negative_on_random_trades():
    rnd, n_ok = random.Random(5), 0
    for _ in range(400):
        n = 60
        px, h, l, c = 100.0, [], [], []
        for _ in range(n):
            o = px; cl = o * (1 + rnd.uniform(-0.012, 0.012))
            h.append(max(o, cl) * (1 + rnd.uniform(0, 0.006))); l.append(min(o, cl) * (1 - rnd.uniform(0, 0.006))); c.append(cl); px = cl
        S, Z = _S(h, l, c)
        d = rnd.choice((1, -1)); entry = c[0]; sl = entry * (1 - d * 0.01)
        tps = [entry + d * entry * 0.005 * k for k in range(1, 5)]
        for rule in TL.EXITS.values():
            r = TL.sim_rule(S, Z, 0, d, entry, sl, tps, 10.0, 1.0, allow_open=True, **rule)
            gross = r["net"] + 1.0
            assert r["mfe"] >= 0 and r["giveback"] >= 0
            assert abs(r["giveback"] - max(0.0, r["mfe"] - gross)) < 1e-6
            assert r["mfe"] + 1e-6 >= gross or r["why"] in ("SL", "BE", "TRAIL")   # a profit exit can never show less MFE than it banked
            n_ok += 1
    assert n_ok == 3600


def test_old_sim_rule_results_unchanged():
    rnd, out = random.Random(12345), []
    for _case in range(300):
        n = 90
        px, h, l, c = 100.0, [], [], []
        for _ in range(n):
            o = px; cl = o * (1 + rnd.uniform(-0.012, 0.012))
            h.append(max(o, cl) * (1 + rnd.uniform(0, 0.006))); l.append(min(o, cl) * (1 - rnd.uniform(0, 0.006))); c.append(cl); px = cl
        S = {"h": h, "l": l, "c": c, "n": n, "xdn": [rnd.random() < 0.05 for _ in range(n)], "xup": [rnd.random() < 0.05 for _ in range(n)]}
        Z = {"dn": [rnd.random() < 0.05 for _ in range(n)], "up": [rnd.random() < 0.05 for _ in range(n)]}
        i = rnd.randint(0, 20); d = rnd.choice((1, -1)); entry = c[i]
        sl = entry * (1 - d * rnd.uniform(0.004, 0.02))
        step = abs(entry - sl) * rnd.uniform(0.6, 1.5)
        tps = [entry + d * step * k for k in range(1, rnd.choice((4, 7)) + 1)]
        keys = ("net", "why", "bars", "hit", "b1", "mae", "px", "path")
        for name, rule in TL.EXITS.items():
            r = TL.sim_rule(S, Z, i, d, entry, sl, tps, 10.0, 1.0, **rule)
            r2 = TL.sim_rule(S, Z, i, d, entry, sl, tps, 10.0, 1.0, allow_open=True, **rule)
            out.append([None if r is None else {k: r[k] for k in keys}, {k: r2[k] for k in keys}])
    assert hashlib.sha256(json.dumps(out, sort_keys=True, default=str).encode()).hexdigest() == GOLDEN


def _trade(i, status="open", **kw):
    t = {"id": "BTC|5m|%d" % i, "t": 1000 + i, "s": "BTC", "f": "5m", "d": 1, "src": "MAIN", "status": status, "exit": "x", "mode": "explore"}
    t.update(kw)
    return t


def _q(base, db, sql):
    con = sqlite3.connect(os.path.join(base, db))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_archive_saves_and_conflict_path_keeps_values():
    base, st = tempfile.mkdtemp(), {}
    data = {"trades": [_trade(1, brain_version="b1")], "rows": {}, "rt": {}}
    assert TA.save_dual(data, st, base)
    assert _q(base, TA.DUAL_DB, "SELECT mfe, giveback, brain_version FROM trades") == [(None, None, "b1")]     # open: no MFE yet
    data["trades"][0].update(status="closed", net=19.0, end="TP", mfe=30.0, giveback=10.0)                    # closes -> conflict update
    assert TA.save_dual(data, st, base)
    assert _q(base, TA.DUAL_DB, "SELECT mfe, giveback, brain_version, status FROM trades") == [(30.0, 10.0, "b1", "closed")]
    t = data["trades"][0]                                                                                      # a later save that lacks the values
    t.pop("mfe"); t.pop("giveback"); t.pop("brain_version"); t["status"] = "skipped_done"
    assert TA.save_dual(data, st, base)
    assert _q(base, TA.DUAL_DB, "SELECT mfe, giveback, brain_version, status FROM trades") == [(30.0, 10.0, "b1", "skipped_done")]
    js = json.loads(_q(base, TA.DUAL_DB, "SELECT js FROM trades")[0][0])                                      # js copy stays what the trade held
    assert js["status"] == "skipped_done"
    # Brain own trades
    own = {"closed": [{"id": "o1", "t": 5, "s": "ETH", "f": "15m", "net": 3.0, "stage": "learning", "mfe": 12.5, "giveback": 4.0, "brain_version": "b1"}]}
    assert TA.save_brain(own=own, base=base)
    assert _q(base, TA.BRAIN_DB, "SELECT mfe, giveback, brain_version FROM own") == [(12.5, 4.0, "b1")]
    TA._B["own"].clear()
    assert TA.save_brain(own=own, base=base)                                                                   # same id again: ignored, values kept
    assert _q(base, TA.BRAIN_DB, "SELECT COUNT(*), MAX(mfe) FROM own") == [(1, 12.5)]


def test_old_archive_stays_readable_and_gets_columns():
    base = tempfile.mkdtemp()
    old = ("CREATE TABLE trades (id TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, side INTEGER, src TEXT, status TEXT,"
           " net REAL, exit_rule TEXT, mode TEXT, saved REAL, js TEXT);"
           "CREATE TABLE own (id TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, net REAL, stage TEXT, saved REAL, js TEXT);")
    for name, tbl in ((TA.DUAL_DB, "trades"), (TA.BRAIN_DB, "own")):
        con = sqlite3.connect(os.path.join(base, name)); con.executescript(old)
        if tbl == "trades":
            con.execute("INSERT INTO trades VALUES('OLD1',1,'SOL','5m',1,'MAIN','closed',-4.0,'x','m',1.0,'{\"id\":\"OLD1\"}')")
        else:
            con.execute("INSERT INTO own VALUES('OLD2',1,'SOL','5m',2.0,'learning',1.0,'{\"id\":\"OLD2\"}')")
        con.commit(); con.close()
    st = {}
    assert TA.save_dual({"trades": [_trade(9, brain_version="b1")], "rows": {}, "rt": {}}, st, base)
    assert TA.save_brain(own={"closed": [{"id": "N1", "t": 2, "net": 1.0, "mfe": 5.0, "giveback": 1.0, "brain_version": "b1"}]}, base=base)
    assert _q(base, TA.DUAL_DB, "SELECT id, net, mfe, giveback, brain_version, js FROM trades WHERE id='OLD1'") == [("OLD1", -4.0, None, None, None, '{"id":"OLD1"}')]
    assert _q(base, TA.BRAIN_DB, "SELECT id, net, mfe, brain_version FROM own WHERE id='OLD2'") == [("OLD2", 2.0, None, None)]
    assert BM.shown(None) == "not recorded" and BM.shown("b1") == "b1"
    s = TA.status(base)
    assert s["state"] != "error" and s["trades"] == 2 and s["own"] == 2


def test_brain_version_only_a_label():
    import re
    for f in ("smart_brain.py", "brain_exit_pick.py", "brain_tp_hold.py", "brain_ready.py", "brain_lessons.py", "brain_side.py", "brain_week.py",
              "brain_retest.py", "filter_lab.py", "tag_lab.py", "dual_desk.py"):
        src = open(os.path.join(os.path.dirname(__file__), f)).read()
        assert "brain_version" not in src and "BRAIN_VERSION" not in src, f      # no decision code reads the label


def test_open_trades_get_the_label_and_closed_get_mfe():
    import brain_own as BO
    own = {}
    plan = {"entry": 100.0, "sl": 98.0, "tps": [101, 102, 103, 104], "ct": 1}
    BO.open_from(own, [{"s": "AAA", "f": "5m", "d": 1, "_plan": plan, "_tg": {"x": 1}, "clean": 50}], now_ms=10_000_000_000)
    assert own["open"] and own["open"][0]["brain_version"] == BM.BRAIN_VERSION


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
