#!/usr/bin/env python3
"""
trade_archive.py - Part U1: the LONG-TERM ARCHIVE. Nothing that reaches it is ever deleted.

Why: Dual Bot keeps only its newest 600 trades / 5000 learning rows (dual_lab.trim) and the Brain keeps 300 own trades, 400 picks and
300 exit opinions. Everything older is thrown away to keep the phone fast. The owner wants the Brain to forget nothing until it is
ready for real money, so before anything can be trimmed it is copied here (SQLite file = a filing cabinet: pages are added, none removed).

Files (in the data folder, next to dual_lab_data.json, so zips and updates never touch them):
  dual_archive.db   written by the Dual Bot worker right BEFORE trim():  trades (every state change), rows, rt (retest rows),
                    obs (B4a: one data row per closed candle of an open trade + entry + exit rows, see brain_edge.py; Brain learns from it later)
  brain_archive.db  written by the Brain worker:  own finished trades, frozen picks, exit opinions
Rules: this file never runs a delete statement (test_trade_archive.py checks the source); a failure is caught, remembered and shown,
it never stops a bot. Only the Python standard library (sqlite3). One writer per file, so there is no locking fight.
Run by hand: cd backend && python3 trade_archive.py status
"""
import json
import os
import sqlite3
import sys
import time

DUAL_DB, BRAIN_DB = "dual_archive.db", "brain_archive.db"
STALE_S = 180                      # no save for 3 minutes = the app shows "stale"

