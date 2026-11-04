"""v2_testresults_src.py - R9 / Lab backend A: SOURCES. Turns the saved answers of the four indicator studies into TestResults (shape + verdict rules live in v2_testresults.py).
  zsma     <- v2_sniper_zsma.json      (owl_sniper_zsma.py: Z-SMA as support / resistance, 4 kinds x 3 regimes)
  sd_bands <- v2_sniper_sdbands.json   (owl_sniper_sdbands.py: SD band 1 / 2 / 3 as support / resistance, 12 kinds x 3 regimes)
  pairs    <- v2_sniper_ind_pairs.json (owl_sniper_ind_pairs.py: Z / TSI / cloud / zone against price)
  combos   <- v2_sniper_combo.json     (owl_sniper_combo.py: SD band + Z-SMA + TSI together; feature attribution is NOT included here)
collect(d) = READ ONLY: reads the four saved files (never recomputes), -> (results, meta). A missing or broken file = that family says NOT_RUN_YET / ERROR in meta; the other families still answer.
refresh(d, tf) = the HEAVY part (each study reads the saved candles, read only): builds the four studies one by one and writes ONLY these four small files (R10 adds v2_lab_results_b.json through v2_testresults_src2b.py). Called by the route's slow loop (api/v2_lab_route.py), never by a screen.
States with no event at all (n = 0) are left out. Paper only, no order code."""

import importlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F
import v2_testresults as T
import v2_testresults_src4 as X                 # R12: 9 exit rules x market state
import v2_testresults_src3 as L                 # R11: where the money is lost (Entry / Exit / Sideways)
import v2_testresults_src2b as B                 # R10: the seven Brain / exit / Dual / skipped / wick / regime / scalp families

VERSION = "v2_testresults_src 4 (R9 to R12)"
SOURCES = {"zsma": ("owl_sniper_zsma", "v2_sniper_zsma.json"), "sd_bands": ("owl_sniper_sdbands", "v2_sniper_sdbands.json"),
           "pairs": ("owl_sniper_ind_pairs", "v2_sniper_ind_pairs.json"), "combos": ("owl_sniper_combo", "v2_sniper_combo.json")}


def _used(st):
    return isinstance(st, dict) and (st.get("n") or 0) > 0


def _title(s):
    return s.replace("_", " ")


def from_kinds(fam, rep, now):
    """zsma and sd_bands: rep['kinds'][kind]['states'] (one state per regime)."""
    src, out = SOURCES[fam][1], []
    for kind, kb in (rep.get("kinds") or {}).items():
        for st in kb.get("states") or []:
            if _used(st):
                rg = st.get("regime") or "ALL"
                out.append(T.make(fam, st["state"], "%s (%s)" % (_title(kind), rg), st, kb.get("natural_decision"), context=rg, made=rep.get("made"), now=now, source=src))
    return out


def from_pairs(fam, rep, now):
    out = []
    for pair, states in (rep.get("pairs") or {}).items():
        for st in states or []:
            if _used(st):
                out.append(T.make(fam, "%s|%s" % (pair, st["state"]), "%s: %s" % (_title(pair), _title(str(st["state"]))), st, None, context=pair, made=rep.get("made"), now=now, source=SOURCES[fam][1]))
    return out


def from_combos(fam, rep, now):
    out, src = [], SOURCES[fam][1]
    for kind, kb in ((rep.get("combos") or {}).items()):
        nat = kb.get("natural_decision")
        plain = kb.get("plain_kind")
        if _used(plain):
            out.append(T.make(fam, plain["state"], "%s (plain)" % _title(kind), plain, nat, context=kind, made=rep.get("made"), now=now, source=src))
        for c in kb.get("combos") or []:
            if _used(c):
                out.append(T.make(fam, c["state"], _title(c["state"]).replace("|", " + "), c, nat, adds_value=bool(c.get("adds_value")), context=kind, made=rep.get("made"), now=now, source=src))
    return out


ADAPT = {"zsma": from_kinds, "sd_bands": from_kinds, "pairs": from_pairs, "combos": from_combos}


def collect(d, now=None):
    """-> (sorted TestResults, meta {family: {state, tests, age_sec / why}}). Never raises."""
    now = time.time() if now is None else now
    rs, meta = [], {}
    for fam in T.FAMILIES_A:
        rep = F.read_json(d, SOURCES[fam][1])
        if not rep or not rep.get("ready"):
            meta[fam] = {"state": "NOT_RUN_YET", "why": "The first study run has not finished yet (the slow loop runs it by itself)."}
            continue
        try:
            got = ADAPT[fam](fam, rep, now)
            rs += got
            meta[fam] = {"state": "OK", "tests": len(got), "age_sec": int(now - rep["made"]) if T.num(rep.get("made")) else None, "coins": rep.get("coins")}
        except Exception as e:                                   # one bad file must not hide the others
            meta[fam] = {"state": "ERROR", "why": "%s: %s" % (type(e).__name__, str(e)[:100])}
    rb, mb = B.collect(d, now)                                   # R10 (never raises)
    rl, ml = L.collect(d, now)                                   # R11 (never raises)
    rx, mx = X.collect(d, now)                                   # R12 (never raises)
    return T.sort_results(rs + rb + rl + rx), dict(meta, **mb, **ml, **mx)


def loss(d, now=None):
    """R11: the loss-source object for the Lab card (cheap read, never raises)."""
    return L.loss_source(d, now)


def exits(d, now=None):
    """R12: the exit rule table for the Lab card (cheap read, never raises)."""
    return X.exit_table(d, now)


def refresh(d, tf="5m", now=None):
    """The heavy part: build every study once and save its answer. -> {family: 'saved' / 'not ready: ...' / 'error: ...'}. Never raises."""
    now = int(time.time() if now is None else now)
    out = {}
    for fam in T.FAMILIES_A:
        try:
            mod = importlib.import_module(SOURCES[fam][0])
            rep = mod.build(d, tf)
            if not rep.get("ready"):
                out[fam] = "not ready: %s" % str(rep.get("note", ""))[:80]
            else:
                out[fam] = "saved" if F.write_json(d, SOURCES[fam][1], dict(rep, made=now)) else "not saved (folder not writable)"
        except Exception as e:
            out[fam] = "error: %s: %s" % (type(e).__name__, str(e)[:80])
    out.update(X.refresh(d, now))                                # R12: the exit rule table replay (writes only v2_lab_exit.json)
    out.update(L.refresh(d, now))                                # R11: the loss-source replay (writes only v2_lab_loss.json)
    out.update(B.refresh(d, tf, now))                            # R10: wick / regime / scalp (writes only v2_lab_results_b.json)
    return out
