"""
ai_vision_lessons.py - the Vision AI's LEARNING NOTEBOOK.

What it is
  The AI model itself (Gemini, Mistral ...) can not change when it sees your trades. What we can build is a notebook around it:
  1. After every CLOSED Vision AI trade a one-line LESSON is written (what happened, what to repeat or avoid).
  2. Every trade also carries a few MEASURED tags read from the indicators by code (EMA agrees, TSI agrees, Z-score agrees, chop ...).
     They are numbers, not opinions, so they can be counted later.
  3. About once a day the lessons are turned into at most 3 plain-words RULES. A rule starts as "proposed" (the AI does not see it yet).
     When your own closed trades PROVE it (20+ matching trades, older and newer halves agree, and the gap beats luck) it switches itself
     ON ("auto"). If it later stops holding it pauses itself. You do not have to tap anything; Delete is still there if you want.
  4. Every rule that is linked to a tag shows its EVIDENCE: how many closed Vision trades matched, how they ended, and whether the
     older half and the newer half agree. A rule is called PROVEN only after 20+ matching trades with both halves agreeing.
     Until then the AI is told "unproven".
  5. The best lessons are shown to the AI on the next signals ("your own notebook").

Safety (same family as ai_vision.py): read-only toward the bot and the exchange. This file cannot place orders, cannot change the bot's
settings and never touches the bot's trades. Own file ai/vision_lessons.json. Every error is caught.
Honest limit: a lesson from one trade is a story, not proof. A rule from 5 trades is luck. That is why the evidence is printed next to
every rule and why nothing is switched on without your tap.
"""
import json
import re
import threading
import time

KEEP_LESSONS = 300
MIN_TRUST = 20             # matching closed trades before a rule may be called "proven" (overfit guard)
MAX_RULES = 14
DIGEST_EVERY_S = 86400
DIGEST_MIN_NEW = 5         # at least this many new lessons since the last digest
LESSON_BACKLOG_DAYS = 3

# measured tags: key -> plain words ("true" means the sentence is true at the signal candle)
TAGS = {
    "ema_agrees": "EMA30 is on the trade's side of EMA50",
    "slope_with": "EMA50 is sloping in the trade's direction",
    "tsi_agrees": "TSI is on the trade's side of its signal line",
    "tsl_with": "the TSI signal line is on the trade's side of zero",
    "z_agrees": "Z-score is on the trade's side of its Z-SMA",
    "z_sign_ok": "Z-score is above 0 for a BUY (below 0 for a SELL)",
    "stretched": "price is already beyond the 2nd SD band in the trade's direction",
    "choppy": "price crossed EMA50 3 or more times in the last 20 candles",
    # new measured tags (pump/dump + Z-SMA richer use)
    "zsma_slope_with": "Z-SMA is sloping in the trade's direction",
    "z_cross_ok": "Z recently crossed Z-SMA in the trade's direction",
    "flow_with": "the last candles (body / wick) show the trade's side in control",
    "zsma_near": "Z is close to its Z-SMA at the signal candle (the black line can act as support / resistance)",
    "zsma_bounce_with": "Z touched its Z-SMA from the trade's favourable side in the last 8 candles and moved with the trade",
    "chasing_move": "price is already at the far end of a 4%+ move in the trade's direction (chasing a pump / dump)",
}

_lock = threading.RLock()
_state = {"lessons": [], "rules": [], "skips": [], "last_digest": 0.0, "digest_seen": 0}
_file = None
_loaded = False
_dirty = False


# ------------------------------------------------------------------ storage
def init(path):
    global _file
    import os
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "vision_lessons.json")
    except Exception as e:
        print(f"[VisionLessons] init: {e}")


def _load():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            if _file:
                from . import safe_io
                d, _src = safe_io.read_json_safe(_file, "vision_lessons")
                if isinstance(d, dict):
                    for k in ("lessons", "rules", "skips"):
                        if isinstance(d.get(k), list):
                            _state[k] = d[k]
                    _state["last_digest"] = float(d.get("last_digest") or 0.0)
                    _state["digest_seen"] = int(d.get("digest_seen") or 0)
        except Exception as e:
            print(f"[VisionLessons] load: {e}")


def _save():
    global _dirty
    with _lock:
        if not _file:
            return
        try:
            from . import safe_io
            _state["lessons"] = _state["lessons"][-KEEP_LESSONS:]
            _state["skips"] = _state.get("skips", [])[-KEEP_LESSONS:]
            safe_io.write_json_atomic(_file, _state)
            _dirty = False
        except Exception as e:
            print(f"[VisionLessons] save: {e}")


