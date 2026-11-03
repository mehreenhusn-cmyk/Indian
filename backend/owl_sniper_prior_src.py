"""owl_sniper_prior_src.py - OwlSniper PRIOR KNOWLEDGE READER (Part 36 / FILE 44). READ ONLY: it calls the study modules the owner already has and writes NOTHING, no network, no order code, no trading import. It only collects and renames.
The owner has run MANY backtests and studies; the results sit as raw data. This file gathers them into ONE plain list, one row per finding: what was tested, how many cases (n), the date, and the verdict. Sniper uses them as PRIOR knowledge only (FILE 45): nothing here is trusted blindly, Sniper re-tests on fresh data first (n >= 30 rule).
ROW = {id, source, kind, what, n, date, age_sec, verdict, line, entry_known, lean}
  verdict (one word): EDGE (proven: enough cases, older and newer half agree) / HINT (looks good, not proven) / AVOID (reliably goes the wrong way: a "do not take") / NO_EDGE / LOSING / DIAGNOSIS_ONLY (describes what happened, not usable at entry) / NOT_ENOUGH_DATA.
  kind: study = Study Lab card | exit = which exit rule | entry_filter = enter only when confirmed | level = SD level / Z-SMA behaviour | management = what the Brain should do inside a trade.
  entry_known: True when the finding is about something known AT ENTRY (usable as an entry candidate), False when it is about the exit or about managing an open trade, None when the source does not say. Only entry_known findings can become entry candidates.
  date / age_sec: only when the source gives a time (the Study Lab cards do); otherwise date = null, never a guess.
SOURCES (each in its own try / except: one broken source never stops the others; the answer says which source worked):
  cards  = v2_verdicts.build() (Study Lab: results, setups, stop-wick, zones, squeeze, limits, playbook ...). Their verdict words are kept.
  exit   = recovered_bot.ai_exit_study.build(), level = ai_level_study.build(), wait = ai_wait_study.build(). These are REPLAYS / event counts on real candles, never live trades: their best word is HINT, never EDGE. They live in the running backend (Shadow Lab in memory): from the command line they usually say NOT_ENOUGH_DATA or unavailable, that is true, not an error.
  brain  = brain_stats.run(DATA) (what happened after each Brain state, measured on closed trades, walk-forward). Uses run(), which writes nothing (refresh() would). SUPPORTED = EDGE, EARLY HINT = HINT, NO CLEAR PATTERN = NO_EDGE.
Mapping rules are plain and listed in each adapter. A source that gives no verdict word gets NOT_ENOUGH_DATA, never a guess. Nothing from different books is added: every row keeps its own source.
API: from_cards(res, now), from_exit(out), from_level(out), from_wait(out), from_brain(out), collect(d, now=None, only=None), summary(res). CLI:
  python3 backend/owl_sniper_prior_src.py --data DIR [--only cards,brain] [--json]"""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_prior_src 1 (Part 36)"
VERDICTS = ("EDGE", "HINT", "AVOID", "NO_EDGE", "LOSING", "DIAGNOSIS_ONLY", "NOT_ENOUGH_DATA")
SOURCES = ("cards", "exit", "level", "wait", "brain")
MIN_EDGE_N = 100                           # fewer cases never give EDGE (same number as the Study Lab rule)


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _int(v):
    x = _num(v)
    return int(x) if x is not None else 0


def _row(rid, source, kind, what, n, verdict, line, date=None, age=None, entry_known=None, lean=None):
    return {"id": "%s:%s" % (source, rid), "source": source, "kind": kind, "what": what, "n": _int(n), "date": date, "age_sec": age,
            "verdict": verdict if verdict in VERDICTS else "NOT_ENOUGH_DATA", "line": line, "entry_known": entry_known, "lean": lean}


def _day(ts):
    t = _num(ts)
    if t is None or t <= 0:
        return None
    return time.strftime("%Y-%m-%d", time.gmtime(t / 1000.0 if t > 1e11 else t))


def from_cards(res, now=None):
    """Study Lab cards (v2_verdicts.build) -> rows. The verdict word of the card is kept as it is (EDGE / NO_EDGE / LOSING / NOT_ENOUGH_DATA / DIAGNOSIS_ONLY)."""
    now = time.time() if now is None else now
    out = []
    for c in (res or {}).get("cards") or ():
        if not isinstance(c, dict):
            continue
        ago = _num(c.get("updated_ago_sec"))
        ago = int(ago) if ago is not None and ago >= 0 else None
        n = c.get("n") or c.get("have_n") or 0
        line = str(c.get("headline") or "").strip() or "No headline."
        out.append(_row(c.get("id"), "cards", "study", str(c.get("title") or c.get("id")), n, c.get("verdict"), line, _day(now - ago) if ago is not None else None, ago))
    return out


