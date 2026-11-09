"""v2_f7_gates.py - FILTER STUDY Part 7: WINNING GATES INTO THE CURRENT BOT. The ONLY Part that can change trading (README_FILTER.md).
Default OFF. Mode is the setting f7_gates_mode: "off" = nothing happens | "log" = the gate only WRITES what it would have blocked (v2_f7_gate_log.jsonl) | "block" = the gate skips the entry.
Scope: the current bot (b1, MAIN group) on the 5m timeframe, because the study rules were measured on exactly that. Other bots / timeframes are never touched.
TWO JOBS IN ONE FILE
1) BUILD RULES (runs by itself on the VPS, never by hand): the filter lab (Part 4) is run again on MAIN 5m paper trades. A filter becomes a rule only when ALL are true:
   verdict PASS (net gain in TRAIN and TEST, 10+ blocked in both, ZERO 3%+ moves lost), LUCK % <= 20, and it can be made live (nth-trade-of-day is left out).
   The rules are then tested TOGETHER (union of blocked trades): if the union is not a PASS on TEST, the weakest rule is dropped until it is. No PASS = no rules = the gate does nothing.
   Cut-offs come from TRAIN data only (Part 4). Nothing here is guessed. Result: v2_f7_rules.json (rules + numbers). Rebuilt when older than 24 h (own low-priority process, max one try per 6 h).
2) GATE (live): when the current bot has a signal on 5m, the same entry numbers as the study are made from the last closed candles (bot cache + the saved candle store for the older part),
   every rule is checked, and a hit gives a reason text. ANY problem (no candles, stale candles, no number, error) = take the trade (fail-open), same as the other gates in _extra_entry_block.
Entry numbers for rules about the trade count of the day (nth) are not made live. A number that is missing never blocks.
CLI (normally not needed): python3 v2_f7_gates.py --build --data /home/owl/owl_data   (builds v2_f7_rules.json and prints a summary)
Day = 00:00 UTC = 5:30 AM IST. Durations over 60 min are written as hours + minutes."""
import argparse
import json
import os
import random
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_f7_gates 1 (Filter Part 7)"
RULES_FILE, LOG_FILE = "v2_f7_rules.json", "v2_f7_gate_log.jsonl"
GROUP, TF, STEP = "MAIN", "5m", 300
LUCK_MAX = 20.0                         # a rule must beat luck: at most 20% of random blocks save as much on TEST
REBUILD_SEC, RETRY_SEC, STALE_SEC = 24 * 3600, 6 * 3600, 900
PRE_CANDLES = 300                       # older candles read from the saved store (the bot cache holds only 259)
NOT_LIVE = ("nth", "nth_b")             # numbers that are not made live
LOG_MAX = 2 * 1024 * 1024
_st = {"rules": None, "mtime": None, "proc": None, "last_try": 0.0, "seen": 0, "hit": 0, "skipped": 0, "error": "", "cfg": None, "cfg_t": 0.0}
_lock = threading.Lock()


def _root():
    import v2_inventory as I
    return os.path.realpath(I.find_data_dir())


def _mode():
    try:
        from recovered_bot import settings_store
        m = str(settings_store.get("f7_gates_mode", "off") or "off").lower()
        return m if m in ("log", "block") else "off"
    except Exception:
        return "off"


# ----------------------------------------------------------------------------- 1) build the rules from the filter lab
def _rule_of(j):
    """Part 4 filter result -> a small live rule, or None when it cannot be made live."""
    import v2_f4_filters as F4
    name = j["filter"]
    if j["family"] == "BUCKET":
        for title, key, nm in F4.bucket_filters():
            if name == "BLOCK %s = %s" % (title, nm) and key not in NOT_LIVE:
                return {"kind": "bucket", "key": key, "bucket": nm}
        return None
    for _k, label, field in F4.NUMBERS:
        for d, sym in (("below", "<"), ("above", ">=")):
            if name.startswith("BLOCK %s %s " % (label, sym)) and field not in NOT_LIVE and j.get("cut") is not None:
                return {"kind": "cut", "field": field, "dir": d, "cut": j["cut"]}
    return None