def _txt(x, n=200):
    return " ".join(str(x or "").split())[:n]


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except Exception:
        return None


# ------------------------------------------------------------------ measured tags
def features(f, side):
    """f = ai_ind_features.build(candles) (arrays), measured at the LAST closed candle. -> dict of tag -> True/False (missing = unknown).
    Pure arithmetic on the indicator numbers - no AI, no opinion."""
    try:
        i = f["n"] - 1
        if i < 60:
            return {}
        buy = str(side).upper() == "BUY"
        c, e50, tsi, tsl, z, zs, sma, std = (f["c"], f["e50"], f["tsi"], f["tsl"], f["z"], f["zsma"], f["sma"], f["std"])
        out = {}

        def put(k, cond):
            if cond is not None:
                out[k] = bool(cond)

        e30 = None
        try:
            from . import ai_ind_features as F
            e30 = F.ema(c, 30, seed="sma")[i]
        except Exception:
            pass
        if e30 is not None and e50[i] is not None:
            put("ema_agrees", (e30 > e50[i]) if buy else (e30 < e50[i]))
        if e50[i] is not None and e50[i - 5] is not None:
            put("slope_with", (e50[i] > e50[i - 5]) if buy else (e50[i] < e50[i - 5]))
        if tsi[i] is not None and tsl[i] is not None:
            put("tsi_agrees", (tsi[i] > tsl[i]) if buy else (tsi[i] < tsl[i]))
            put("tsl_with", (tsl[i] > 0) if buy else (tsl[i] < 0))
        if z[i] is not None:
            put("z_sign_ok", (z[i] > 0) if buy else (z[i] < 0))
            if zs[i] is not None:
                put("z_agrees", (z[i] > zs[i]) if buy else (z[i] < zs[i]))
        if sma[i] is not None and std[i]:
            put("stretched", (c[i] > sma[i] + 2 * std[i]) if buy else (c[i] < sma[i] - 2 * std[i]))
        cross, prev = 0, None
        for j in range(i - 19, i + 1):
            if e50[j] is None:
                continue
            s = c[j] > e50[j]
            if prev is not None and s != prev:
                cross += 1
            prev = s
        put("choppy", cross >= 3)
        # Z-SMA slope + recent cross
        if zs[i] is not None and i >= 5 and zs[i - 5] is not None:
            put("zsma_slope_with", (zs[i] > zs[i - 5]) if buy else (zs[i] < zs[i - 5]))
        if z[i] is not None and zs[i] is not None:
            crossed_ok = False
            for j in range(max(1, i - 5), i + 1):
                if z[j] is None or zs[j] is None or z[j - 1] is None or zs[j - 1] is None:
                    continue
                if buy and z[j - 1] < zs[j - 1] and z[j] >= zs[j]:
                    crossed_ok = True
                if (not buy) and z[j - 1] > zs[j - 1] and z[j] <= zs[j]:
                    crossed_ok = True
            put("z_cross_ok", crossed_ok)
            # the black Z-SMA line as support / resistance for Z (side-relative)
            put("zsma_near", abs(z[i] - zs[i]) <= 0.25)
            bounce = False
            for j in range(max(1, i - 8), i):
                if None in (z[j], zs[j], z[j - 1], zs[j - 1], z[i], zs[i]):
                    continue
                if buy and z[j - 1] > zs[j - 1] and z[j] <= zs[j] + 0.1 and z[i] > zs[i] and z[i] > z[j] + 0.05:
                    bounce = True        # Z came down onto the line from above and moved back up (support held)
                if (not buy) and z[j - 1] < zs[j - 1] and z[j] >= zs[j] - 0.1 and z[i] < zs[i] and z[i] < z[j] - 0.05:
                    bounce = True        # Z came up onto the line from below and moved back down (resistance held)
            put("zsma_bounce_with", bounce)
        # recent pump/dump position
        try:
            highs = f.get("h") or []
            lows = f.get("l") or []
            if len(highs) > i and len(lows) > i and i >= 20:
                seg_h = max(highs[i - 19:i + 1])
                seg_l = min(lows[i - 19:i + 1])
                if seg_h > seg_l and seg_l > 0:
                    move = (seg_h - seg_l) / seg_l * 100.0
                    pos = (c[i] - seg_l) / (seg_h - seg_l)
                    put("chasing_move", move >= 4.0 and ((buy and pos >= 0.8) or ((not buy) and pos <= 0.2)))
        except Exception:
            pass
        return out
    except Exception:
        return {}


