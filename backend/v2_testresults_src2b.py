"""v2_testresults_src2b.py - R10 / Lab backend B (2 of 2): LOADERS. Gets the reports for the seven R10 families and hands them to the converters of v2_testresults_src2.py.
LIGHT families (brain, exit, dual, ignored): collect() only READS smart_brain_view.json, the small file the Smart Brain already writes every few minutes (learn.stats, learn.skip, edge, tp_hold, timing). Nothing is recomputed,
  nothing is written, brain_archive.db is NOT touched (brain_stats.refresh writes to it, so it is never called here). The parsed file is cached until its modified time changes.
HEAVY families (wick, regime, scalp): refresh() builds them from the saved candles / trade files (all read only) and writes ONE small file, v2_lab_results_b.json. Called by the route's slow loop through v2_testresults_src.refresh
  (first run 10 minutes after start, then every 6 hours), never by a screen. collect() only reads that file.
collect(d, now) -> (TestResults, meta {family: {state, tests, age_sec / why}}). Never raises. A missing / broken source = that family says NOT_RUN_YET / ERROR in meta; the others still answer.
Writes ONLY v2_lab_results_b.json. Paper only, no order code, no trading import."""
import importlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F
import v2_testresults as T
import v2_testresults_src2 as C

VERSION = "v2_testresults_src2b 1 (R10)"
VIEW_FILE, SAVED_FILE = "smart_brain_view.json", "v2_lab_results_b.json"
LIGHT, HEAVY = ("brain", "exit", "dual", "ignored"), ("wick", "regime", "scalp")
MAX_VIEW_BYTES = 30_000_000
WICK_DAYS, SCALP_LIMIT, SCALP_DAYS = 3, 6000, 30           # the same 3 days as the Study Lab cards; the newest 6000 records of the last 30 days keep the phone light
_cache = {"key": None, "view": None}


def _view(d):
    """-> (view dict or None, modified time). The Smart Brain's own file, opened read only, parsed again only when it changed."""
    p = F._p(d, VIEW_FILE)
    try:
        if os.path.islink(p) or not os.path.isfile(p) or os.path.getsize(p) > MAX_VIEW_BYTES:
            return None, None
        key = (p, os.path.getmtime(p), os.path.getsize(p))
        if _cache["key"] != key:
            _cache.update(key=key, view=F.read_json(d, VIEW_FILE))
        return _cache["view"], key[1]
    except OSError:
        return None, None


def light(d, now):
    """-> (results, meta) for brain / exit / dual / ignored, straight from the Brain's saved view."""
    v, mt = _view(d)
    if not v or not isinstance(v, dict):
        why = "The Smart Brain has not saved its view yet (file %s)." % VIEW_FILE
        return [], {f: {"state": "NOT_RUN_YET", "why": why} for f in LIGHT}
    beat = v.get("beat") if T.num(v.get("beat")) else mt
    ago = int(now - beat) if T.num(beat) else -1
    learn = v.get("learn") if isinstance(v.get("learn"), dict) else {}
    jobs = {"brain": lambda: C.from_brain_stats(learn.get("stats"), ago) + C.from_brain_edge(v.get("edge"), ago), "exit": lambda: C.from_exit(v.get("tp_hold"), ago),
            "dual": lambda: C.from_dual(v.get("timing"), ago), "ignored": lambda: C.from_ignored(learn.get("skip"), ago)}
    rs, meta = [], {}
    for fam in LIGHT:
        try:
            got = jobs[fam]()
            rs += got
            meta[fam] = {"state": "OK", "tests": len(got), "age_sec": ago if ago >= 0 else None}
        except Exception as e:                                      # one bad block must not hide the others
            meta[fam] = {"state": "ERROR", "why": "%s: %s" % (type(e).__name__, str(e)[:100])}
    return rs, meta


