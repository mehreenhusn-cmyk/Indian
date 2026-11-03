"""owl_sniper_selflog.py - OwlSniper SELF LOG (Part 44 / FILE 53). PAPER ONLY, REPORT ONLY: it only writes its OWN small file, never an order, never a setting of the Sniper.
The owner's question: "What did Sniper learn, which mistakes did it make, what changed?" in plain lines, newest first.
Three kinds of line (nothing is made up: every line comes from a saved file or from a CHANGE between two looks):
  LEARNED = a new fact: an old finding re-tested (CONFIRMED / PARTIAL / REFUTED), an edge verdict reached or changed (VALID / WEAK / EXPIRED), LEARN reached 30 closed trades.
  MISTAKE = a LEARN paper trade that lost, the LEARN kill switch turned ON, a kill rule (WATCH / TRIPPED) that appeared.
  CHANGED = the owner's LEARN switches (on / floor / size), kill switch reset. Sniper changes NOTHING by itself (every check is report only), so this list shows only what really changed.
How it works: each look() reads (1) the LEARN state log (v2_sniper_learn.json), (2) the edge-decay report (owl_sniper_decay), (3) the old-finding re-test (owl_sniper_prior_use). It keeps ONE snapshot of the last look in v2_sniper_selflog.json
and writes a line only for what DIFFERS from that snapshot (a line is never written twice). The first look writes the facts known today once (max 12) so the screen is not empty.
Limit, said openly: the LEARN state keeps only the newest 30 log lines, so if more than 30 LEARN events happen between two looks, the oldest of them are missing from this list.
A part that cannot be read (None) is skipped and its old snapshot is kept, so a read error never looks like a change. A BROKEN own file is never overwritten (state "broken").
API: learn_entries(log, seen), snapshot(learn, decay, prior), diff(prev, snap, now), update(d, now, decay, prior), view(st, now), build(d, now, deep). CLI:  python3 backend/owl_sniper_selflog.py --data DIR [--no-deep]  -> JSON."""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F

VERSION = "owl_sniper_selflog 1 (Part 44)"
FILE = "v2_sniper_selflog.json"
LEARN_FILE = "v2_sniper_learn.json"          # same name as owl_sniper_learn.STATE_FILE; read only here
KEEP, KEEP_SEEN, BASE_MAX, MIN_N = 200, 120, 12, 30
SEV = {"NOT_ENOUGH_DATA": 0, "VALID": 1, "WEAK": 2, "EXPIRED": 3}
KSEV = {"OK": 0, "WATCH": 1, "TRIPPED": 2}
CLOSED = re.compile(r"^LEARN closed (\S+): ([+-]?[0-9.]+) USDT$")
NOTE = "Sniper changes nothing by itself: every check is report only. 'Changed' lists only the owner's switches."


def _e(ts, kind, text, src):
    return {"ts": int(ts), "kind": kind, "text": text, "src": src}


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else None


def learn_entries(log, seen):
    """LEARN state log lines -> (new entries, new seen keys). PURE. Wins are not listed (the LEARN n of 30 bar counts them); losses, kill switch and owner switches are."""
    out, keys, old = [], [], set(seen or ())
    for r in log or ():
        if not isinstance(r, dict) or _num(r.get("ts")) is None or not isinstance(r.get("text"), str):
            continue
        ts, tx = int(r["ts"]), r["text"]
        k = "%d|%s" % (ts, tx)
        if k in old:
            continue
        keys.append(k)
        m = CLOSED.match(tx)
        if m:
            try:
                x = float(m.group(2))
            except ValueError:
                x = None
            p = m.group(1).split("-")
            if x is not None and x <= 0:
                what = "%s %s %s" % (p[2], p[3], p[1]) if len(p) >= 5 else m.group(1)
                out.append(_e(ts, "MISTAKE", "Lost a LEARN paper trade: %s, %+.4f USDT. It counts as a lesson (n of %d)." % (what, x, MIN_N), "learn"))
        elif tx.startswith("LEARN kill switch ON"):
            why = tx[len("LEARN kill switch ON"):].strip()
            out.append(_e(ts, "MISTAKE", "The LEARN kill switch turned ON %s. No new LEARN trade until the owner resets it." % (why or "(no reason saved)"), "learn"))
        elif tx.startswith("LEARN kill switch reset"):
            out.append(_e(ts, "CHANGED", "The owner reset the LEARN kill switch.", "learn"))
        elif tx.startswith("LEARN config:"):
            out.append(_e(ts, "CHANGED", "The owner changed the LEARN switches (" + tx[len("LEARN config:"):].strip() + ").", "learn"))
    return out, keys