# ------------------------------------------------------------------ evidence for a rule
# One-sided 90% t critical values (from the "when to use t instead of z" idea): small samples need a bigger gap before we believe them.
_T90 = [(1, 3.078), (2, 1.886), (3, 1.638), (4, 1.533), (5, 1.476), (10, 1.372), (20, 1.325), (30, 1.310), (10 ** 9, 1.282)]


def _t_crit(df):
    c = _T90[0][1]
    for d, v in _T90:
        if df >= d:
            c = v
    return c


def _t_gap(a, b):
    """Welch t of mean(a) - mean(b) with its degrees of freedom. -> (t, df) or None when there are too few numbers."""
    try:
        na, nb = len(a), len(b)
        if na < 5 or nb < 5:
            return None
        ma, mb = sum(a) / na, sum(b) / nb
        va = sum((x - ma) ** 2 for x in a) / (na - 1)
        vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
        se2 = va / na + vb / nb
        if se2 <= 0:
            return None
        t = (ma - mb) / (se2 ** 0.5)
        df = se2 ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1) or 1e-12)
        return t, df
    except Exception:
        return None


def _half_ok(rows, do):
    """rows = [(closed_at, pnl)] of the matching trades. Both the older half and the newer half must point the same way."""
    rows = sorted(rows)
    if len(rows) < 4:
        return False
    h = len(rows) // 2
    a, b = sum(p for _t, p in rows[:h]), sum(p for _t, p in rows[h:])
    return (a < 0 and b < 0) if do == "skip" else (a > 0 and b > 0)


def evidence(rule, trades):
    """trades = [{"feat": {...}, "pnl": x, "closed_at": t}] of closed Vision trades. -> plain numbers + a verdict word."""
    tag = rule.get("tag")
    if not tag:
        return {"n": 0, "verdict": "no_tag", "text": "No measured tag, so it can not be counted. It stays a lesson in words."}
    want = bool(rule.get("when", True))
    m = [(t.get("closed_at") or 0, t["pnl"]) for t in trades if isinstance(t.get("feat"), dict) and t["feat"].get(tag) is want]
    o = [t["pnl"] for t in trades if isinstance(t.get("feat"), dict) and t["feat"].get(tag) is (not want)]
    n = len(m)
    net_m = sum(p for _t, p in m)
    wins = sum(1 for _t, p in m if p > 0)
    avg_m = net_m / n if n else 0.0
    avg_o = (sum(o) / len(o)) if o else 0.0
    do = rule.get("do", "skip")
    ev = {"n": n, "wins": wins, "net": round(net_m, 2), "avg": round(avg_m, 3), "others_n": len(o), "others_avg": round(avg_o, 3), "need": MIN_TRUST}
    if n < MIN_TRUST:
        ev["verdict"] = "unproven"
        ev["text"] = f"Unproven: only {n} of {MIN_TRUST} matching trades so far."
        return ev
    helps = (avg_m < avg_o and net_m < 0) if do == "skip" else (avg_m > avg_o and net_m > 0)
    both = _half_ok(m, do)
    tg = _t_gap([p for _t, p in m], o)
    sure = True
    if tg is not None:                                   # the gap must also be bigger than luck (small samples need a bigger gap)
        t, df = tg
        t = -t if do == "skip" else t
        ev["t"] = round(t, 2)
        sure = t >= _t_crit(df)
    if helps and both and sure:
        ev["verdict"] = "proven"
        ev["text"] = f"Proven on {n} trades: they ended {net_m:+.2f} USDT ({wins} wins), older and newer halves agree" + (", and the gap is bigger than luck." if tg is not None else ".")
    elif helps and both:
        ev["verdict"] = "mixed"
        ev["text"] = f"Not clear: {n} trades look {'bad' if do == 'skip' else 'good'} and both halves agree, but the gap could still be luck."
    elif helps:
        ev["verdict"] = "mixed"
        ev["text"] = f"Not clear: {n} trades look {'bad' if do == 'skip' else 'good'} overall but the older and newer halves disagree."
    else:
        ev["verdict"] = "contradicted"
        ev["text"] = f"Not supported: {n} matching trades ended {net_m:+.2f} USDT, the rule does not help."
    return ev


def _closed_with_feat(V):
    out = []
    with V._lock:
        decs = {d["id"]: d for d in V._state["dec"]}
        for t in V._state["trades"]:
            if t.get("status") == "closed" and t.get("pnl") is not None:
                if (t.get("source") or "bot") != "bot":      # own-scan trades are a different population: rules are proven on bot signals only
                    continue
                d = decs.get(t.get("dec_id")) or {}
                out.append({"feat": d.get("feat"), "pnl": float(t["pnl"]), "closed_at": t.get("closed_at") or 0})
    return out