def from_exit(out):
    """ai_exit_study.build() -> rows. CLEAR = HINT (a replay is never EDGE), MAYBE = DIAGNOSIS_ONLY, SAME (the bot's hold is fine) = NO_EDGE. Fewer signals than the study needs = one NOT_ENOUGH_DATA row."""
    out = out if isinstance(out, dict) else {}
    tf, sig = str(out.get("tf") or "?"), _int(out.get("signals"))
    if out.get("status") != "OK":
        why = "needs more signals" if out.get("status") == "TOO_FEW" else "the study gave an error (%s)" % str(out.get("error") or "unknown")[:60]
        return [_row("overall_" + tf, "exit", "exit", "Exit rule study (%s)" % tf, sig, "NOT_ENOUGH_DATA", "Exit rule study on %s: %d signals, %s." % (tf, sig, why), entry_known=False)]
    nice, rows = out.get("nice") or {}, []
    mp = {"CLEAR": "HINT", "MAYBE": "DIAGNOSIS_ONLY", "SAME": "NO_EDGE"}
    for s in out.get("scenarios") or ():
        v, best, gain = mp.get(s.get("verdict"), "NOT_ENOUGH_DATA"), s.get("best"), _num(s.get("gain")) or 0.0
        if v == "NO_EDGE":
            line = "%s: the bot's own hold is fine (%d signals)." % (s.get("label"), _int(s.get("n")))
        else:
            line = "%s: exit '%s' beat the bot's hold by %+.1f ROI points over %d signals%s (replay)." % (s.get("label"), nice.get(best, best), gain, _int(s.get("n")), ", older and newer half agree" if s.get("stable") else ", not stable yet")
        rows.append(_row("%s_%s" % (tf, s.get("label")), "exit", "exit", "Exit rule in: %s (%s)" % (s.get("label"), tf), s.get("n"), v, line, entry_known=False))
    return rows or [_row("overall_" + tf, "exit", "exit", "Exit rule study (%s)" % tf, sig, "NO_EDGE", "Exit rule study on %s: no exit rule beat the bot's hold in any scenario with enough signals." % tf, entry_known=False)]


def from_level(out):
    """ai_level_study.build() -> rows (SD level / Z-SMA events, counted on candles). GOOD = HINT (an event count is never EDGE), BAD = AVOID, NO_EDGE = NO_EDGE, COLLECTING = NOT_ENOUGH_DATA."""
    out = out if isinstance(out, dict) else {}
    if out.get("status") != "OK":
        n = _int(out.get("n"))
        return [_row("overall", "level", "level", "SD level / Z-SMA events", n, "NOT_ENOUGH_DATA", "SD level / Z-SMA study: %d events so far, %d needed." % (n, _int(out.get("need")) or 60), date=_day(out.get("ts")), entry_known=True)]
    mp, rows = {"GOOD": "HINT", "BAD": "AVOID", "NO_EDGE": "NO_EDGE", "COLLECTING": "NOT_ENOUGH_DATA"}, []
    for it in (out.get("levels") or []) + (out.get("situations") or []):
        v, rate = mp.get(it.get("verdict"), "NOT_ENOUGH_DATA"), _num(it.get("rate")) or 0.0
        act = {"HINT": "level held / followed", "AVOID": "level broke / failed", "NO_EDGE": "no clear lean"}.get(v, "not enough events")
        rows.append(_row(it.get("label"), "level", "level", "Price at %s" % it.get("label"), it.get("n"), v, "%s: %s (%.0f%% good of %d events%s)." % (it.get("label"), act, rate, _int(it.get("n")), ", older and newer half agree" if v in ("HINT", "AVOID") else ""), date=_day(out.get("ts")), entry_known=True))
    return rows


def from_wait(out):
    """ai_wait_study.build() -> ONE row: 'enter only when not sideways AND Z and TSI both agree'. CLEAR = HINT, MAYBE = DIAGNOSIS_ONLY, NO = NO_EDGE, TOO_FEW = NOT_ENOUGH_DATA."""
    out = out if isinstance(out, dict) else {}
    tf, n = str(out.get("tf") or "?"), _int(out.get("signals"))
    v = {"CLEAR": "HINT", "MAYBE": "DIAGNOSIS_ONLY", "NO": "NO_EDGE"}.get(out.get("verdict"), "NOT_ENOUGH_DATA")
    c = out.get("confirm") or {}
    if v == "NOT_ENOUGH_DATA":
        line = "Enter-only-when-confirmed study (%s): %d signals so far, not enough yet." % (tf, n)
    else:
        line = "Enter only when not sideways and Z + TSI agree (%s): avg %+.1f%% vs the bot's %+.1f%%, %d signals skipped (replay)." % (tf, _num(c.get("keep_avg")) or 0.0, _num(c.get("bot_avg")) or 0.0, _int(c.get("skip_n")))
    return [_row("confirm_" + tf, "wait", "entry_filter", "Enter only when confirmed (%s)" % tf, n, v, line, entry_known=True)]