def snapshot(learn, decay, prior):
    """The facts to compare next time. A part given as None stays None (= not read). PURE."""
    sn = {"learn_n": None, "edge": None, "kill": None, "prior": None}
    cl = (learn or {}).get("closed") if isinstance(learn, dict) else None
    if isinstance(cl, dict) and _num(cl.get("n")) is not None:
        sn["learn_n"] = int(cl["n"])
    if isinstance(decay, dict) and decay.get("state") in ("OK", "NOT_ENOUGH_DATA"):
        sn["edge"], sn["kill"] = {}, {}
        for fam, a in (decay.get("families") or {}).items():
            if not isinstance(a, dict):
                continue
            if a.get("state") in ("VALID", "WEAK", "EXPIRED"):
                sn["edge"][fam] = {"s": a["state"], "t": str(a.get("edge_line") or "")[:200]}
            if a.get("kill") in ("WATCH", "TRIPPED"):
                ks = a.get("kills") or [{}]
                sn["kill"][fam] = {"s": a["kill"], "t": str(ks[0].get("text") or "")[:200]}
    if isinstance(prior, dict) and prior.get("state") == "OK":
        sn["prior"] = {str(c.get("id")): {"s": c.get("status"), "t": str(c.get("plain") or "")[:260]} for c in prior.get("cands") or () if isinstance(c, dict) and c.get("status") in ("CONFIRMED", "PARTIAL", "REFUTED")}
    return sn


def diff(prev, snap, now):
    """Old snapshot + new snapshot -> new entries. PURE. prev None = first look: the known facts, once (max BASE_MAX)."""
    out = []
    if prev is None:
        out.append(_e(now, "CHANGED", "Self log started. From now on every new lesson, mistake and change is listed here once.", "self"))
        for i, v in (snap.get("prior") or {}).items():
            out.append(_e(now, "LEARNED", "Old finding re-tested: " + v["t"], "prior"))
        for f, v in (snap.get("edge") or {}).items():
            out.append(_e(now, "LEARNED", "Edge of %s: %s" % (f, v["t"]), "decay"))
        for f, v in (snap.get("kill") or {}).items():
            out.append(_e(now, "MISTAKE", "Kill rule %s for %s: %s" % (v["s"], f, v["t"]), "decay"))
        return out[:BASE_MAX]
    a, b = prev.get("learn_n"), snap.get("learn_n")
    if a is not None and b is not None and a < MIN_N <= b:
        out.append(_e(now, "LEARNED", "LEARN reached %d closed trades: Sniper can now be judged on its own paper trades (still paper)." % MIN_N, "learn"))
    for key, name, kind in (("prior", "Old finding re-tested again", "LEARNED"), ("edge", "Edge", "LEARNED")):
        o, n = prev.get(key), snap.get(key)
        if o is None or n is None:
            continue
        for k, v in n.items():
            if k not in o:
                out.append(_e(now, kind, ("%s: %s" % (name, v["t"])) if key == "prior" else "Edge of %s is now judged: %s" % (k, v["t"]), "prior" if key == "prior" else "decay"))
            elif o[k]["s"] != v["s"]:
                out.append(_e(now, kind, ("%s (%s -> %s): %s" % (name, o[k]["s"], v["s"], v["t"])) if key == "prior" else "Edge of %s changed %s -> %s. %s" % (k, o[k]["s"], v["s"], v["t"]), "prior" if key == "prior" else "decay"))
    o, n = prev.get("kill"), snap.get("kill")
    if o is not None and n is not None:
        for k, v in n.items():
            if KSEV[v["s"]] > KSEV[(o.get(k) or {"s": "OK"})["s"]]:
                out.append(_e(now, "MISTAKE", "Kill rule %s for %s: %s" % (v["s"], k, v["t"]), "decay"))
        for k in o:
            if k not in n:
                out.append(_e(now, "LEARNED", "The kill rule for %s is clear again (nothing was paused at any time)." % k, "decay"))
    return out