def build_rules(root):
    import owl_sniper_feed as FEED
    import v2_f1_counts as X
    import v2_f2_fakes as K
    import v2_f3a_moves as A
    import v2_f4_filters as F4
    import v2_pnl as P
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "made_ts": time.time(), "group": GROUP, "tf": TF, "luck_max_pct": LUCK_MAX, "rules": [], "status": ""}
    X.build_report(root)                                               # fresh Part 1 rows (the study files are made again from the newest trades + candles)
    try:
        A.build_report(root)
    except Exception as e:
        rep["note_moves_error"] = str(e)[:200]
    src = K.load_rows(root)
    mv = F4.load_json(root, A.MOVES_FILE)
    moves = [m for m in ((mv or {}).get("moves") or []) if (m.get("list") or {}).get("kind") != "CONTROL" and (m.get("size_pct") or 0) >= 3.0]
    rows, _dropped = K.prepare((src or {}).get("rows") or [])
    for r in rows:
        F4.derive(r)
    rows = [r for r in rows if r.get("g") == GROUP and r.get("tf") == TF]
    sc = F4.make_scope(rows, moves)
    if sc is None:
        rep["status"] = "NO_RULES: not enough MAIN 5m trades (%d, need %d)" % (len(rows), F4.MIN_SCOPE)
    elif not moves:
        rep["status"] = "NO_RULES: no moves file, the zero-moves-lost check is not possible (never trusted)"
    else:
        rng = random.Random(7)
        cands = F4.bucket_results(sc, True) + F4.cutoff_results(sc, True)
        keep = []
        for j, b in cands:
            if "train" not in j or j["verdict"] != "PASS" or not b:
                continue
            rule = _rule_of(j)
            lk = F4.luck(sc, j["test"]["blocked"], j["test"]["net_gain"], rng)
            if rule is None or lk is None or lk > LUCK_MAX:
                continue
            rule.update({"name": j["filter"], "luck_random_as_good_pct": lk, "train": j["train"], "test": j["test"]})
            keep.append((rule, b))
        keep.sort(key=lambda x: -x[0]["test"]["net_gain"])
        rep["passed_alone"] = len(keep)
        while keep:                                                    # the rules together must also PASS on TEST
            total = set().union(*(b for _r, b in keep))
            tr, te = (F4.evaluate(sc["rows"], total, sc["parts"][p]) for p in ("train", "test"))
            if F4.verdict(tr, te, True) == "PASS":
                rep["combined"] = {"train": tr, "test": te, "luck_random_as_good_pct": F4.luck(sc, te["blocked"], te["net_gain"], rng)}
                break
            keep.pop()                                                 # drop the weakest (smallest TEST gain)
        rep["rules"] = [dict(r, id="R%d" % (i + 1)) for i, (r, _b) in enumerate(keep)]
        rep["status"] = ("OK: %d rules" % len(keep)) if keep else "NO_RULES: no filter passed (PASS + low luck + together PASS). The gate does nothing."
        rep["trades_used"], rep["moves_used_3pct_plus"] = len(rows), len(moves)
    rep["saved"] = FEED.write_json(root, RULES_FILE, rep)
    return rep


# ----------------------------------------------------------------------------- 2) live gate
def _rules(root):
    """Rules from the file (cached by file time). Starts a rebuild in its own low-priority process when the file is missing or older than 24 h."""
    p = os.path.join(root, RULES_FILE)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        mt = None
    if mt is None or time.time() - mt > REBUILD_SEC:
        _start_build(root)
    if mt is None:
        return []
    with _lock:
        if _st["mtime"] != mt:
            import owl_sniper_feed as FEED
            rep = FEED.read_json(root, RULES_FILE) or {}
            _st["rules"] = rep.get("rules") or [] if str(rep.get("status", "")).startswith("OK") else []
            _st["mtime"] = mt
        return _st["rules"] or []


def _start_build(root):
    with _lock:
        pr = _st["proc"]
        if (pr is not None and pr.poll() is None) or time.time() - _st["last_try"] < RETRY_SEC:
            return
        _st["last_try"] = time.time()
        try:
            kw = {"preexec_fn": lambda: os.nice(10)} if hasattr(os, "nice") else {}
            _st["proc"] = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--build", "--data", root], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        except Exception as e:
            _st["error"] = "build start: %s" % str(e)[:120]


def _cfg(root):
    if _st["cfg"] is None or time.time() - _st["cfg_t"] > 600:
        import owl_sniper_engine as E
        import owl_sniper_ind_pairs as IP
        try:
            _st["cfg"] = IP.load_cfg(root, TF)[0]
        except Exception:
            _st["cfg"] = dict(E.DEFAULTS)
        _st["cfg_t"] = time.time()
    return _st["cfg"]