# ------------------------------------------------------------------ lessons
_SYS_LESSON = ("You keep a trading notebook for a crypto paper-trading bot. You are given one CLOSED virtual trade with what the AI thought "
               "when it entered and how the trade ended. Write ONE short lesson in simple English (max 35 words): what to repeat or what to "
               "avoid next time, in terms of the chart and BOTH indicator families (EMA/SD and TSI/Z). "
               "Also mention if the stop was too tight/wide or if trailing the target would have captured more of the peak ROI. "
               "Be honest: if the result looks like normal market noise, say so and do not invent a cause. Never invent numbers. "
               "Answer with JSON only: "
               '{"lesson":"...","kind":"entry|stop|exit|good|noise","sl_note":"one short phrase or empty","trail_note":"one short phrase or empty"}')


def _hold_text(tr):
    try:
        m = max(0, int(((tr.get("closed_at") or 0) - (tr.get("opened_at") or 0)) / 60))
        return f"{m} min"
    except Exception:
        return "?"


def _sl_distance_text(tr, d):
    try:
        entry = float(tr.get("entry") or 0)
        sl = float(tr.get("sl") or d.get("stop") or 0)
        if not entry or not sl:
            return "SL distance unknown"
        pct = abs(entry - sl) / entry * 100.0
        return f"SL was {pct:.2f}% from entry"
    except Exception:
        return "SL distance unknown"


def _auto_lesson(tr):
    win = (tr.get("pnl") or 0) > 0
    pk = tr.get("peak_roi") or 0
    s = f"{'Won' if win else 'Lost'} {abs(tr.get('pnl') or 0):.2f} USDT; best ROI was {pk:+.1f}% and it closed at {tr.get('roi') or 0:+.1f}% ({_txt(tr.get('exit_reason'), 60)})."
    return s, ("good" if win else "noise")


def _write_one(V, tr):
    """-> True when a lesson was stored, 'quota' when the AI had no quota (try again later)."""
    with V._lock:
        d = dict(next((x for x in V._state["dec"] if x["id"] == tr.get("dec_id")), {}) or {})
    feat = d.get("feat") or {}
    tags = ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in feat.items()) or "not measured"
    notes = " | ".join(_txt(n.get("text"), 110) for n in (tr.get("notes") or [])[-5:])
    ind = d.get("indicator_summary") or {}
    ind_line = "; ".join(f"{k}={v}" for k, v in ind.items() if v) if isinstance(ind, dict) else ""
    text = (f"Trade: {_txt(tr.get('symbol'), 20)} {tr.get('side')} on {V._tf_label(tr.get('tf_min') or 5)}, held {_hold_text(tr)}.\n"
            f"Result: {tr.get('pnl') or 0:+.2f} USDT ({tr.get('roi') or 0:+.1f}% ROI after fees); best ROI during the trade {tr.get('peak_roi') or 0:+.1f}%; "
            f"closed because: {_txt(tr.get('exit_reason'), 100)}.\n"
            f"{_sl_distance_text(tr, d)}. Peak ROI {tr.get('peak_roi') or 0:+.1f}% vs final {tr.get('roi') or 0:+.1f}% "
            f"(if peak was much higher, trailing might have helped).\n"
            f"Why you entered: {_txt(d.get('reason'), 160)}\nYour entry checklist: {_txt(json.dumps(d.get('checklist') or {}), 300)}\n"
            f"Indicator summary at entry: {ind_line or 'n/a'}\n"
            f"Measured at entry (code, not opinion): {tags}.\nWhat happened while open: {notes or 'no notes'}\n"
            "Write the lesson now (JSON only).")
    V._count()
    out, err = V._call_ai(_SYS_LESSON, text, None)
    kind, lesson = None, None
    sl_note, trail_note = "", ""
    if err:
        if str(err).startswith("quota:"):
            V._uncount()
            return "quota"
        V._log(f"lesson {tr.get('symbol')}: {_txt(err, 100)}")
    else:
        j = V._parse(out) or {}
        lesson = _txt(j.get("lesson"), 220) or None
        kind = _txt(j.get("kind"), 10).lower() or None
        sl_note = _txt(j.get("sl_note"), 80)
        trail_note = _txt(j.get("trail_note"), 80)
    auto = False
    if not lesson:
        lesson, kind = _auto_lesson(tr)
        auto = True
    with _lock:
        _state["lessons"].append({"id": "l" + str(tr.get("id")), "trade_id": tr.get("id"), "symbol": tr.get("symbol"), "side": tr.get("side"),
                                  "tf": V._tf_label(tr.get("tf_min") or 5), "pnl": round(float(tr.get("pnl") or 0), 2),
                                  "roi": round(float(tr.get("roi") or 0), 1), "text": lesson, "kind": kind or "noise", "auto": auto,
                                  "sl_note": sl_note, "trail_note": trail_note,
                                  "feat": feat, "indicator_summary": ind if isinstance(ind, dict) else {},
                                  "source": tr.get("source") or "bot",
                                  "t": time.time(), "closed_at": tr.get("closed_at") or 0})
    _save()
    return True