def _load(d):
    """-> (state dict, broken). Missing file = new. A file that exists but cannot be read = broken (never overwritten)."""
    if not os.path.exists(os.path.join(os.path.realpath(d), FILE)):
        return {"v": 1, "entries": [], "seen": [], "snap": None, "last": 0}, False
    s = F.read_json(d, FILE)
    if not isinstance(s, dict) or not isinstance(s.get("entries"), list) or not isinstance(s.get("seen"), list):
        return {"v": 1, "entries": [], "seen": [], "snap": None, "last": 0}, True
    return s, False


def update(d, now=None, decay=None, prior=None):
    """One look: new entries are added, the snapshot is saved. Returns the state dict (never raises)."""
    now = int(time.time() if now is None else now)
    s, broken = _load(d)
    if broken:
        return dict(s, broken=True)
    learn = F.read_json(d, LEARN_FILE)
    new, keys = learn_entries((learn or {}).get("log"), s["seen"])
    prev = s.get("snap") if isinstance(s.get("snap"), dict) else None
    snap = snapshot(learn, decay, prior)
    if prev is not None:                                           # a part that was not read keeps its old facts
        for k in snap:
            if snap[k] is None:
                snap[k] = prev.get(k)
    new += diff(prev, snap, now)
    s["entries"] = (s["entries"] + new)[-KEEP:]
    s["seen"] = (s["seen"] + keys)[-KEEP_SEEN:]
    s["snap"], s["last"] = snap, now
    if not F.write_json(d, FILE, s):
        s["unsaved"] = True
    return s


def view(st, now=None, limit=60):
    """State -> what the screen shows: newest first, counts per kind, one plain top line."""
    now = int(time.time() if now is None else now)
    if st.get("broken"):
        t = "The self log file is broken, so it was not touched. Remove v2_sniper_selflog.json to start a new log."
        return {"version": VERSION, "state": "broken", "text": t, "lines": [t], "entries": [], "counts": {}, "paper_only": True, "report_only": True}
    es = sorted((x for x in st.get("entries") or () if isinstance(x, dict)), key=lambda x: -x.get("ts", 0))
    cnt = {k: sum(1 for x in es if x.get("kind") == k) for k in ("LEARNED", "MISTAKE", "CHANGED")}
    t = "%d notes: %d learned, %d mistakes, %d changed." % (len(es), cnt["LEARNED"], cnt["MISTAKE"], cnt["CHANGED"]) if es else "Nothing to list yet."
    return {"version": VERSION, "state": "OK" if es else "EMPTY", "text": t, "lines": [t, NOTE], "entries": es[:limit], "counts": cnt, "n_total": len(es), "last_look": st.get("last"), "unsaved": bool(st.get("unsaved")),
            "paper_only": True, "report_only": True, "now": now}


def build(d, now=None, deep=True):
    """Reads the reports (slow part, deep=True), does one look, returns the view. Never raises."""
    dec = pri = None
    if deep:
        try:
            import owl_sniper_decay as DEC
            dec = DEC.build(d, limit=2000, now=now)
        except Exception:
            dec = None
        try:
            import owl_sniper_prior_use as PU
            pri = PU.build(d, now=now)
        except Exception:
            pri = None
    try:
        return view(update(d, now, dec, pri), now)
    except Exception as e:
        t = "The self log could not be built: %s." % type(e).__name__
        return {"version": VERSION, "state": "error", "text": t, "lines": [t], "entries": [], "counts": {}, "paper_only": True, "report_only": True}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper self log (report only)")
    ap.add_argument("--data", required=True)
    ap.add_argument("--no-deep", action="store_true", help="only the LEARN log, skip the slow edge / old-finding reports")
    a = ap.parse_args(argv)
    print(json.dumps(build(a.data, deep=not a.no_deep), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
