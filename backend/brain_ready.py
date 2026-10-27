"""brain_ready.py - Part C1: READY CHECK. One small block that answers "is the Brain good enough to be trusted with more?"

Only READS numbers the Brain view already has (trust, luck, what-if, exit hit-rate, retest, timing sync, own book) and says in plain words
which checks are true. Nothing here changes any trade. Gates (README section 6): checks 1+2+3 true = ask the owner about Brain skip;
check 4 true = ask the owner about the exit trail. ok: True = passed, False = failed, None = still collecting.
No network. Test: cd backend && python3 test_brain_ready.py
"""


def _row(key, name, ok, text, gate=True):
    return {"key": key, "name": name, "ok": ok, "text": text, "gate": gate}


def ready_check(v):
    v = v or {}
    tv, lk, fw = v.get("trust") or {}, v.get("luck") or {}, v.get("follow") or {}
    sc = (v.get("exit") or {}).get("score") or {}
    rt, tm, own = v.get("retest") or {}, v.get("timing") or {}, v.get("own") or {}
    rows = []
    tvd = tv.get("verdict")
    rows.append(_row("trust", "1. Trust meter", True if tvd == "earned" else (False if tvd == "not_yet" else None), tv.get("text") or "No data yet."))
    lvd = lk.get("verdict")
    rows.append(_row("luck", "2. Luck test", True if lvd == "solid" else (False if lvd == "luck" else None), lk.get("text") or "No data yet."))
    st = fw.get("stories") or []
    if fw.get("status") == "ready" and len(st) >= 2 and fw.get("judged", 0) >= fw.get("need", 30):
        rows.append(_row("whatif", "3. What if the bot had listened?", st[1]["total"] > st[0]["total"], fw.get("text") or ""))
    else:
        rows.append(_row("whatif", "3. What if the bot had listened?", None, "%d of %s finished trades judged." % (fw.get("judged", 0), fw.get("need", 30))))
    pct = sc.get("pct")
    rows.append(_row("exit", "4. Exit advice hit-rate", None if pct is None else pct > 60, sc.get("text") or "No opinions checked yet."))
    if rt.get("status") == "ok":
        rows.append(_row("retest", "Retest", None, "Best wait %d candles: %+.2f USDT versus entering at the signal. Part of it is only skipping signals." % (
            rt.get("wait", 0), rt.get("total_gain", 0.0)), gate=False))
    else:
        rows.append(_row("retest", "Retest", None, rt.get("text") or "No data yet.", gate=False))
    rows.append(_row("timing", "Timing sync", None, tm.get("text") or "No data yet.", gate=False))
    if own:
        nxt = ("Next stage (%s) in %d more trades." % (own.get("next_stage"), own.get("next_in", 0))) if own.get("next_stage") else "Top stage reached."
        rows.append(_row("own", "Own book", None, ("Exploring: %d of %d finished own trades (small paper size). " % (own.get("n", 0), own.get("explore_n", 30)) if own.get("exploring") else "") + "Stage %s, %d finished own trades, %+.2f USDT. %s" % (own.get("stage"), own.get("n", 0), own.get("pnl", 0.0), nxt), gate=False))
    else:
        rows.append(_row("own", "Own book", None, "No own trades yet.", gate=False))
    skip_ok = all(r["ok"] is True for r in rows[:3])
    exit_ok = rows[3]["ok"] is True
    n_true = sum(1 for r in rows[:4] if r["ok"] is True)
    if skip_ok and exit_ok:
        head = "All 4 checks are true. You can ask Claude about Brain skip and the exit trail (paper only, switch default OFF)."
    elif skip_ok:
        head = "Checks 1-3 are true. You can ask Claude about Brain skip (paper only, switch default OFF)."
    elif exit_ok:
        head = "Check 4 is true. You can ask Claude about the exit trail (paper only, switch default OFF)."
    else:
        head = "%d of 4 checks true. Not ready yet: the Brain only watches." % n_true
    return {"rows": rows, "n_true": n_true, "skip_ok": skip_ok, "exit_ok": exit_ok, "text": head}
