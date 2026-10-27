"""Batch 4a - per-candle DATA COLLECTION for the Brain (observation only). Run: cd backend && python3 test_brain_obs.py
Proves: numbers are right, NO LOOK-AHEAD, one row per closed candle, the exit candle is captured, the archive keeps everything,
old data stays readable, a crash never reaches the bot, trading output is byte-identical."""
import json, os, random, re, sqlite3, sys, tempfile, time
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "recovered_bot"))
sys.path.insert(0, HERE)
import brain_edge as BE
import dual_lab as D
import filter_lab as FL
import tag_lab as TL
import trade_archive as TA
import test_brain_edge as TE
from recovered_bot import ai_ind_features as F

KEYS = BE.OBS_KEYS
K = {k: n for n, k in enumerate(KEYS)}
I0 = TE.I0


def fresh():
    BE._BUF[:] = []
    BE._STAT.update(dropped=0, err="")


def rows_of(rows, kind=None, tid=None):
    return [r for r in rows if (kind is None or r[2] == kind) and (tid is None or r[0] == tid)]


def val(row, key):
    return row[11][K[key]]


def real_series(n=460, seed=5, tf="5m"):
    cc = TE._candles(tf, n, seed)
    S = F.build(cc)
    return cc, S, TL.z_series(S)


# ---------------------------------------------------------------- 1. the numbers
def test_snapshot_matches_hand_calculation():
    n = I0 + 10
    k = n - 1
    S, Z = TE.mk(n, z={k: 1.0, k - 3: 0.4, k - 5: 0.5}, diff={k: 2.0, k - 3: 1.5}, width={k: 1.2, k - 5: 1.0},
                 e50={k: 98.0, k - 5: 97.0}, std={k: 2.0}, tsi={k: 12.0, k - 3: 10.0})
    S["sma"] = [100.0] * n
    f = BE.snapshot(S, Z, k, 1)
    assert len(f) == 18
    c, c3 = S["c"][k], S["c"][k - 3]
    exp = {"tsi": 12.0, "hist": 2.0, "hs3": 0.5, "ts3": 2.0, "z": 1.0, "zs3": 0.6, "zsm": 0.2, "zg": 0.8, "dm": round((c - 100.0) / 100.0 * 100.0, 3),
           "bw": 1.2, "wd5": 20.0, "ed": round((c - 98.0) / 2.0, 2), "es": 0.5, "sm": None, "sz": None, "ev": 0,
           "px3": round((c - c3) / c3 * 100.0, 3), "sc": 6}
    for key, v in exp.items():
        assert f[K[key]] == v, (key, f[K[key]], v)


def test_short_trade_signs_mirror():
    n = I0 + 10
    S, Z = TE.mk(n, c=lambda k: 100.0 - 0.1 * k, tsi=lambda k: -10.0, diff=lambda k: -2.0, z=lambda k: -1.0, zsma=lambda k: -0.2,
                 e50=lambda k: 110.0, zf=lambda k: -0.8, zs=lambda k: -0.5)
    S["sma"] = [100.0] * n
    f = BE.snapshot(S, Z, n - 1, -1)
    assert f[K["tsi"]] == 10.0 and f[K["hist"]] == 2.0 and f[K["z"]] == 1.0 and f[K["zsm"]] == 0.2 and f[K["zg"]] == 0.8 and f[K["sc"]] == 6, f
    assert f[K["ed"]] > 0 and f[K["dm"]] > 0 and f[K["px3"]] > 0                      # all "with trade" numbers are positive on a going-well short


def test_event_bits_for_long_and_short():
    n = I0 + 10
    k = n - 1
    S, Z = TE.mk(n)
    S["sma"] = [100.0] * n
    for key, bit in (("xdn", 1), ("dn", 2), ("wdn", 4), ("xup", 8), ("up", 16), ("wup", 32)):
        S, Z = TE.mk(n, **{key: {k: (1 if key.startswith("w") else True)}})
        S["sma"] = [100.0] * n
        assert BE.snapshot(S, Z, k, 1)[K["ev"]] == bit, key
        mirror = {1: 8, 2: 16, 4: 32, 8: 1, 16: 2, 32: 4}[bit]                             # a short sees the same events the other way round
        assert BE.snapshot(S, Z, k, -1)[K["ev"]] == mirror, key
    S, Z = TE.mk(n, xdn={k: True}, dn={k: True}, wdn={k: 1})
    S["sma"] = [100.0] * n
    assert BE.snapshot(S, Z, k, 1)[K["ev"]] == 7