def _tuples(root, symbol, cache):
    """Bot candles (dicts, ms) -> engine tuples (s) with the older saved candles in front. -> (tuples, cohort) or None."""
    import owl_sniper_feed as FEED
    import v2_f1_counts as X
    tl = []
    for c in cache or []:
        t = int(c["timestamp"])
        tl.append((t // 1000 if t > 10 ** 11 else t, c["open"], c["high"], c["low"], c["close"], c.get("volume") or 0))
    if len(tl) < 60 or tl[1][0] - tl[0][0] != STEP or time.time() - tl[-1][0] > STALE_SEC:
        return None                                                    # not 5m, too short or stale
    cohort, con = {}, FEED.open_ro(root)
    if con is not None:
        try:
            cohort = X.load_cohort(con)
            old = con.execute("SELECT open_ts, o, h, l, c, v FROM candles WHERE symbol=? AND interval=? AND open_ts<? ORDER BY open_ts DESC LIMIT ?", (symbol, TF, tl[0][0], PRE_CANDLES)).fetchall()
            pre, nxt = [], tl[0][0]
            for x in old:                                              # newest first; stop at the first gap
                if x[0] + STEP != nxt:
                    break
                pre.append(tuple(x))
                nxt = x[0]
            tl = pre[::-1] + tl
        except Exception:
            pass
        finally:
            con.close()
    return tl, cohort


def live_row(signal, symbol, cache, root):
    """The same entry numbers as the study (Part 1) for this signal, or None when they cannot be made."""
    import owl_sniper_engine as E
    import v2_f1_counts as X
    import v2_f2_fakes as K
    import v2_f4_filters as F4
    import v2_money_hour as M
    from recovered_bot import settings_store
    got = _tuples(root, symbol, cache)
    if got is None:
        return None
    tl, cohort = got
    side = 1 if str(signal.action).upper() in ("BUY", "LONG") else -1
    cfg = _cfg(root)
    S = E.build_features(tl, cfg)
    i = S["n"] - 1
    if i < E.warmup_end(S):
        return None
    now = time.time()
    rc = getattr(signal, "regime_cross_n", None)
    r = {"sym": symbol, "g": GROUP, "tf": TF, "side": side, "ent": now, "entry_price": float(signal.entry_price), "lev": float(settings_store.get("leverage", 1) or 1),
         "fee_roi": float(settings_store.get("fee_roi_pct", 1.0) or 1.0), "tp1": getattr(signal, "tp1", None), "tp4": getattr(signal, "tp4", None), "regime_cross_n": rc}
    idx = {t: j for j, t in enumerate(S["t"])}
    r.update(X.candle_numbers(S, tl, idx, i, r))
    r.update(X.shape_numbers(S, i, side))
    r.update(X.setup_numbers(S, i, side, cfg))
    r.update(X.cohort_numbers(r, cohort))
    r["side_b"] = "LONG" if side == 1 else "SHORT"
    r["chop_b"] = "n/a" if rc is None else (K.CHOP[1] if rc >= 3 else K.CHOP[0])
    r["session"] = M.session_of(time.gmtime(now).tm_hour)
    F4.derive(r)
    return r


def _hit(rule, r):
    if rule["kind"] == "bucket":
        return r.get(rule["key"]) == rule["bucket"]
    v = r.get(rule["field"])
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False                                                   # no number = never blocked
    return v < rule["cut"] if rule["dir"] == "below" else v >= rule["cut"]


def _log(root, line):
    try:
        p = os.path.join(root, LOG_FILE)
        if os.path.isfile(p) and os.path.getsize(p) > LOG_MAX:
            os.replace(p, p + ".old")
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, separators=(",", ":"), default=str) + "\n")
    except Exception:
        pass


def gate_reason(signal, symbol, cache):
    """Called by the current bot (b1) before it opens a paper trade. A reason text ONLY when mode is "block" and a rule hits, else None (= take it)."""
    m = _mode()
    if m == "off":
        return None
    try:
        root = _root()
        rules = _rules(root)
        if not rules:
            return None
        r = live_row(signal, symbol, cache, root)
        if r is None:
            _st["skipped"] += 1
            return None
        _st["seen"] += 1
        hits = [x for x in rules if _hit(x, r)]
        if not hits:
            return None
        _st["hit"] += 1
        _log(root, {"t": int(time.time()), "sym": symbol, "side": r["side"], "mode": m, "rules": [x["id"] for x in hits], "blocked": m == "block"})
        if m == "block":
            return "Filter gate (Part 7): " + "; ".join(x["name"].replace("BLOCK ", "", 1) for x in hits[:3])
    except Exception as e:
        _st["error"] = str(e)[:160]
    return None


def info():
    """For the app (Part 8): mode, rules, counters since the backend started."""
    root = _root()
    rep = {}
    try:
        import owl_sniper_feed as FEED
        rep = FEED.read_json(root, RULES_FILE) or {}
    except Exception:
        pass
    return {"mode": _mode(), "status": rep.get("status", "no rules file yet"), "made_utc": rep.get("made_utc"), "rules": len(rep.get("rules") or []), "combined": rep.get("combined"),
            "signals_checked": _st["seen"], "signals_hit": _st["hit"], "signals_skipped_no_numbers": _st["skipped"], "last_error": _st["error"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 7: build the gate rules (the gate itself runs inside the bot)")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    if not a.build:
        print(json.dumps(info(), indent=1, default=str))
        return 0
    import v2_inventory as I
    rep = build_rules(I.find_data_dir(a.data))
    print(json.dumps({k: rep.get(k) for k in ("status", "made_utc", "passed_alone", "combined", "saved")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
