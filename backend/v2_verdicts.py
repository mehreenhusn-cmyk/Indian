"""v2_verdicts.py - Round 3: ONE VERDICT CARD PER STUDY (the heart of the redesign). The app shows these cards on top of Study Lab and as the header of every study screen.
Card = {id, title, verdict, headline (12 words max), detail, n, caveat, reason_missing, updated_ago_sec, need_n, have_n, eta_text, next_action}. updated_ago_sec = -1 means unknown.
verdict is one of EDGE / NO_EDGE / LOSING / NOT_ENOUGH_DATA / DIAGNOSIS_ONLY. Rules (owner + AI_HANDOFF_BRIEF):
  * Only groups known AT ENTRY (side, hour, coin, timeframe, zone, higher-timeframe trend) may give EDGE. How the trade ended / how long it was open = diagnosis text only.
  * EDGE needs n >= 100 and the same sign in the older and the newer half. LOSING = net after fee negative with n >= 100. Fewer = NOT_ENOUGH_DATA.
  * Setup Finder and Stop-wick are replays without fees: NEVER EDGE. No clear gap to their own baseline = NO_EDGE; a clear gap = DIAGNOSIS_ONLY (unproven).
  * A card that cannot decide never says only "not enough data": it says WHAT is missing, have_n of need_n, WHEN (eta_text from the real rate, else "unknown") and WHAT TO DO (next_action).
  * Any exception inside one study = that card becomes NOT_ENOUGH_DATA with the reason. The text "None" never appears (missing = "n/a").
A new study = ONE register() call (id, title, function); its card appears automatically. Read-only: own saved files + the market store opened mode=ro. No network, no write, no trading import."""
import calendar
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_limits as LM
import v2_bt_playbook as PB
import v2_bt_zonestudy as ZS
import v2_results as RS
import v2_setup_forward as SW
import v2_store as S
import v2_wickstudy as WK

VERSION = "v2_verdicts 3 (Round 6)"
VERDICTS = ("EDGE", "NO_EDGE", "LOSING", "NOT_ENOUGH_DATA", "DIAGNOSIS_ONLY")
MIN_N, MIN_PLAYBOOK, CLEAR_GAP, MIN_BASE, DAYS, MAX_WORDS = 100, 30, 0.20, 30, 3, 12
ENTRY_DIMS, AFTER_DIMS = ("side", "hour", "coin", "tf", "zone", "htf"), ("exit", "hold")
REGISTRY = []


def register(cid, title, fn):
    """Add a study. fn(ctx) -> partial card dict (verdict, headline, detail, n, ...). Same id twice = the newer one replaces the older."""
    REGISTRY[:] = [r for r in REGISTRY if r[0] != cid] + [(cid, title, fn)]


def fmt(x, nd=2, plus=False):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x:
        return "n/a"
    return ("%" + ("+" if plus else "") + ".%df" % nd) % x


def _i(x):
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x else 0


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _scrub(v):
    return re.sub(r"\bNone\b", "n/a", v) if isinstance(v, str) else v


def eta_text(have, need, per_day=None):
    if have >= need:
        return "ready now"
    if _num(per_day) and per_day > 0:
        d = (need - have) / per_day
        return "about %d hour(s) at the real rate" % max(1, round(d * 24)) if d < 2 else "about %d day(s) at the real rate" % round(d)
    return "unknown (no real rate yet)"


def nod(headline, reason, have, need, act, eta=None, n=0):
    return {"verdict": "NOT_ENOUGH_DATA", "headline": headline, "detail": reason, "reason_missing": reason, "have_n": have, "need_n": need, "n": n, "next_action": act,
            "eta_text": eta or eta_text(have, need)}