# ------------------------------------------------------------------ rules (daily digest)
_SYS_DIGEST = ("You turn trade lessons into a few simple RULES for a crypto paper-trading bot's chart-reading AI. Rules are about when to SKIP "
               "or when to TAKE a signal. Propose at most 3 NEW rules, and only when at least 3 different lessons point the same way. "
               "If nothing repeats, return an empty list. Each rule must be plain English a non-technical trader understands. "
               "If a rule matches one of the measured tags, give that tag (exactly one of the keys given) and when=true if the rule is about "
               "the tag being true, false if about it being false; otherwise tag=null. do = skip or take. Never invent numbers. "
               'Answer with JSON only: {"rules":[{"text":"...","why":"one short sentence","tag":"key or null","when":true,"do":"skip|take"}]}')


def _digest(V):
    with _lock:
        ls = list(_state["lessons"][-40:])
        existing = [r for r in _state["rules"] if r.get("status") != "deleted"]
    lines = [f"- {x['symbol']} {x['side']} {x['tf']} {x['pnl']:+.2f} USDT [{x.get('kind')}]: {x['text']}"
             + (" (tags: " + ", ".join(f"{k}={'y' if v else 'n'}" for k, v in (x.get('feat') or {}).items()) + ")" if x.get("feat") else "")
             for x in ls]
    text = ("Measured tags you may use: " + "; ".join(f"{k} = {v}" for k, v in TAGS.items()) + ".\n\nExisting rules (do not repeat): "
            + (" / ".join(_txt(r.get("text"), 100) for r in existing) or "none") + "\n\nLessons:\n" + "\n".join(lines) + "\n\nPropose rules now (JSON only).")
    V._count()
    out, err = V._call_ai(_SYS_DIGEST, text, None)
    if err:
        if str(err).startswith("quota:"):
            V._uncount()
            return "quota"
        V._log(f"digest: {_txt(err, 100)}")
        with _lock:
            _state["last_digest"] = time.time() - DIGEST_EVERY_S + 3600      # try again in an hour
        _save()
        return False
    j = V._parse(out) or {}
    added = 0
    with _lock:
        _state["last_digest"] = time.time()
        _state["digest_seen"] = len(_state["lessons"])
        for r in (j.get("rules") or [])[:3]:
            if not isinstance(r, dict) or not _txt(r.get("text")):
                continue
            tag = r.get("tag") if r.get("tag") in TAGS else None
            do = "take" if str(r.get("do", "skip")).lower() == "take" else "skip"
            when = bool(r.get("when", True))
            txt = _txt(r.get("text"), 160)
            if any(x.get("text", "").lower() == txt.lower() or (tag and x.get("tag") == tag and x.get("when") == when and x.get("do") == do)
                   for x in _state["rules"]):
                continue
            if len([x for x in _state["rules"] if x.get("status") != "deleted"]) >= MAX_RULES:
                break
            _state["rules"].append({"id": "r" + str(int(time.time())) + str(added), "text": txt, "why": _txt(r.get("why"), 140), "tag": tag,
                                    "when": when, "do": do, "status": "proposed", "created": time.time()})
            added += 1
    _save()
    return True


# ------------------------------------------------------------------ jobs (called by ai_vision._step when it has nothing else to do)
def next_job(V):
    """Does at most ONE small job (a lesson or the daily digest). -> True if it used an AI call."""
    _load()
    now = time.time()
    with V._lock:
        done = {x.get("trade_id") for x in _state["lessons"]}
        cand = [t for t in V._state["trades"] if t.get("status") == "closed" and t.get("id") not in done
                and now - (t.get("closed_at") or 0) < LESSON_BACKLOG_DAYS * 86400]
    if cand:
        cand.sort(key=lambda t: t.get("closed_at") or 0)
        r = _write_one(V, cand[0])
        return r is True
    with _lock:
        new = len(_state["lessons"]) - _state["digest_seen"]
        due = now - _state["last_digest"] >= DIGEST_EVERY_S and new >= DIGEST_MIN_NEW
    if due:
        return _digest(V) is True
    return False