# ---------------------------------------------------------------- 2. NO LOOK-AHEAD
class Guard(list):
    """A list that refuses to give any value after index `limit` (the closed candle the row belongs to)."""
    def __init__(self, a, limit):
        super().__init__(a)
        self.limit = limit

    def __getitem__(self, i):
        if isinstance(i, slice) or i < 0 or i > self.limit:
            raise AssertionError("LOOK-AHEAD: index %r read, the row belongs to candle %d" % (i, self.limit))
        return list.__getitem__(self, i)


def _guarded(S, Z, k):
    G = {key: (Guard(v, k) if isinstance(v, list) else v) for key, v in S.items()}
    GZ = {key: (Guard(v, k + 1 if key in ("pm", "pz") else k) if isinstance(v, list) else v) for key, v in Z.items()}   # pm / pz = prefix sums: [k+1] = total up to k
    return G, GZ


def test_snapshot_reads_only_candles_up_to_k():
    cc, S, Z = real_series()
    for k in (260, 333, 459):
        for d in (1, -1):
            G, GZ = _guarded(S, Z, k)
            assert BE.snapshot(G, GZ, k, d) == BE.snapshot(S, Z, k, d)                      # no AssertionError = never touched a later candle


def test_future_candles_cannot_change_a_row():
    cc, S, Z = real_series(n=460, seed=9)
    rnd = random.Random(1)
    for k in (270, 410, 440):
        for d in (1, -1):
            cut = cc[:k + 1]
            S1 = F.build(cut)
            poisoned = cut + [{"timestamp": 0, "open": 1.0, "high": 1e6 * rnd.random() + 2, "low": 0.5, "close": 1e5 * rnd.random() + 1, "volume": 1.0} for _ in range(40)]
            S2 = F.build(poisoned)
            a = BE.snapshot(S1, TL.z_series(S1), k, d)
            b = BE.snapshot(S2, TL.z_series(S2), k, d)
            c = BE.snapshot(S, Z, k, d)                                                     # the real, longer window
            assert a == b == c, (k, d)
            assert None not in a or k < 400                                                 # a warmed-up candle has every number (Z-SMA needs ~400 candles)


def test_entry_exit_and_open_rows_use_only_their_own_candle():
    """E row is computed one candle after the entry, X row after the exit: both must equal a snapshot made with data that ends at THEIR candle."""
    cc, S, Z = real_series(n=420, seed=7)
    d, i = 1, 300
    entry = S["c"][i]
    tps = [entry * (1 + 0.004 * q) for q in (1, 2, 3, 4)]
    tr = {"id": "R1", "s": "AAAUSDT", "f": "5m", "d": d, "status": "open", "take": True, "entry": entry, "sl": entry * 0.99, "ct": S["t"][i]}
    fresh()
    for j in range(i + 1, 330):                                                             # one observation per new closed candle, like the bot
        Sj = F.build(cc[:j + 1])
        Zj = TL.z_series(Sj)
        lv = TL.sim_rule(Sj, Zj, i, d, entry, tr["sl"], tps, 10.0, 1.0, allow_open=True)
        if lv is None or lv.get("why") != "OPEN":
            break
        BE.observe(tr, Sj, Zj, i, lv, 10.0, 1.0)
    rows = BE.pending()
    e = rows_of(rows, "E")
    assert len(e) == 1 and e[0][1] == S["t"][i] and e[0][3] == 0
    Si = F.build(cc[:i + 1])
    assert e[0][11][:18] == BE.snapshot(Si, TL.z_series(Si), i, d)                           # entry numbers = what was known AT the entry candle
    for r in rows_of(rows, "O"):
        j = [x for x in range(len(S["t"])) if S["t"][x] == r[1]][0]
        Sj = F.build(cc[:j + 1])
        assert r[11][:18] == BE.snapshot(Sj, TL.z_series(Sj), j, d) and r[10] == 0
    # exit row
    Sx = F.build(cc[:331])
    Zx = TL.z_series(Sx)
    r = {"net": 4.0, "mfe": 12.0, "giveback": 8.0, "bars": 20, "why": "TP"}
    tr["status"] = "closed"
    fresh()
    BE.exit_obs(tr, Sx, Zx, i, r, 10.0, 1.0)
    x = BE.pending()[0]
    assert x[2] == "X" and x[1] == Sx["t"][i + 20] and x[3] == 20 and x[9] == "TP" and x[10] == 330 - (i + 20), x[:11]   # lag = candles between the exit candle and the newest one
    Sc = F.build(cc[:i + 21])
    assert x[11][:18] == BE.snapshot(Sc, TL.z_series(Sc), i + 20, d)
    assert x[11][K["roi"]] == 4.0 and x[11][K["mfe"]] == 12.0 and x[11][K["gb"]] == 8.0