def finish(cid, title, part, now):
    """Every card has exactly the same keys, no None, a legal verdict word and a headline of 12 words at most."""
    c = {"id": cid, "title": title, "verdict": "NOT_ENOUGH_DATA", "headline": "", "detail": "", "n": 0, "caveat": "", "reason_missing": "", "updated_ago_sec": -1,
         "need_n": 0, "have_n": 0, "eta_text": "", "next_action": ""}
    c.update({k: v for k, v in part.items() if k in c and v is not None})
    if c["verdict"] not in VERDICTS:
        c["verdict"], c["reason_missing"] = "NOT_ENOUGH_DATA", "the study returned an unknown verdict word"
    for k in ("n", "need_n", "have_n"):
        c[k] = _i(c[k])
    c["updated_ago_sec"] = _i(c["updated_ago_sec"]) if _num(c["updated_ago_sec"]) else -1
    if c["verdict"] == "NOT_ENOUGH_DATA":
        c["reason_missing"] = c["reason_missing"] or "the study gave no reason"
        c["next_action"] = c["next_action"] or "open the study screen for details"
        c["eta_text"] = c["eta_text"] or eta_text(c["have_n"], c["need_n"])
    c = {k: _scrub(v) for k, v in c.items()}
    if not c["headline"] or len(c["headline"].split()) > MAX_WORDS:
        c["headline"] = "%s: %s" % (title, c["verdict"].replace("_", " ").lower())
    return c


def _ago(now, ts):
    return max(0, int(now - ts)) if _num(ts) else -1


def _load_json(path):
    try:
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > 8_000_000:
            return None
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def open_ro(data_dir):
    path = S.store_path(data_dir)
    if not os.path.isfile(path):
        return None
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    return con