# ------------------------------------------------------------------ what the AI is shown
def prompt_block(symbol=None, side=None):
    """Text added to the AI's instructions: approved rules (with their evidence label) + a few of its own recent lessons."""
    _load()
    try:
        from . import ai_vision as V
        tr = _closed_with_feat(V)
    except Exception:
        tr = []
    _sync_status(tr)
    with _lock:
        rules = [dict(r) for r in _state["rules"] if r.get("status") in ("approved", "auto")]
        ls = list(_state["lessons"])
    if not rules and not ls:
        return ""
    out = ""
    if rules:
        out += "\n\nRULES YOU MAY USE (switched on by the owner, or switched on automatically because your own closed trades proved them; weigh any unproven one lightly):\n"
        for r in rules[:8]:
            ev = evidence(r, tr)
            label = {"proven": "PROVEN", "unproven": "unproven", "mixed": "not clear", "contradicted": "NOT supported by your trades", "no_tag": "judgement rule"}.get(ev["verdict"], "")
            out += f"- {r['text']} [{label}]\n"
    pick, seen = [], set()
    same = [x for x in reversed(ls) if symbol and x.get("symbol") == symbol and not x.get("auto")][:2]
    loss = [x for x in reversed(ls) if x["pnl"] < 0 and not x.get("auto")][:2]
    win = [x for x in reversed(ls) if x["pnl"] > 0 and not x.get("auto")][:2]
    for x in same + loss + win:
        if x["id"] not in seen:
            seen.add(x["id"])
            pick.append(x)
    if pick:
        out += ("\n\nYOUR OWN NOTEBOOK (one-line lessons from your closed trades; each is one trade's story, not proof):\n"
                + "\n".join(f"- {x['symbol']} {x['side']} {x['pnl']:+.1f} USDT: {x['text']}" for x in pick[:5]))
    return out


# ------------------------------------------------------------------ automatic rule status (no tap needed)
def _sync_status(trades):
    """proposed / paused -> auto when the evidence says PROVEN; auto -> paused when it stops holding. 'approved' (old manual tap) is kept.
    A rule without a measured tag can not be counted, so it stays a note and is never forced on the AI. Deleted stays deleted."""
    changed = False
    with _lock:
        for r in _state["rules"]:
            st = r.get("status")
            if st in ("deleted", "approved") or not r.get("tag"):
                continue
            v = evidence(r, trades).get("verdict")
            if st in ("proposed", "paused") and v == "proven":
                r["status"] = "auto"
                r["auto_at"] = time.time()
                changed = True
            elif st == "auto" and v in ("contradicted", "mixed"):
                r["status"] = "paused"
                changed = True
    if changed:
        _save()


# ------------------------------------------------------------------ indicator guide (what the AI found, in plain words)
HOW_TO = [
    ("EMA 30 / 50", ["ema_agrees", "slope_with", "choppy"],
     "EMA50 is the trend line. A BUY is cleaner when EMA30 is above EMA50 and EMA50 slopes up. When price keeps crossing EMA50 back and forth, "
     "the market is sideways and cross signals are mostly fake."),
    ("TSI", ["tsi_agrees", "tsl_with"],
     "TSI shows who is stronger, buyers or sellers. For a BUY, TSI above its signal line means buyers are gaining. "
     "The signal line above zero means the bigger push is up."),
    ("Z-score", ["z_agrees", "z_sign_ok"],
     "Z-score = how far price is from its average, counted in standard deviations (above 0 = above average). Above its Z-SMA means the push is rising. "
     "Far from 0 means stretched, so the move may be tired."),
    ("SD bands", ["stretched"],
     "SD bands are the same idea drawn on the chart: the average line and 1, 2, 3 standard deviations around it. "
     "They work as support and resistance. Price outside the 2nd band is stretched, so chasing it is risky."),
]


def _grp(rows):
    n = len(rows)
    w = sum(1 for p in rows if p > 0)
    return {"n": n, "wins": w, "avg": round(sum(rows) / n, 3) if n else 0.0}