def from_brain(out):
    """brain_stats.run() -> rows, one per Brain state (STRONG / STABLE / WEAKENING / REVERSED) with enough trades, plus the sliced ones. SUPPORTED = EDGE, EARLY HINT = HINT, NO CLEAR PATTERN = NO_EDGE, NOT ENOUGH DATA = NOT_ENOUGH_DATA. These are about managing an OPEN trade (hold or leave), so entry_known is False."""
    out = out if isinstance(out, dict) else {}
    mp, rows = {"SUPPORTED": "EDGE", "EARLY HINT": "HINT", "NO CLEAR PATTERN": "NO_EDGE", "NOT ENOUGH DATA": "NOT_ENOUGH_DATA"}, []
    groups = [("all trades", out.get("states") or {})] + [(str(g.get("slice")), g.get("states") or {}) for g in (out.get("slices") or [])[1:] if isinstance(g, dict)]
    for sl, states in groups:
        for key, r in states.items():
            if not isinstance(r, dict):
                continue
            v = mp.get(r.get("verdict"), "NOT_ENOUGH_DATA")
            if sl != "all trades" and v == "NOT_ENOUGH_DATA":
                continue
            lean = r.get("lean") or None
            line = str(r.get("text") or "").strip() or "Brain state %s: %s." % (key, v)
            rows.append(_row("%s_%s" % (sl, key), "brain", "management", "Brain state %s (%s)" % (r.get("name") or key, sl), r.get("n"), v, line, entry_known=False, lean=lean))
    return rows


def _src_cards(d, now):
    import v2_verdicts as VD
    return from_cards(VD.build(d, now), now)


def _src_ai(name, fn):
    from recovered_bot import ai_exit_study, ai_level_study, ai_wait_study
    mod = {"exit": ai_exit_study, "level": ai_level_study, "wait": ai_wait_study}[name]
    return fn(mod.build())


def _src_brain(d):
    import brain_stats as BS
    out = BS.run(d)
    if out.get("err"):
        raise RuntimeError(out["err"])
    return from_brain(out)


def collect(d, now=None, only=None):
    """-> {rows, counts, sources {name: {state, rows, note}}, made}. Never raises; every source is isolated."""
    now = time.time() if now is None else now
    want = [s for s in (only or SOURCES) if s in SOURCES]
    jobs = {"cards": lambda: _src_cards(d, now), "exit": lambda: _src_ai("exit", from_exit), "level": lambda: _src_ai("level", from_level), "wait": lambda: _src_ai("wait", from_wait), "brain": lambda: _src_brain(d)}
    rows, info = [], {}
    for s in want:
        try:
            got = jobs[s]()
            rows.extend(got)
            info[s] = {"state": "ok", "rows": len(got), "note": ""}
        except ImportError as e:
            info[s] = {"state": "unavailable", "rows": 0, "note": "module not found here (%s)" % str(e)[:60]}
        except Exception as e:
            info[s] = {"state": "error", "rows": 0, "note": "%s: %s" % (type(e).__name__, str(e)[:80])}
    return {"version": VERSION, "rows": rows, "counts": {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}, "sources": info, "report_only": True, "made": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now))}


def summary(res):
    """Plain lines for the owner: one per source, then the counts."""
    out = []
    for s, i in (res.get("sources") or {}).items():
        out.append("%s: %s, %d findings%s" % (s, i["state"], i["rows"], (" (%s)" % i["note"]) if i["note"] else ""))
    c = res.get("counts") or {}
    out.append("Verdicts: " + ", ".join("%s %d" % (v, c.get(v, 0)) for v in VERDICTS))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper prior knowledge reader (read only)")
    ap.add_argument("--data", required=True)
    ap.add_argument("--only", default="", help="comma list of: " + ",".join(SOURCES))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = collect(a.data, only=[x.strip() for x in a.only.split(",") if x.strip()] or None)
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print("\n".join(summary(res)))
        for r in res["rows"]:
            print("[%s] %s | n=%d | %s" % (r["verdict"], r["what"], r["n"], r["line"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