# ---------------------------------------------------------------- 3. rows while the bot runs
def test_rows_follow_the_trades_in_a_fake_market():
    fresh()
    d = TE._run_market(11, "5m", step=1)
    rows = BE.pending()
    assert rows and all(len(r[11]) == len(KEYS) for r in rows)
    assert len({(r[0], r[1], r[2]) for r in rows}) == len(rows)                              # never two rows for the same candle and kind
    ids = {t["id"]: t for t in d["trades"]}
    assert {r[0] for r in rows} <= {i for i, t in ids.items() if t.get("take")}               # only taken trades
    kinds = {r[2] for r in rows}
    assert kinds == {"E", "O", "X"}, kinds
    nx = 0
    for tid, t in ids.items():
        rr = rows_of(rows, tid=tid)
        if not rr:
            continue
        if t["status"] == "closed":
            xs = rows_of(rr, "X")
            assert len(xs) == 1, (tid, len(xs))
            x = xs[0]
            assert abs(val(x, "roi") - t["net"]) < 0.06 and abs(val(x, "mfe") - t["mfe"]) < 0.06 and abs(val(x, "gb") - t["giveback"]) < 0.06
            assert x[9] == t["end"] and x[1] == t["xt"] and x[3] == (t["xt"] - t["ct"]) // FL.TF_MS["5m"]     # the exit candle itself
            nx += 1
        else:
            assert not rows_of(rr, "X")
        e = t.get("edge")
        if e and len(e["hs"]) < BE.MAX_HIST and e["f0"] == 1:
            assert len(rows_of(rr, "O")) == len(e["hs"]) and len(rows_of(rr, "E")) == 1 and rows_of(rr, "E")[0][1] == t["ct"]
        os_ = rows_of(rr, "O")
        assert [r[1] for r in os_] == sorted(r[1] for r in os_) and [r[3] for r in os_] == sorted(r[3] for r in os_)
        assert all(r[10] == 0 for r in os_) and all(r[7] == "o1" and r[8] == "b1" and r[6] == t["d"] for r in rr)
    assert nx > 5, nx


def test_same_candle_twice_gives_one_row_and_old_b3a_trades_get_no_entry_row():
    S, Z = TE.mk(I0 + 12)
    S["sma"] = [100.0] * S["n"]
    fresh()
    tr = TE.trade(S)
    BE.observe(tr, S, Z, I0, TE.lv_of(S, I0, 1), 10.0, 1.0)
    BE.observe(tr, S, Z, I0, TE.lv_of(S, I0, 1), 10.0, 1.0)                                 # the 6-8 s loop sees the same candle again
    assert [r[2] for r in BE.pending()] == ["E", "O"]
    fresh()
    old = TE.trade(S)
    old["edge"] = {"v": "e1", "lt": S["t"][I0 + 3], "n": 3, "f0": 1, "hs": "NTT", "hc": "666", "hr": [1, 2, 3], "hz": [1, 1, 1]}     # observed before B4a
    BE.observe(old, S, Z, I0, TE.lv_of(S, I0, 1), 10.0, 1.0)
    assert [r[2] for r in BE.pending()] == ["O"]                                           # nothing is back-filled


def test_boot_replay_skipped_trades_and_open_trades_get_no_exit_row():
    names = list(TL.EXITS.keys())
    cc = TE._candles("5m", 900, 11)
    fresh()
    d = {"rows": {}, "trades": [], "seen": {}, "boot": {}, "fetched": {}}
    for cut in range(420, 900, 2):
        D.process(d, "BBBUSDT", "5m", cc[:cut], True, cc[cut - 1]["timestamp"] + 305000, None, names)
    assert d["trades"] and BE.pending() == []                                               # history replay writes nothing
    S, Z = TE.mk(I0 + 12)
    for kw in ({"status": "skipped_done", "take": False}, {"status": "open"}):
        assert BE.exit_obs(dict(TE.trade(S), **kw), S, Z, I0, {"net": 1.0, "mfe": 1.0, "giveback": 0.0, "bars": 3, "why": "TP"}, 10.0, 1.0) is None
    assert BE.pending() == []


