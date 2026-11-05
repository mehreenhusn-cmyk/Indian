"""owl_sniper_why.py - OwlSniper R26b: the GATES CHECKLIST. READ ONLY, writes nothing, no order code.
Why: the owner could not see WHY the Sniper was quiet. This reads the saved files and answers with 8 gates, each PASS / FAIL / WAIT with one plain sentence made from real numbers, plus ONE reason line.
Gates (lane EXPLORE = the paper lane that learns, lane REAL = the 85% gate that stays locked): 1 data, 2 fresh candle, 3 market state (REAL), 4 model trained (REAL), 5 floor proven (REAL), 6 win chance (REAL), 7 risk, 8 paper lane.
EXPLORE needs gates 1, 2, 7, 8 only. REAL needs all 8 AND the executor armed. Nothing is invented: a missing file gives WAIT with the reason, never a fake PASS.
API: build(d, now) -> {gates[], explore{state,text}, real{state,text}, reason, cards, mistakes{blocked, counts}}"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_exec as EX
import owl_sniper_explore as XP
import owl_sniper_feed as F
import owl_sniper_learn as LN
import owl_sniper_mistakes as MS

VERSION = "owl_sniper_why 1 (R26b)"
FRESH_OK, FRESH_WAIT = 600, 1800            # seconds since the last EXPLORE scan: PASS / WAIT, else FAIL
EXPLORE_GATES = ("data", "fresh", "risk", "lane")


def _g(i, name, state, text, lane):
    return {"id": i, "name": name, "state": state, "text": text, "lane": lane}


def _try(fn, dflt):
    try:
        return fn()
    except Exception:
        return dflt


def build(d, now=None):
    now = time.time() if now is None else now
    live, model = F.read_json(d, F.LIVE_FILE) or {}, F.read_json(d, F.MODEL_FILE) or {}
    xp = F.read_json(d, XP.FILE) or {}
    ln, ex = _try(lambda: LN.status(d, now), {"state": "broken"}), _try(lambda: EX.status(d, now), {"ok": False})
    off = os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE))
    G = []
    if not xp:
        G.append(_g("data", "Data", "WAIT", "The EXPLORE scan has not run yet. It runs once per 5 minute candle.", "EXPLORE"))
    elif xp.get("state") != "OK" or not xp.get("scanned"):
        G.append(_g("data", "Data", "FAIL", "No coin has fresh candles (%s). Check the collector." % (xp.get("text") or xp.get("state") or "no scan"), "EXPLORE"))
    else:
        G.append(_g("data", "Data", "PASS", "%d coins scanned." % xp["scanned"], "EXPLORE"))
    age = now - int(xp.get("saved_at") or 0) if xp else None
    if age is None:
        G.append(_g("fresh", "Fresh candle", "WAIT", "No scan time yet.", "EXPLORE"))
    else:
        st = "PASS" if age <= FRESH_OK else ("WAIT" if age <= FRESH_WAIT else "FAIL")
        G.append(_g("fresh", "Fresh candle", st, "Last scan %d min ago, %d coins skipped as stale." % (age // 60, xp.get("stale") or 0), "EXPLORE"))
    ban = str(live.get("banner") or "UNKNOWN").upper()
    G.append(_g("regime", "Market state", "PASS" if ban == "TRENDING" else ("WAIT" if ban == "UNKNOWN" else "FAIL"),
                "Market is %s. The REAL gate needs TRENDING; EXPLORE ignores it." % ban.lower(), "REAL"))
    ms = model.get("status")
    G.append(_g("model", "Model trained", "PASS" if ms == "OK" else ("WAIT" if not ms else "FAIL"),
                "The win-chance model is trained." if ms == "OK" else ("The model has not run yet." if not ms else "Not trained: it needs 30 TRAIN trades. EXPLORE does not need it."), "REAL"))
    fv = live.get("floor_verified") is True
    G.append(_g("floor", "85% floor proven", "PASS" if fv else "FAIL", "Proven on the TEST days." if fv else "Not proven on the TEST days. The floor is never lowered.", "REAL"))
    cards = [c for c in (live.get("cards") or []) if isinstance(c, dict) and c.get("action") in ("SNIPER_LONG", "SNIPER_SHORT")]
    best = max([c.get("confidence") or 0.0 for c in cards] or [0.0])
    G.append(_g("conf", "Win chance", "WAIT" if not cards else ("PASS" if fv and best >= EX.FLOOR else "FAIL"),
                "No qualified signal now." if not cards else "Best win chance %.0f%% (needs %.0f%% and a proven floor)." % (best * 100, EX.FLOOR * 100), "REAL"))
    x = ln.get("xp") or {}
    kill = (ln.get("kill") or {}).get("on") or (ex.get("kill") or {}).get("on")
    if kill:
        G.append(_g("risk", "Risk", "FAIL", "A kill switch is on: %s." % ((ln.get("kill") or ex.get("kill") or {}).get("reason") or "owner"), "EXPLORE"))
    elif (x.get("day_pnl") or 0) <= -(x.get("daily_loss_cap") or LN.XP_DAILY_LOSS):
        G.append(_g("risk", "Risk", "FAIL", "Today's EXPLORE loss cap is reached. It resets on a new UTC day.", "EXPLORE"))
    elif (x.get("open") or 0) >= (x.get("max_open") or LN.XP_MAX_OPEN):
        G.append(_g("risk", "Risk", "WAIT", "%d EXPLORE trades open (the cap is full)." % x.get("open"), "EXPLORE"))
    else:
        G.append(_g("risk", "Risk", "PASS", "%d of %d EXPLORE trades open, today %+.2f USDT paper." % (x.get("open") or 0, x.get("max_open") or LN.XP_MAX_OPEN, x.get("day_pnl") or 0), "EXPLORE"))
    if off or ln.get("state") != "ok" or ln.get("enabled") is False:
        G.append(_g("lane", "Paper lane", "FAIL", "The Sniper is switched off." if off else "The LEARN / EXPLORE paper lane is off or its file is broken.", "EXPLORE"))
    else:
        G.append(_g("lane", "Paper lane", "PASS", "Paper only: %.0f USDT margin, %.0fx. Real executor %s." % (LN.XP_SIZE, LN.XP_LEV, "ARMED" if ex.get("armed") else "OFF"), "EXPLORE"))

    def lane(ids):
        bad = [g for g in G if g["id"] in ids and g["state"] != "PASS"]
        return {"state": "OPEN" if not bad else ("BLOCKED" if any(g["state"] == "FAIL" for g in bad) else "WAITING"),
                "text": "Every gate passes." if not bad else "%s: %s" % (bad[0]["name"], bad[0]["text"])}
    e, r = lane(EXPLORE_GATES), lane([g["id"] for g in G])
    if r["state"] == "OPEN" and not ex.get("armed"):
        r = {"state": "OFF", "text": "Every gate passes, but the executor is not armed (2-step Termux command)."}
    n = len(_try(lambda: XP.cards(d, now), []))
    reason = ("EXPLORE lane is open. %d fresh cards now; trades open as the paper caps allow." % n) if e["state"] == "OPEN" and n else (
        "EXPLORE lane is open, but no coin has a fresh indicator signal right now." if e["state"] == "OPEN" else "EXPLORE is quiet. " + e["text"])
    mv = MS.view(d) or {}
    return {"version": VERSION, "paper_only": True, "gates": G, "explore": e, "real": r, "reason": reason, "cards": n,
            "mistakes": {"state": mv.get("state") or "NO_TRADES_YET", "trades": mv.get("trades") or 0, "counts": mv.get("counts") or {},
                         "blocked": list((mv.get("blocked") or {}).values()), "journal": (mv.get("journal") or [])[:12], "rule": mv.get("rule")}}