def heavy(d, now):
    """-> (results, meta) for wick / regime / scalp, from the one saved file the slow loop makes."""
    rep = F.read_json(d, SAVED_FILE)
    fams = (rep or {}).get("families") if isinstance((rep or {}).get("families"), dict) else {}
    made = (rep or {}).get("made")
    ago = int(now - made) if T.num(made) else -1
    rs, meta = [], {}
    for fam in HEAVY:
        f = fams.get(fam)
        if not isinstance(f, dict):
            meta[fam] = {"state": "NOT_RUN_YET", "why": "The first study run has not finished yet (the slow loop runs it by itself)."}
            continue
        if f.get("state") != "OK":
            meta[fam] = {"state": f.get("state") or "ERROR", "why": f.get("why") or ""}
            continue
        got = [dict(r, updated_ago_sec=ago) for r in f.get("results") or [] if isinstance(r, dict)]
        rs += got
        meta[fam] = {"state": "OK", "tests": len(got), "age_sec": ago if ago >= 0 else None}
    return rs, meta


def collect(d, now=None):
    now = time.time() if now is None else now
    try:
        a, ma = light(d, now)
    except Exception as e:
        a, ma = [], {f: {"state": "ERROR", "why": "%s: %s" % (type(e).__name__, str(e)[:100])} for f in LIGHT}
    try:
        b, mb = heavy(d, now)
    except Exception as e:
        b, mb = [], {f: {"state": "ERROR", "why": "%s: %s" % (type(e).__name__, str(e)[:100])} for f in HEAVY}
    return a + b, dict(ma, **mb)


def _wick(d, now, tf):
    wk = importlib.import_module("v2_wickstudy")
    con = F.open_ro(d)
    if con is None:
        return {"state": "NOT_READY", "why": "No market store yet: no candles are saved."}
    try:
        rep = wk.build_forward(con, now, WICK_DAYS)
    finally:
        con.close()
    if not rep.get("ready"):
        return {"state": "NOT_READY", "why": "No coin has clean saved candles in the last %d days." % WICK_DAYS}
    return {"state": "OK", "results": C.from_wick(rep, -1)}


def _regime(d, now, tf):
    rg = importlib.import_module("owl_sniper_regime")
    rep = rg.build(d, tf)
    if not rep.get("ready"):
        return {"state": "NOT_READY", "why": str(rep.get("note") or "not ready")[:120]}
    return {"state": "OK", "results": C.from_regime(rep, -1, now, now)}


def _scalp(d, now, tf):
    sc = importlib.import_module("owl_sniper_scalp")
    rep = sc.build(d, SCALP_LIMIT, SCALP_DAYS)
    if rep.get("state") == "ERROR":
        return {"state": "ERROR", "why": str(rep.get("text") or "")[:120]}
    return {"state": "OK", "results": C.from_scalp(rep, -1)}


def refresh(d, tf="5m", now=None):
    """The heavy part: build wick / regime / scalp once and save them in ONE file. -> {family: 'saved' / 'not ready: ...' / 'error: ...'}. Never raises."""
    now = int(time.time() if now is None else now)
    fams, out = {}, {}
    for fam, fn in (("wick", _wick), ("regime", _regime), ("scalp", _scalp)):
        try:
            fams[fam] = fn(d, now, tf)
            out[fam] = "saved" if fams[fam]["state"] == "OK" else "not ready: %s" % fams[fam].get("why", "")[:60]
        except Exception as e:
            fams[fam] = {"state": "ERROR", "why": "%s: %s" % (type(e).__name__, str(e)[:100])}
            out[fam] = "error: %s: %s" % (type(e).__name__, str(e)[:80])
    try:
        ok = F.write_json(d, SAVED_FILE, {"made": now, "tf": tf, "families": fams})
    except Exception as e:                                          # a result that cannot become JSON must not kill the loop
        ok = False
        out["save"] = "error: %s" % type(e).__name__
    if not ok:
        out["save"] = out.get("save") or "not saved (folder not writable)"
    return out
