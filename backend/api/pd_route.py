"""api/pd_route.py - the Pump / Dump scanner routes (PD). Read-only except the two switches.
  GET  /api/pd/live          status, coins in play on each side, the last START events (the app's sound + badge read this)
  GET  /api/pd/day?day=YYYY-MM-DD   one IST day: pump list + dump list (newest first, each with its checked result) + the list of days
  GET  /api/pd/movers        Round 1 (28 Nov 2026): Naye Movers + Pehle se chal rahe (strength, chance, TSI numbers per time frame)
  GET  /api/pd/pre           Round 2 (28 Nov 2026): Taiyari me = pre-pump / pre-dump coins (price still flat, buyers / sellers arriving)
  GET  /api/pd/learning      the newest daily report, thresholds, penalties, the changes the tuner made
  POST /api/pd/toggle        {"enabled": bool} and / or {"auto_tune": bool}
Never raises: a problem answers {"state": "error", ...}. Mounted by api_server.py unless OWL_PUMPDUMP=0."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pd_config as C
import pd_runner as R
import pd_store as ST

VERSION = "api/pd_route 1 (26 Nov 2026)"
_DAYS = {"t": 0.0, "v": None}


def _day_summary(day):
    ev = ST.read_day("events", day)
    oc = ST.read_day("outcomes", day)
    out = {"day": day}
    for side in ("pump", "dump"):
        starts = [e for e in ev if e["side"] == side and e["stage"] == "START"]
        done = [o for o in oc if o["side"] == side]
        out[side] = {"events": sum(1 for e in ev if e["side"] == side), "starts": len(starts), "checked": len(done), "real": sum(1 for o in done if o.get("real"))}
    return out


def days(now=None):
    now = time.time() if now is None else now
    if _DAYS["v"] is None or now - _DAYS["t"] > 20:
        names = ST.list_days("events")
        today = C.day_of(now)
        if today not in names:
            names = [today] + names
        _DAYS["v"] = [_day_summary(d) for d in names[:14]]
        _DAYS["t"] = now
    return _DAYS["v"]


def _compact(e):
    return {"stage": e["stage"], "time": e["time"], "ts": e["ts"], "price": e["price"], "gain": e.get("gain", 0.0), "score": e.get("score", 0.0), "note": e.get("note", ""),
            "r5": e.get("r5", 0.0), "vr5": e.get("vr5", 0.0)}


def episodes(ev, side, res, pend):
    """Groups the events of ONE coin move into ONE card (Round C, 26 Nov 2026). A new episode starts when the coin had ended its last one or was silent for 90 min.
    The card keeps the fields the old per-event tile read (stage = the LAST stage, r5 / vr5 / score / price / time of the START), so an older app still shows it."""
    eps, cur = [], {}
    for e in ev:                                     # events are in time order
        if e["side"] != side:
            continue
        s = e["symbol"]
        ep = cur.get(s)
        if ep is None or ep["ended"] or e["ts"] - ep["last_ts"] > 5400:
            ep = {"id": e["id"], "symbol": s, "side": side, "day": e["day"], "ts": e["ts"], "time": e["time"], "stage": e["stage"], "started": False, "ended": False,
                  "price": e["price"], "r5": e.get("r5", 0.0), "r1": e.get("r1", 0.0), "r15": e.get("r15", 0.0), "vr5": e.get("vr5", 0.0), "vr1": e.get("vr1", 0.0),
                  "score": e.get("score", 0.0), "qv24": e.get("qv24", 0), "brk": e.get("brk", False), "flat": e.get("flat", False), "note": e.get("note", ""),
                  "gain": 0.0, "peak_gain": 0.0, "last_ts": e["ts"], "last_time": e["time"], "stages": [], "events": []}
            eps.append(ep)
            cur[s] = ep
        if e["stage"] == "START" and not ep["started"]:                  # the START numbers become the card's numbers
            ep.update(started=True, id=e["id"], ts=e["ts"], time=e["time"], price=e["price"], r5=e.get("r5", 0.0), r1=e.get("r1", 0.0), r15=e.get("r15", 0.0),
                      vr5=e.get("vr5", 0.0), vr1=e.get("vr1", 0.0), score=e.get("score", 0.0), qv24=e.get("qv24", 0), brk=e.get("brk", False), flat=e.get("flat", False),
                      note=e.get("note", ""))
        ep["stage"], ep["last_ts"], ep["last_time"] = e["stage"], e["ts"], e["time"]
        ep["gain"] = e.get("gain", 0.0)
        ep["peak_gain"] = max(ep["peak_gain"], e.get("gain", 0.0))
        if not ep["stages"] or ep["stages"][-1] != e["stage"]:
            ep["stages"].append(e["stage"])
        if e["stage"] == "END":
            ep["ended"] = True
        ep["events"].append(_compact(e))
    for ep in eps:
        if ep["started"]:
            o = res.get(ep["id"])
            if o:
                ep["result"] = {"state": "real" if o.get("real") else "fake", "pct15": o.get("pct15"), "pct30": o.get("pct30"), "pct60": o.get("pct60"), "mfe": o.get("mfe"), "mae": o.get("mae")}
            elif ep["id"] in pend:
                p = pend[ep["id"]]
                ep["result"] = {"state": "wait", "mfe": round(p.get("mfe", 0.0), 2), "mae": round(p.get("mae", 0.0), 2), "pct15": p["pct"].get("15"), "pct30": p["pct"].get("30")}
    eps.reverse()                                    # newest first
    return eps[:150]


def day_view(d=None, now=None):
    now = time.time() if now is None else now
    d = d or C.day_of(now)
    if len(d) != 10 or d[4] != "-" or d[7] != "-":
        d = C.day_of(now)
    ev = ST.read_day("events", d)
    res = {o["id"]: o for o in ST.read_day("outcomes", d)}
    pend = {}
    try:
        lr = R._R["learn"]
        if lr is not None:
            pend = {o["id"]: o for o in lr.pending}
    except Exception:
        pass
    out = {"day": d, "today": C.day_of(now), "days": days(now), "pump": episodes(ev, "pump", res, pend), "dump": episodes(ev, "dump", res, pend),
           "missed": len(ST.read_day("missed", d)), "events_n": len(ev), "view": "episodes"}
    return out


def learning():
    rep = {}
    names = sorted([n[:-5] for n in (os.listdir(C.path("reports")) if os.path.isdir(C.path("reports")) else []) if n.endswith(".json")], reverse=True)
    if names:
        rep = ST.read_json("reports/%s.json" % names[0], {})
    t = ST.read_json("tuner.json", {})
    adj = t.get("coin_adj", {})
    return {"report": rep, "report_days": names[:14], "auto_tune": t.get("auto_tune", True), "start_vol": C.get("start_vol"), "watch_vol": C.get("watch_vol"),
            "defaults": {"start_vol": C.DEFAULTS["start_vol"], "watch_vol": C.DEFAULTS["watch_vol"]}, "changes": (t.get("changes") or [])[-10:][::-1],
            "penalties": sorted([{"symbol": k, "adj": v} for k, v in adj.items() if v < 0], key=lambda x: x["adj"])[:10],
            "bonuses": sorted([{"symbol": k, "adj": v} for k, v in adj.items() if v > 0], key=lambda x: -x["adj"])[:10],
            "min_outcomes": C.get("min_outcomes")}


def toggle(body):
    done = {}
    if "enabled" in body:
        R.set_enabled(bool(body["enabled"]))
        done["enabled"] = bool(body["enabled"])
    if "auto_tune" in body:
        R.set_auto_tune(bool(body["auto_tune"]))
        done["auto_tune"] = bool(body["auto_tune"])
    return done


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return {"state": "error", "err": "%s: %s" % (type(e).__name__, str(e)[:120])}


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends, Request
    r = APIRouter()

    @r.get("/api/pd/live", dependencies=[Depends(require_api_token)])
    async def pd_live():
        return await asyncio.to_thread(_safe, R.live)

    @r.get("/api/pd/day", dependencies=[Depends(require_api_token)])
    async def pd_day(day: str = ""):
        return await asyncio.to_thread(_safe, day_view, day or None)

    @r.get("/api/pd/movers", dependencies=[Depends(require_api_token)])
    async def pd_movers():
        return await asyncio.to_thread(_safe, R.movers)

    @r.get("/api/pd/pre", dependencies=[Depends(require_api_token)])
    async def pd_pre():
        return await asyncio.to_thread(_safe, R.pre_view)

    @r.get("/api/pd/learning", dependencies=[Depends(require_api_token)])
    async def pd_learning():
        return await asyncio.to_thread(_safe, learning)

    @r.post("/api/pd/toggle", dependencies=[Depends(require_api_token)])
    async def pd_toggle(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        return await asyncio.to_thread(_safe, toggle, body if isinstance(body, dict) else {})

    return r