# ---------------------------------------------------------------- 4. safety
def test_a_data_row_problem_never_stops_the_edge_or_the_bot():
    S, Z = TE.mk(I0 + 12)
    fresh()
    saved = BE.snapshot
    try:
        BE.snapshot = lambda *a, **k: 1 / 0
        tr = TE.trade(S)
        e = BE.observe(tr, S, Z, I0, TE.lv_of(S, I0, 1), 10.0, 1.0)
        assert e is not None and tr["edge"]["st"] == "STRONG" and BE.pending() == [] and "division" in BE.obs_status()["err"]
        d = TE._run_market(11, "5m", step=6)                                                # and process() just carries on
        assert d["trades"]
    finally:
        BE.snapshot = saved
    assert BE.exit_obs(None, S, Z, I0, None, 10.0, 1.0) is None and BE.exit_obs({"status": "closed"}, {"n": 3}, Z, I0, {"bars": 1}, 10.0, 1.0) is None
    BE.confirm("x"); BE.confirm(None)                                                       # nothing here raises
    saved_d = D.BE

    class Boom:
        observe = staticmethod(lambda *a, **k: None)
        close = staticmethod(lambda *a, **k: None)
        exit_obs = staticmethod(lambda *a, **k: 1 / 0)
        slim_edge = staticmethod(lambda t: None)
    try:
        D.BE = Boom
        assert TE._run_market(11, "5m", step=6)["trades"]
    finally:
        D.BE = saved_d


def test_buffer_is_bounded():
    S, Z = TE.mk(I0 + 12)
    S["sma"] = [100.0] * S["n"]
    fresh()
    keep = BE.MAX_BUF
    try:
        BE.MAX_BUF = 50
        for q in range(120):
            tr = dict(TE.trade(S), id="T%d" % q)
            BE.observe(tr, S, Z, I0, TE.lv_of(S, I0, 1), 10.0, 1.0)
        assert len(BE.pending()) == 50 and BE.obs_status()["dropped"] == 190
    finally:
        BE.MAX_BUF = keep


def test_trading_output_identical_with_rows_collected():
    TE.test_process_results_identical_with_and_without_the_hook()                            # same golden sha256 as before Batch 3a / 4a


def test_nothing_that_decides_reads_the_rows():
    names = ("exit_obs", "obs_status", "OBS_KEYS", "BE.pending", "BE.snapshot", "brain_edge.pending", "brain_edge.snapshot", "brain_edge.exit_obs")
    for f in ("strategy.py", "paper_trader.py", "tag_lab.py", "brain_own.py", "brain_exit.py", "brain_exit_pick.py", "brain_tp_hold.py", "filter_lab.py",
              "brain_meta.py", "smart_brain.py", "brain_ready.py", "brain_retest.py", "brain_follow.py", "dual_tp_ext.py"):
        p = os.path.join(HERE, f) if os.path.exists(os.path.join(HERE, f)) else os.path.join(HERE, "recovered_bot", f)
        if os.path.exists(p):
            src = open(p).read()
            assert not any(w in src for w in names), f
    src = open(os.path.join(HERE, "trade_archive.py")).read()
    assert 'tr["edge"]' not in src and 't["edge"]' not in src and re.findall(r"_BE\.(\w+)", src).__len__() > 0
    assert set(re.findall(r"_BE\.(\w+)", src)) <= {"pending", "confirm", "OBS_KEYS"}
    for f in ("brain_edge.py", "trade_archive.py"):
        assert re.search(r"\b(delete\s+from|drop\s+table|truncate|vacuum)\b", open(os.path.join(HERE, f)).read(), re.I) is None, f
    uses = {m for l in open(os.path.join(HERE, "dual_lab.py")).read().splitlines() for m in re.findall(r"\bBE\.(\w+)", l)}
    assert uses == {"close", "observe", "slim_edge", "exit_obs"}, uses


def test_cost_per_observation():
    S, Z = TE.mk(I0 + 280)
    S["sma"] = [100.0] * S["n"]
    tr = TE.trade(S)
    fresh()
    t0 = time.perf_counter()
    for _ in range(50):
        tr.pop("edge", None)
        BE.observe(tr, S, Z, I0, TE.lv_of(S, I0, 1), 10.0, 1.0)
    ms = (time.perf_counter() - t0) / 50 * 1000.0
    print("   observe + data rows on a 280-candle trade: %.2f ms" % ms)
    assert ms < 20.0, ms
    cc, Sr, Zr = real_series()
    t0 = time.perf_counter()
    for k in range(300, 400):
        BE.snapshot(Sr, Zr, k, 1)
    print("   one snapshot on real indicators: %.3f ms" % ((time.perf_counter() - t0) / 100 * 1000.0))