_DUAL_SQL = """
CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, side INTEGER, src TEXT, status TEXT,
  net REAL, exit_rule TEXT, mode TEXT, saved REAL, js TEXT);
CREATE INDEX IF NOT EXISTS trades_t ON trades(t);
CREATE TABLE IF NOT EXISTS rows (k TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, js TEXT);
CREATE INDEX IF NOT EXISTS rows_t ON rows(t);
CREATE TABLE IF NOT EXISTS rt (k TEXT PRIMARY KEY, js TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS obs (id TEXT, t INTEGER, k TEXT, n INTEGER, sym TEXT, tf TEXT, d INTEGER, v TEXT, bv TEXT, tag TEXT, lag INTEGER, f TEXT,
  PRIMARY KEY (id, t, k));
CREATE INDEX IF NOT EXISTS obs_t ON obs(t);
"""
_BRAIN_SQL = """
CREATE TABLE IF NOT EXISTS own (id TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, net REAL, stage TEXT, saved REAL, js TEXT);
CREATE TABLE IF NOT EXISTS picks (id TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, mode TEXT, js TEXT);
CREATE TABLE IF NOT EXISTS exit_shadow (k TEXT, t INTEGER, js TEXT, PRIMARY KEY (k, t));
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""
_NEW_COLS = {DUAL_DB: "trades", BRAIN_DB: "own"}        # Batch 2: columns added to the EXISTING tables (old rows keep NULL = not recorded)
_NEW_SPEC = (("mfe", "REAL"), ("giveback", "REAL"), ("brain_version", "TEXT"))
_META = "INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v"
_B = {"own": set(), "pk": set(), "ex": set()}     # what the Brain worker already saved (this process)
_C = {"t": 0.0, "v": None}                                                  # status() cache


def _dir(base=None):
    if not base:
        base = os.environ.get("OWL_DATA_DIR")
    if not base:
        try:
            with open(os.path.expanduser("~/.owl_data_dir"), "r", encoding="utf-8") as f:
                base = f.read().strip()
        except Exception:
            base = ""
    base = base or os.path.expanduser("~/owl_data")
    os.makedirs(base, exist_ok=True)
    return base


def _open(name, sql, base=None):
    con = sqlite3.connect(os.path.join(_dir(base), name), timeout=20)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(sql)
    tbl = _NEW_COLS.get(name)
    if tbl:
        have = {r[1] for r in con.execute("PRAGMA table_info(%s)" % tbl)}
        for col, typ in _NEW_SPEC:
            if col not in have:
                con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, col, typ))
    return con


def _js(x):
    return json.dumps(x, separators=(",", ":"), default=str)


def _fail(holder, e):
    holder["arch_err"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    if time.time() - holder.get("arch_err_t", 0) > 600:          # print at most every 10 minutes
        holder["arch_err_t"] = time.time()
        print("trade_archive: NOT saved (%s)" % holder["arch_err"], flush=True)


def save_dual(data, st=None, base=None):
    """Dual Bot worker, right before trim(): copies new / changed trades and new rows. Returns True when saved. Never raises."""
    st = st if st is not None else {}
    try:
        seen_t, seen_r, seen_rt = st.setdefault("arch_t", {}), st.setdefault("arch_r", set()), st.setdefault("arch_rt", set())
        now = time.time()
        tr = []
        for t in data.get("trades") or []:
            sig = (t.get("status"), t.get("net"), t.get("end"))
            if t.get("id") and seen_t.get(t["id"]) != sig:
                tr.append((t, sig))
        rows = data.get("rows") or {}
        rt = data.get("rt") or {}
        rw = [(k, v) for k, v in rows.items() if k not in seen_r]
        rr = [(k, v) for k, v in rt.items() if k not in seen_rt]
        ob = []
        try:                                                      # B4a: data rows waiting in brain_edge (a problem here never stops the trade copy)
            import brain_edge as _BE
            ob = _BE.pending()
        except Exception:
            ob = []
        con = _open(DUAL_DB, _DUAL_SQL, base)
        try:
            with con:
                if ob:
                    con.executemany("INSERT OR IGNORE INTO obs(id, t, k, n, sym, tf, d, v, bv, tag, lag, f) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                    [r[:11] + (_js(r[11]),) for r in ob])
                    con.execute("INSERT OR IGNORE INTO meta(k, v) VALUES(?, ?)", ("obs_keys_" + ob[0][7], _js(list(_BE.OBS_KEYS))))   # the layout of f, saved next to the data
                con.executemany(
                    "INSERT INTO trades(id, t, sym, tf, side, src, status, net, exit_rule, mode, saved, js, mfe, giveback, brain_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET status=excluded.status, net=excluded.net, saved=excluded.saved, js=excluded.js, "
                    "mfe=COALESCE(excluded.mfe, trades.mfe), giveback=COALESCE(excluded.giveback, trades.giveback), "
                    "brain_version=COALESCE(excluded.brain_version, trades.brain_version)",   # Batch 2: a later save without the value never wipes it
                    [(t["id"], t.get("t"), t.get("s"), t.get("f"), t.get("d"), t.get("src"), t.get("status"), t.get("net"),
                      t.get("exit"), t.get("mode"), now, _js(t), t.get("mfe"), t.get("giveback"), t.get("brain_version")) for t, _ in tr])
                con.executemany("INSERT OR IGNORE INTO rows(k, t, sym, tf, js) VALUES(?,?,?,?,?)",
                                [(k, v[2], v[0], v[1], _js(v)) for k, v in rw])
                con.executemany("INSERT OR IGNORE INTO rt(k, js) VALUES(?,?)", [(k, _js(v)) for k, v in rr])
                con.execute(_META, ("last_sync", str(now)))
                con.execute("INSERT OR IGNORE INTO meta(k, v) VALUES('first_sync', ?)", (str(now),))
        finally:
            con.close()
        if ob:
            _BE.confirm(len(ob))                                  # safely written: the buffer may forget them (a failed save keeps them for the next cycle)
        for t, sig in tr:
            seen_t[t["id"]] = sig
        seen_r.update(k for k, _ in rw)
        seen_rt.update(k for k, _ in rr)
        if len(seen_r) > 3 * len(rows) + 2000:                   # forget keys trim() already dropped (they stay safe in the archive)
            seen_r.intersection_update(rows)
        if len(seen_rt) > 3 * len(rt) + 2000:
            seen_rt.intersection_update(rt)
        st["arch_err"] = ""
        return True
    except Exception as e:
        _fail(st, e)
        return False


def save_brain(own=None, ex=None, book=None, base=None):
    """Brain worker: copies finished own trades, frozen picks and exit opinions that were not saved yet. Never raises."""
    try:
        closed = [t for t in (own or {}).get("closed", []) if t.get("id") and t["id"] not in _B["own"]]
        picks = [p for p in ((book or {}).get("picks") or {}).values() if p.get("id") and p["id"] not in _B["pk"]]
        shadow = [e for e in (ex or {}).get("done", []) if (e.get("k"), e.get("t")) not in _B["ex"]]
        con = _open(BRAIN_DB, _BRAIN_SQL, base)
        try:
            with con:
                con.executemany("INSERT OR IGNORE INTO own(id, t, sym, tf, net, stage, saved, js, mfe, giveback, brain_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                [(t["id"], t.get("t"), t.get("s"), t.get("f"), t.get("net"), t.get("stage"), time.time(), _js(t),
                                  t.get("mfe"), t.get("giveback"), t.get("brain_version")) for t in closed])
                con.executemany("INSERT OR IGNORE INTO picks(id, t, sym, tf, mode, js) VALUES(?,?,?,?,?,?)",
                                [(p["id"], p.get("t"), p.get("s"), p.get("f"), p.get("mode"), _js(p)) for p in picks])
                con.executemany("INSERT OR IGNORE INTO exit_shadow(k, t, js) VALUES(?,?,?)", [(e.get("k"), e.get("t"), _js(e)) for e in shadow])
                con.execute(_META, ("last_sync", str(time.time())))
        finally:
            con.close()
        _B["own"].update(t["id"] for t in closed)
        _B["pk"].update(p["id"] for p in picks)
        _B["ex"].update((e.get("k"), e.get("t")) for e in shadow)
        _B["arch_err"] = ""
        return True
    except Exception as e:
        _fail(_B, e)
        return False


def _count(con, sql):
    try:
        return int(con.execute(sql).fetchone()[0] or 0)
    except Exception:
        return 0


def _meta_of(con, k):
    try:
        r = con.execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
        return float(r[0]) if r else 0.0
    except Exception:
        return 0.0


def _ago(sec):
    sec = int(max(0, sec))
    try:                                     # owner rule: over 60 min = hours + minutes
        from timefmt import span
        return span(sec) + " ago"
    except Exception:
        return "%d s ago" % sec if sec < 90 else "%d min ago" % (sec // 60) if sec < 5400 else "%d h ago" % (sec // 3600)


def status(base=None):
    """Small plain summary for the app (DATA SAFE chip). Reads only, cached for 8 seconds. Never raises."""
    now = time.time()
    if not base and _C["v"] is not None and now - _C["t"] < 8:
        return dict(_C["v"])
    out = {"state": "none", "text": "Archive not started yet.", "trades": 0, "closed": 0, "rows": 0, "rt": 0, "obs": 0, "own": 0, "picks": 0,
           "exit_shadow": 0, "first_t": None, "last_sync": 0, "age_s": None, "mb": 0.0, "err": ""}
    try:
        d = _dir(base)
        p = os.path.join(d, DUAL_DB)
        if os.path.exists(p):
            con = sqlite3.connect(p, timeout=5)
            try:
                out["trades"] = _count(con, "SELECT COUNT(*) FROM trades")
                out["closed"] = _count(con, "SELECT COUNT(*) FROM trades WHERE status IN ('closed','skipped_done')")
                out["rows"] = _count(con, "SELECT COUNT(*) FROM rows")
                out["rt"] = _count(con, "SELECT COUNT(*) FROM rt")
                out["obs"] = _count(con, "SELECT COUNT(*) FROM obs")
                out["first_t"] = con.execute("SELECT MIN(t) FROM trades").fetchone()[0]
                out["last_sync"] = _meta_of(con, "last_sync")
            finally:
                con.close()
        p = os.path.join(d, BRAIN_DB)
        if os.path.exists(p):
            con = sqlite3.connect(p, timeout=5)
            try:
                out["own"], out["picks"] = _count(con, "SELECT COUNT(*) FROM own"), _count(con, "SELECT COUNT(*) FROM picks")
                out["exit_shadow"] = _count(con, "SELECT COUNT(*) FROM exit_shadow")
            finally:
                con.close()
        out["mb"] = round(sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d) if f.endswith(("_archive.db", "_archive.db-wal"))) / 1048576.0, 1)
        if out["last_sync"]:
            out["age_s"] = int(now - out["last_sync"])
            out["state"] = "safe" if out["age_s"] <= STALE_S else "stale"
            out["text"] = "%s: %d trades, %d learning rows, %d Brain trades saved. Last save %s." % (
                "Safe" if out["state"] == "safe" else "Waiting (Dual Bot stopped?)", out["trades"], out["rows"], out["own"], _ago(out["age_s"]))
    except Exception as e:
        out["state"], out["err"] = "error", "%s: %s" % (type(e).__name__, str(e)[:100])
        out["text"] = "Archive problem: " + out["err"]
    _C["t"], _C["v"] = now, dict(out)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print(json.dumps(status(), indent=1))
    else:
        print(__doc__)