def _span_rate(first, last, n):
    try:
        a, b = (calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M")) for s in (first, last))
        return n / ((b - a) / 86400.0) if b - a >= 3600 else None
    except (TypeError, ValueError):
        return None


def _worst(box, keys, only_losing):
    best = None
    for dm in box.get("dims") or []:
        if dm.get("key") in keys:
            for r in dm.get("rows") or []:
                if (not only_losing or r.get("verdict") == "LOSING") and _num(r.get("net_usdt")) and (best is None or r["net_usdt"] < best[1]["net_usdt"]):
                    best = (dm, r)
    return best


def c_results(x):
    d = RS.build(x["dir"])
    if not d.get("ready") or not d.get("order"):
        return nod("No closed trades yet", d.get("note") or "No closed trades were found in the data folder.", 0, MIN_N, "let the bot or the paper Brain close trades first")
    b = d["boxes"][d["order"][0]]                                   # the box with most trades; the boxes are never added together
    o, n = b["overall"], b["overall"]["n"]
    net, h1, h2 = o["net_usdt"], o["older_half_usdt"], o["newer_half_usdt"]
    if n < MIN_N:
        return nod("Only %d closed trades so far" % n, "%d closed trades, net %s USDT. Need %d before a verdict." % (n, fmt(net, 2, True), MIN_N), n, MIN_N,
                   "keep trading; check again later", eta_text(n, MIN_N, _span_rate(b.get("first_close_utc"), b.get("last_close_utc"), n)), n)
    if net < 0:
        v, head = "LOSING", "Bot lost %s USDT over %d trades" % (fmt(-net), n)
    elif net > 0 and h1 > 0 and h2 > 0:
        v, head = "EDGE", "Bot made %s USDT over %d trades" % (fmt(net), n)
    else:
        v, head = "NO_EDGE", "No steady profit or loss over %d trades" % n
    parts = ["Net %s USDT after fee, win rate %s%%, older half %s, newer half %s." % (fmt(net, 2, True), fmt(o["win_pct"], 1), fmt(h1, 2, True), fmt(h2, 2, True))]
    leak, after = _worst(b, ENTRY_DIMS, True), _worst(b, AFTER_DIMS, False)
    if leak:
        parts.append("Biggest steady leak known at entry: %s = %s (%d trades, %s USDT)." % (leak[0]["title"], leak[1]["label"], leak[1]["n"], fmt(leak[1]["net_usdt"], 2, True)))
    if after:
        parts.append("After the trade (diagnosis only, not a filter): %s = %s, %s USDT." % (after[0]["title"], after[1]["label"], fmt(after[1]["net_usdt"], 2, True)))
    return {"verdict": v, "headline": head, "detail": " ".join(parts), "n": n, "need_n": MIN_N, "have_n": n, "caveat": "closed trades, net of fee: %s" % b.get("title", "one box"),
            "updated_ago_sec": _ago(x["now"], _span_utc(b.get("last_close_utc")))}


def _span_utc(s):
    try:
        return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M"))
    except (TypeError, ValueError):
        return None


def _descriptive(x, rep, noun):
    if not rep.get("ready"):
        return nod("No %s data yet" % noun, "No coin has clean saved candles in the last %d days (collector off or too few candles)." % DAYS, 0, MIN_N, "run: python3 backend/v2_candles.py --status", n=0)
    base, clear, best_n, first_n = rep.get("baseline") or {}, [], 0, 0
    for t in rep.get("types") or []:
        for h, cell in (t.get("horizons") or {}).items():
            n, b = _i(cell.get("n")), base.get(h) or {}
            best_n = max(best_n, n)
            first_n += n if h == (rep.get("horizons") or [h])[0] else 0
            m, bm = cell.get("median_end_pct"), b.get("median_end_pct")
            if n >= MIN_N and _i(b.get("n")) >= MIN_BASE and _num(m) and _num(bm) and abs(m - bm) >= CLEAR_GAP:
                clear.append((abs(m - bm), str(t.get("type") or noun).replace("_", " "), h, m, bm, n))
    cav = "replay of saved candles, no fees, nothing proven"
    if best_n < MIN_N:
        return nod("Too few %s cases yet" % noun, "The biggest group has %d cases; %d are needed to compare it with ordinary candles." % (best_n, MIN_N), best_n, MIN_N,
                   "run: python3 backend/v2_candles_deep.py --plan, then wait for more candles", n=first_n)
    if not clear:
        return {"verdict": "NO_EDGE", "headline": "No %s beats ordinary candles" % noun, "n": first_n, "need_n": MIN_N, "have_n": best_n, "caveat": cav,
                "detail": "Every group with %d+ cases ends within %.2f points of the ordinary-candle median (last %d days)." % (MIN_N, CLEAR_GAP, DAYS)}
    clear.sort(reverse=True)
    g, name, h, m, bm, n = clear[0]
    return {"verdict": "DIAGNOSIS_ONLY", "headline": "%s differs from ordinary candles, unproven" % name.lower(), "n": first_n, "need_n": MIN_N, "have_n": best_n, "caveat": cav,
            "detail": "%s after %s: median end %s%% vs %s%% for ordinary candles (%d cases). %d group(s) differ in all. No fees, no proof." % (name, h, fmt(m, 2, True), fmt(bm, 2, True), n, len(clear))}


def c_setups(x):
    return _descriptive(x, SW.build(x["con"], x["now"], DAYS), "formation") if x["con"] else nod("No market store yet", "The candle store does not exist.", 0, MIN_N, "run: python3 backend/v2_candles.py --on")


def c_stopwick(x):
    return _descriptive(x, WK.build_forward(x["con"], x["now"], DAYS), "wick") if x["con"] else nod("No market store yet", "The candle store does not exist.", 0, MIN_N, "run: python3 backend/v2_candles.py --on")


def _left_out(d):
    c = {}
    for s in d.get("skipped") or []:
        w = str((s or {}).get("why") or "reason not saved")
        c[w] = c.get(w, 0) + 1
    top = sorted(c.items(), key=lambda kv: -kv[1])[:2]
    n = sum(c.values())
    return "" if not n else "%d coin(s) left out: %s" % (n, "; ".join("%s x%d" % kv for kv in top) if len(top) > 1 else top[0][0])


def _gate(x, name, cmd):
    d = _load_json(cmd[1](x["dir"], "5m"))
    if d is None:
        return None, nod("%s not made yet" % name, "The saved study file is missing.", 0, ZS.MIN_COINS, "run: python3 backend/%s run" % cmd[0])
    if not d.get("coins"):
        return d, nod("%s has 0 usable coins" % name, _left_out(d) or "No coin was usable.", 0, ZS.MIN_COINS,
                      "run: python3 backend/v2_candles_deep.py --once, then python3 backend/%s run" % cmd[0], n=0)
    return d, None


def _candidates(d, rows, cases, name, describe, cav):
    use, avoid = [r for r in rows if r.get("verdict") == "USE"], [r for r in rows if r.get("verdict") == "AVOID"]
    base = {"n": cases, "need_n": MIN_N, "have_n": cases, "caveat": cav, "updated_ago_sec": None}
    big = [r for r in use if _i(r.get("n")) >= MIN_N]
    if big:
        return dict(base, verdict="EDGE", headline="%s: %d group(s) positive in both halves" % (name, len(big)), detail="%s %d groups were checked at once, so some win by luck." % (describe(big[0]), _i(d.get("groups_checked"))))
    if cases < MIN_N and not (use or avoid):
        return nod("%s has too few cases" % name, "%d cases from %d coin(s); %d are needed." % (cases, len(d.get("coins") or []), MIN_N), cases, MIN_N, "wait for more candles, then run the study again", n=cases)
    c = (use + avoid)[:1]
    return dict(base, verdict="NO_EDGE", headline="%s: no proven edge" % name, detail=("Candidate (not proven): %s" % describe(c[0])) if c else "No group is better than the baseline in both TRAIN and HOLDOUT.")


def c_zone(x):
    d, bad = _gate(x, "Zone study", ("v2_bt_zonestudy.py", ZS.cache_path))
    if bad:
        return bad
    desc = lambda r: "%s side, SD zone %s, %s: %d cases, mean net %s R (TRAIN %s, HOLDOUT %s)." % (r.get("side", "n/a"), r.get("zone", "n/a"), "all states" if r.get("state") == "ALL" else r.get("state", "n/a"), _i(r.get("n")),
                                                                                                fmt(r.get("mean_net_r"), 2, True), fmt(r.get("train_net_r"), 2, True), fmt(r.get("holdout_net_r"), 2, True))
    out = _candidates(d, d.get("rows") or [], _i(d.get("cases")), "Zone study", desc, "hypothetical trades on saved candles, fee included, many groups checked")
    out["updated_ago_sec"] = _ago(x["now"], d.get("made_ts"))
    return out


def c_squeeze(x):
    d, bad = _gate(x, "Squeeze study", ("v2_bt_limits.py", LM.cache_path))
    if bad:
        return bad
    desc = lambda r: "squeeze break %s, %s: %d cases, mean net %s R (TRAIN %s, HOLDOUT %s)." % (r.get("dir", "n/a"), r.get("group", "n/a"), _i(r.get("n")), fmt(r.get("mean_net_r"), 2, True), fmt(r.get("train_net_r"), 2, True), fmt(r.get("holdout_net_r"), 2, True))
    out = _candidates(d, d.get("squeeze_rows") or [], _i(d.get("squeeze_ends")), "Squeeze study", desc, "hypothetical trades on saved candles, many groups checked")
    out["updated_ago_sec"] = _ago(x["now"], d.get("made_ts"))
    return out


def c_limits(x):
    d, bad = _gate(x, "Limits study", ("v2_bt_limits.py", LM.cache_path))
    if bad:
        return bad
    rows, entries = d.get("limit_rows") or [], _i(d.get("entries"))
    better = [r for r in rows if r.get("verdict") == "BETTER CANDIDATE"]
    cav = "%d limit rows checked at once, a few look good by luck; nothing is applied without your OK" % _i(d.get("limit_rows_checked"))
    base = {"n": entries, "need_n": MIN_N, "have_n": entries, "caveat": cav, "updated_ago_sec": _ago(x["now"], d.get("made_ts"))}
    if entries < MIN_N:
        return dict(nod("Limits study has too few trades", "%d replayed entries; %d are needed." % (entries, MIN_N), entries, MIN_N, "wait for more candles, then run: python3 backend/v2_bt_limits.py run", n=entries), caveat=cav)
    if not better:
        return dict(base, verdict="NO_EDGE", headline="No limit set clearly beats the reference", detail="%d limit rows were compared with the reference limits; none gained enough in both TRAIN and HOLDOUT." % max(0, len(rows) - 1))
    r = better[0]
    return dict(base, verdict="NO_EDGE", headline="Limits study: one candidate, not proven", detail="Candidate (not proven): stop %s SD, target %s R, hold %s candles: mean net %s %%, %s %% better than the reference, %d cases." % (
        r.get("stop_sd", "n/a"), r.get("target_r", "n/a"), r.get("hold", "n/a"), fmt(r.get("mean_net_pct"), 3, True), fmt(r.get("diff_pct"), 3, True), _i(r.get("n"))))


def c_playbook(x):
    d = PB.build_playbook(x["dir"], "PAPER", x["now"], None, None)
    if not d.get("ready"):
        return nod("No Brain trades yet", str(d.get("note") or "No Brain Trader file yet."), 0, MIN_PLAYBOOK, "restart the backend; the first Brain tick comes in about 5 minutes")
    tot = _i(d.get("total_closed"))
    if tot < MIN_PLAYBOOK:
        return nod("Playbook needs %d closed trades" % MIN_PLAYBOOK, "The Brain has %d closed paper trades; %d are needed before any state gets a USE or AVOID." % (tot, MIN_PLAYBOOK), tot, MIN_PLAYBOOK, "let the Brain keep trading on paper", n=tot)
    use = [r for b in d.get("blocks") or [] for r in b.get("use") or []]
    avoid = [r for b in d.get("blocks") or [] for r in b.get("avoid") or []]
    big = [r for r in use if _i(r.get("n")) >= MIN_N]
    cav = "paper trades net of fee and slippage; %d states checked at once, some look good by luck" % _i(d.get("checked"))
    pick = lambda r: "%s = %s: %d trades, net %s USDT." % (r.get("dim_title", "n/a"), r.get("label", "n/a"), _i(r.get("n")), fmt(r.get("net_usdt"), 2, True))
    base = {"n": tot, "need_n": MIN_PLAYBOOK, "have_n": tot, "caveat": cav, "updated_ago_sec": 0}
    if big:
        return dict(base, verdict="EDGE", headline="%d state(s) made money in both halves" % len(big), detail="USE when " + pick(big[0]))
    c = (use + avoid)[:1]
    return dict(base, verdict="NO_EDGE", headline="Playbook: no proven state yet", detail=("Candidate (not proven): " + pick(c[0])) if c else "No state has 30+ trades with the same sign in both halves.")


for _id, _title, _fn in (("results", "Bot results", c_results), ("setup_finder", "Setup Finder", c_setups), ("stopwick", "Stop-wick study", c_stopwick), ("zone", "Zone study", c_zone),
                         ("squeeze", "Squeeze study", c_squeeze), ("limits", "Limits study", c_limits), ("playbook", "Indicator Playbook", c_playbook)):
    register(_id, _title, _fn)

for _mod in ("v2_verdict_studies_a", "v2_verdict_studies_b"):     # Rounds 5 + 6: more studies, one register() call each
    try:
        __import__(_mod)
    except Exception as _e:               # a broken study module becomes ONE visible card, never a crash
        register(_mod[-9:], "More studies (%s)" % _mod[-1].upper(), lambda x, _n=type(_e).__name__, _m=_mod: nod("More studies could not load", "%s failed to import (%s)." % (_m, _n), 0, 0, "send the error name to Claude"))


def build(data_dir, now=None):
    """-> {ready, cards, counts, made_utc}. Never raises: a study that fails becomes a NOT_ENOUGH_DATA card with the reason."""
    now = int(time.time() if now is None else now)
    con = None
    try:
        con = open_ro(data_dir)
    except (sqlite3.Error, OSError, S.StoreRefused):
        con = None
    x, cards = {"dir": data_dir, "now": now, "con": con}, []
    try:
        for cid, title, fn in REGISTRY:
            try:
                part = fn(x)
            except Exception as e:
                part = nod("%s could not be checked" % title, "The study failed (%s)." % type(e).__name__, 0, 0, "open the study screen; send the error name to Claude")
            cards.append(finish(cid, title, part if isinstance(part, dict) else {}, now))
    finally:
        if con is not None:
            con.close()
    counts = {v: sum(1 for c in cards if c["verdict"] == v) for v in VERDICTS}
    return {"ready": True, "framework": VERSION, "cards": cards, "counts": counts, "made_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)),
            "note": "Read-only. A verdict is evidence, not an order. EDGE needs 100+ cases and the same sign in both halves."}