def guide(trades):
    out = []
    for name, tags, how in HOW_TO:
        fs = []
        for tg in tags:
            yes = [t["pnl"] for t in trades if isinstance(t.get("feat"), dict) and t["feat"].get(tg) is True]
            no = [t["pnl"] for t in trades if isinstance(t.get("feat"), dict) and t["feat"].get(tg) is False]
            y, nn = _grp(yes), _grp(no)
            if y["n"] < 8 or nn["n"] < 8:
                line = f"Too few trades to say ({y['n']} with, {nn['n']} without). Needs about 8 on each side before even a hint."
                verdict = "few"
            else:
                a = evidence({"tag": tg, "when": True, "do": "take"}, trades)
                b = evidence({"tag": tg, "when": False, "do": "skip"}, trades)
                if a["verdict"] == "proven":
                    verdict, line = "good", "Looks useful: trades WITH this did better, and it held in older and newer trades."
                elif b["verdict"] == "proven":
                    verdict, line = "bad", "Looks harmful when missing: trades WITHOUT this lost, and it held in older and newer trades."
                elif y["avg"] > nn["avg"]:
                    verdict, line = "hint", "A small hint only: trades WITH this did a bit better, but it is not proven yet."
                else:
                    verdict, line = "none", "No help so far: trades WITH this were not better."
            fs.append({"tag": tg, "text": TAGS[tg], "with": y, "without": nn, "verdict": verdict, "line": line})
        out.append({"indicator": name, "how": how, "findings": fs})
    return out


# ------------------------------------------------------------------ similar past trades (the AI's memory for one signal)
def similar_block(symbol, side, feat):
    """Up to 5 closed Vision trades with the same side and the most matching measured tags -> one short text for the AI. '' if none."""
    try:
        from . import ai_vision as V
        tr = _closed_with_feat(V)
        with V._lock:
            sym_of = {t.get("dec_id"): t.get("symbol") for t in V._state["trades"]}
        if not feat:
            return ""
        scored = []
        for t in tr:
            f = t.get("feat")
            if not isinstance(f, dict) or not f:
                continue
            keys = [k for k in feat if k in f]
            if len(keys) < 4:
                continue
            same = sum(1 for k in keys if f[k] == feat[k])
            scored.append((same / len(keys), t.get("closed_at") or 0, t))
        scored = [x for x in scored if x[0] >= 0.75]
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        top = [x[2] for x in scored[:5]]
        if len(top) < 3:
            return ""
        wins = sum(1 for t in top if t["pnl"] > 0)
        net = sum(t["pnl"] for t in top)
        return (f"\n\nSIMILAR PAST SETUPS (your own closed trades with almost the same measured tags): {len(top)} found, {wins} won, "
                f"net {net:+.2f} USDT. This is a small sample: a hint, not proof.")
    except Exception:
        return ""


# ------------------------------------------------------------------ for the app
def snapshot(V):
    _load()
    tr = _closed_with_feat(V)
    _sync_status(tr)
    with _lock:
        lessons = [dict(x) for x in _state["lessons"][-30:]][::-1]
        rules = [dict(r) for r in _state["rules"] if r.get("status") != "deleted"]
        total = len(_state["lessons"])
        last_digest = _state["last_digest"]
        new = total - _state["digest_seen"]
    for r in rules:
        r["evidence"] = evidence(r, tr)
        r["tag_text"] = TAGS.get(r.get("tag") or "", "")
    for x in lessons:
        x["feat_text"] = [TAGS[k] if v else "NOT: " + TAGS[k] for k, v in (x.get("feat") or {}).items() if k in TAGS][:8]
        x.pop("feat", None)
    ss = skip_stats()
    return {"lessons": lessons, "rules": rules, "total": total, "min_trust": MIN_TRUST, "guide": guide(tr), "closed_n": len(tr),
            "next_rules_note": (f"{new} new lesson(s) since the last rule check; rules are checked about once a day after {DIGEST_MIN_NEW}+ new lessons."
                                if total else "No closed AI trade yet, so the notebook is empty."),
            "last_digest": last_digest, "skip_stats": ss}


def set_rule(rule_id, action):
    _load()
    action = str(action or "").lower()
    with _lock:
        for r in _state["rules"]:
            if r.get("id") == rule_id:
                if action == "approve":
                    r["status"] = "approved"
                elif action == "delete":
                    r["status"] = "deleted"
                elif action == "propose":
                    r["status"] = "proposed"
                else:
                    return {"ok": False, "error": "unknown action"}
                break
        else:
            return {"ok": False, "error": "rule not found"}
    _save()
    return {"ok": True}