# ---------------------------------------------------------------- 5. archive
def test_archive_keeps_every_row_once_and_forgets_the_buffer():
    fresh()
    d = TE._run_market(23, "5m", step=1)
    rows = BE.pending()
    base = tempfile.mkdtemp()
    st = {}
    assert TA.save_dual(d, st, base=base) is True
    assert BE.pending() == []                                                               # written -> forgotten
    con = sqlite3.connect(os.path.join(base, "dual_archive.db"))
    assert con.execute("SELECT COUNT(*) FROM obs").fetchone()[0] == len(rows)
    r = con.execute("SELECT id, t, k, n, sym, tf, d, v, bv, tag, lag, f FROM obs WHERE k='X' LIMIT 1").fetchone()
    assert r[7] == "o1" and r[8] == "b1" and len(json.loads(r[11])) == len(KEYS)
    assert json.loads(con.execute("SELECT v FROM meta WHERE k='obs_keys_o1'").fetchone()[0]) == list(KEYS)
    avg = con.execute("SELECT AVG(LENGTH(f)) FROM obs").fetchone()[0]
    print("   %d rows, average %.0f characters of numbers per row" % (len(rows), avg))
    assert avg < 230, avg
    BE._BUF.extend(rows[:25])                                                               # the same rows again (e.g. a retry): ignored
    assert TA.save_dual(d, st, base=base) and con.execute("SELECT COUNT(*) FROM obs").fetchone()[0] == len(rows)
    assert TA.status(base)["obs"] == len(rows)
    n_trades = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    assert n_trades == len(d["trades"])                                                      # the trade copy works exactly as before
    con.close()


def test_a_failed_archive_keeps_the_rows_for_the_next_cycle():
    fresh()
    S, Z = TE.mk(I0 + 12)
    S["sma"] = [100.0] * S["n"]
    BE.observe(TE.trade(S), S, Z, I0, TE.lv_of(S, I0, 1), 10.0, 1.0)
    waiting = len(BE.pending())
    assert waiting == 2
    bad = tempfile.NamedTemporaryFile(delete=False).name                                    # a FILE where the folder should be: cannot save
    st = {}
    assert TA.save_dual({"trades": [], "rows": {}, "rt": {}}, st, base=bad) is False and len(BE.pending()) == waiting and st["arch_err"]
    good = tempfile.mkdtemp()
    assert TA.save_dual({"trades": [], "rows": {}, "rt": {}}, st, base=good) is True and BE.pending() == []
    assert sqlite3.connect(os.path.join(good, "dual_archive.db")).execute("SELECT COUNT(*) FROM obs").fetchone()[0] == waiting


def test_an_old_archive_file_opens_and_its_data_stays_readable():
    base = tempfile.mkdtemp()
    con = sqlite3.connect(os.path.join(base, "dual_archive.db"))                             # the layout from before Batch 2 / 4a
    con.executescript("""CREATE TABLE trades (id TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, side INTEGER, src TEXT, status TEXT, net REAL,
      exit_rule TEXT, mode TEXT, saved REAL, js TEXT); CREATE TABLE rows (k TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, js TEXT);
      CREATE TABLE rt (k TEXT PRIMARY KEY, js TEXT); CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
      INSERT INTO trades VALUES ('OLD', 1, 'XUSDT', '5m', 1, 'Z', 'closed', 3.5, 'x', 'm', 1.0, '{"id":"OLD"}');""")
    con.commit(); con.close()
    fresh()
    S, Z = TE.mk(I0 + 12)
    S["sma"] = [100.0] * S["n"]
    BE.observe(TE.trade(S), S, Z, I0, TE.lv_of(S, I0, 1), 10.0, 1.0)
    assert TA.save_dual({"trades": [], "rows": {}, "rt": {}}, {}, base=base) is True
    con = sqlite3.connect(os.path.join(base, "dual_archive.db"))
    assert con.execute("SELECT net, js FROM trades WHERE id='OLD'").fetchone() == (3.5, '{"id":"OLD"}')
    assert con.execute("SELECT COUNT(*) FROM obs").fetchone()[0] == 2
    con.close()


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")