# ------------------------------------------------------------------ skip / wait hindsight
def record_skip(dec):
    """Remember a SKIP or expired WAIT so we can later check whether skipping was correct.
    dec = decision record from ai_vision (must have symbol, side, sig_time, tf_min, reason, feat)."""
    _load()
    try:
        with _lock:
            sid = "s" + str(dec.get("id") or int(time.time() * 1000))
            _state.setdefault("skips", []).append({
                "id": sid,
                "dec_id": dec.get("id"),
                "symbol": dec.get("symbol"),
                "side": dec.get("side"),
                "tf_min": dec.get("tf_min") or 15,
                "sig_time": dec.get("sig_time") or time.time(),
                "reason": _txt(dec.get("reason"), 180),
                "decision": dec.get("decision") or "SKIP",
                "feat": dec.get("feat") or {},
                "checked": False,
                "hindsight": None,
                "t": time.time(),
            })
        _save()
        return True
    except Exception as e:
        print(f"[VisionLessons] record_skip: {e}")
        return False


def check_skip_hindsight(V, limit=20):
    """For recent unchecked skips: look at price after the signal and mark whether skip was good.
    Good skip = price moved against the side by >= 0.8% within ~8 bars (or never moved +0.8% for us).
    Bad skip = price moved in our favour by >= 1.2% within ~8 bars (we missed a winner)."""
    _load()
    with _lock:
        pending = [s for s in _state.get("skips", []) if not s.get("checked")][-limit:]
    if not pending:
        return 0
    done = 0
    for s in pending:
        try:
            tf = int(s.get("tf_min") or 15)
            age_s = time.time() - float(s.get("sig_time") or 0)
            # wait at least 8 bars after the signal
            if age_s < tf * 60 * 8:
                continue
            candles = V._fetch(s.get("symbol"), tf)
            if not candles or len(candles) < 30:
                continue
            # find candle closest to sig_time
            sig_ts = float(s.get("sig_time") or 0) * 1000  # ms if needed
            # candles timestamps are usually ms
            idx = None
            for i, c in enumerate(candles):
                ts = float(c.get("timestamp") or 0)
                if ts >= (s.get("sig_time") or 0) * (1000 if ts > 1e12 else 1) - tf * 60 * 1000:
                    idx = i
                    break
            if idx is None:
                idx = max(0, len(candles) - 12)
            entry = float(candles[idx]["close"])
            future = candles[idx + 1: idx + 9]
            if len(future) < 4:
                continue
            side = str(s.get("side") or "").upper()
            highs = [float(c["high"]) for c in future]
            lows = [float(c["low"]) for c in future]
            max_up = (max(highs) - entry) / entry * 100.0 if entry else 0
            max_dn = (min(lows) - entry) / entry * 100.0 if entry else 0
            if side == "BUY":
                fav, against = max_up, abs(min(0, max_dn))
            else:
                fav, against = abs(min(0, max_dn)), max_up
            if against >= 0.8 and fav < 1.0:
                verdict = "good_skip"
                note = f"price moved against by {against:.1f}% — skip looked correct"
            elif fav >= 1.2:
                verdict = "missed_winner"
                note = f"price moved in favour by {fav:.1f}% — skip may have been wrong"
            else:
                verdict = "neutral"
                note = f"small move (fav {fav:.1f}% / against {against:.1f}%)"
            with _lock:
                for x in _state.get("skips", []):
                    if x.get("id") == s.get("id"):
                        x["checked"] = True
                        x["hindsight"] = {"verdict": verdict, "note": note, "fav": round(fav, 2), "against": round(against, 2)}
                        break
            done += 1
        except Exception as e:
            print(f"[VisionLessons] hindsight: {e}")
    if done:
        _save()
    return done


def skip_stats():
    """Summary for the app / prompt."""
    _load()
    with _lock:
        skips = list(_state.get("skips", []))
    checked = [s for s in skips if s.get("checked") and s.get("hindsight")]
    if not checked:
        return {"n": len(skips), "checked": 0, "good": 0, "missed": 0, "neutral": 0, "text": "No skip hindsight yet."}
    good = sum(1 for s in checked if (s["hindsight"] or {}).get("verdict") == "good_skip")
    missed = sum(1 for s in checked if (s["hindsight"] or {}).get("verdict") == "missed_winner")
    neutral = len(checked) - good - missed
    text = f"Skip hindsight (n={len(checked)}): good skips {good}, missed winners {missed}, neutral {neutral}."
    return {"n": len(skips), "checked": len(checked), "good": good, "missed": missed, "neutral": neutral, "text": text}
