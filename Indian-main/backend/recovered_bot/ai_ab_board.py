"""
ai_ab_board.py - the RESEARCH SCOREBOARD: the bot as it is vs the same bot if it also read
(B) the TSI, (C) the Z-score / SD relationship, (D) both together, (E) anything the AI finds.

The live strategy is NOT touched (EMA50 cross entry, candle SL, 200-SD TPs, TP1 -> breakeven). The
Shadow Lab replays that exact strategy on real candles and saves, for every signal, what BOTH
indicator views showed and how the trade ended. This module only READS those rows and asks:
"if the signals in a scenario had been skipped, what would the net result be?"

Phase 1 added: Z vs its own average line, Z/price divergence, sideways-vs-trending, and a Z-and-TSI
agreement fact. They exist only for signals saved after this update (older rows simply lack them).

Families of facts (the AI may only use the facts of a version's family):
  TSI      TSI position, TSI vs its signal line, TSI with / against the trade, momentum, reversal arrow
  Z / SD   Z zone, Z direction, WHY Z moves (price / average / SD), PRICE-vs-Z relationship
           (price WITH/AGAINST the trade  x  Z WITH/AGAINST the trade, over 3 and 10 candles),
           SD shape, SD size, which SD zone the entry is in.  Z/SD is a core dimension, equal to TSI.
  Main     EMA slope turn, regime, volume, phase, direction     (used by E only)
  Higher TF 5m/15m/1h/2h trend, TSI, EMA slope, agreement, Top-10 side   (used by E only)
Versions:  A bot (all signals) | B TSI facts only | C Z/SD facts only |
           D scenarios that need one TSI fact AND one Z/SD fact together | E any facts.

How a version's rule is made: loser scenarios (1-2 facts, up to 3 rules) are mined on OLDER signals
only; a scenario must be clearly worse than average in both halves of that older data. It is then
scored on signals it never saw.  Two views:
  forward  - rules FROZEN when the test starts (first open, or reset()); only later signals scored.
  history  - instant check: rules mined on the older 60% of the saved replay, scored on the newer 40%.
Every version reports: net ROI (fee already inside), trades, wins, original SL losses, TP1..TP4
reached, TP1->breakeven exits, losses avoided, good trades skipped, drawdown, luck test.

Safety: READ-ONLY. Reads Shadow Lab rows, writes only ai_ab_state.json. Never touches orders,
positions, settings or any trading decision. Never raises.
"""
import json
import os
import random
import threading
import time

from . import ai_ind_features as F
from . import ai_shadow_lab as L
from . import ai_rowcache as RC

LIVE_RULE = L.LIVE_RULE
DAY_MS = 86_400_000
MIN_TRAIN = 120
MIN_EVAL = 30
MIN_GAP = 1.0            # a loser scenario must be this many ROI points below the average signal
MAX_RULES = 3
LUCK_RUNS = 300
_CACHE_S = 60
STATE_VER = 2

FAM_TSI = frozenset(("tsi_pos", "tsi_vs_sig", "tsi_4zone", "tsi_vs_trade", "momentum", "warning"))
FAM_ZSD = frozenset(("z_zone", "z_move", "z_why", "z_why10", "z_recent", "pz3", "pz10",
                     "sd_shape", "sd_size", "sd_zone", "zma_vs_trade", "z_div"))
FAM_MAIN = frozenset(("ema_turn", "regime", "volume", "phase", "direction", "move"))
FAM_BOTH = frozenset(("z_tsi",))      # one fact that already compares Z and TSI (counts for version D alone)
_HTF_PREFIX = ("htf_", "htfs_", "htft_", "mtf_agree", "market")

VERSIONS = (("tsi", "B. Bot + TSI"), ("zsd", "C. Bot + Z / SD"),
            ("both", "D. Bot + TSI + Z/SD together"), ("ai", "E. AI khud dhundha (sab facts)"))

_lock = threading.RLock()
_recs_cache = {"key": None, "v": []}
_out_cache = {}
_hist_cache = {}         # tf -> (key, history block, relation): the slow part of a build, re-done only every _HIST_STEP signals
_HIST_STEP = 150


def _cfg(name, default):
    try:
        return L._cfg(name, default)
    except Exception:
        return default


def _kind(tok):
    return tok.split("=", 1)[0]


def _in_fam(tok, fam):
    return _kind(tok) in fam


def _any_kind(tok):
    k = _kind(tok)
    return k in FAM_TSI or k in FAM_ZSD or k in FAM_MAIN or k in FAM_BOTH or k.startswith(_HTF_PREFIX)


# ------------------------------------------------------------------ state file
def _state_path():
    d = getattr(L, "_dir", None)
    return os.path.join(d, "ai_ab_state.json") if d else None


def _save_state(st):
    try:
        p = _state_path()
        if p:
            tmp = p + ".tmp"
            with open(tmp, "w") as f:
                json.dump(st, f)
            os.replace(tmp, p)
    except Exception:
        pass


def _state():
    """{'ver', 'start_ms', 'rules': {tf: {version: [[token, ...], ...]}}} - created on first use."""
    with _lock:
        st = None
        try:
            p = _state_path()
            if p and os.path.exists(p):
                with open(p, "r") as f:
                    st = json.load(f)
        except Exception:
            st = None
        if not isinstance(st, dict) or not isinstance(st.get("start_ms"), int):
            st = {"ver": STATE_VER, "start_ms": int(time.time() * 1000), "rules": {}}
            _save_state(st)
        if st.get("ver") != STATE_VER or not isinstance(st.get("rules"), dict):
            st["ver"], st["rules"] = STATE_VER, {}      # older rule format: mine again (start time kept)
            _save_state(st)
        return st


def reset():
    """Start a fresh forward test from now (rules are mined again from everything older)."""
    with _lock:
        _save_state({"ver": STATE_VER, "start_ms": int(time.time() * 1000), "rules": {}})
        _out_cache.clear()
        _hist_cache.clear()
    return build()


# ------------------------------------------------------------------ data
def _pz(ind, action, sfx, zeps, peps):
    zp, zm, zs = ind.get("zp" + sfx), ind.get("zm" + sfx), ind.get("zs" + sfx)
    if zp is None or zm is None or zs is None:
        return None
    d = 1 if str(action).upper() == "BUY" else -1
    dz = zp + zm + zs
    p = "flat" if abs(zp) <= peps else ("WITH" if zp * d > 0 else "AGAINST")
    z = "flat" if abs(dz) <= zeps else ("WITH" if dz * d > 0 else "AGAINST")
    return f"Price {p} / Z {z}"


def _recs(tf, lev, fee):
    """Finished lab signals of one timeframe, oldest first. {'t', 's': frozenset(tokens), 'v': net ROI %,
    'w': how the live rule ended (TP/SL/BE/REV/TIMEOUT), 'r': (TP1, TP2, TP3, TP4 reached)}.
    Rows come from the shared slim reader (ai_rowcache) - the big file is not parsed here any more."""
    key = (RC.version(), tf, lev, fee)
    with _lock:
        if _recs_cache["key"] == key:
            return _recs_cache["v"]
    out = []
    for r in RC.rows(tf):
        try:
            o = r["o"]
            if LIVE_RULE not in o:
                continue
            toks = frozenset(f"{k}={v}" for k, v in r["f"].items() if _any_kind(f"{k}="))
            out.append({"t": r["t"], "s": toks, "v": L._net(o[LIVE_RULE][0], lev, fee),
                        "w": o[LIVE_RULE][1],
                        "r": tuple(1 if (("T%d" % i) in o and o["T%d" % i][1] == "TP") else 0 for i in (1, 2, 3, 4))})
        except Exception:
            continue
    with _lock:
        _recs_cache.update(key=key, v=out)
    return out


# ------------------------------------------------------------------ mining (OLD data only)
def _mine_avoid(train, pick):
    """Up to MAX_RULES loser scenarios from `train`. pick(a, b) says whether a 1- or 2-fact scenario
    is allowed: pick(tok, None) for singles, pick(tok1, tok2) for pairs."""
    n = len(train)
    if n < MIN_TRAIN:
        return []
    base = sum(r["v"] for r in train) / n
    cut = int(n * 0.6)
    minn = max(25, int(n * 0.04))
    idx = {}
    for i, r in enumerate(train):
        for t in r["s"]:
            idx.setdefault(t, set()).add(i)
    cands = {}

    def test(key, ids):
        if len(ids) < minn:
            return
        a = [train[i]["v"] for i in ids if i < cut]
        b = [train[i]["v"] for i in ids if i >= cut]
        if len(a) < 10 or len(b) < 10:
            return
        avg = (sum(a) + sum(b)) / len(ids)
        if avg > base - MIN_GAP or sum(a) / len(a) > base or sum(b) / len(b) > base:
            return
        cands[key] = ids

    avg_of = lambda t: sum(train[i]["v"] for i in idx[t]) / len(idx[t])
    ok1 = [t for t in idx if len(idx[t]) >= minn and pick(t, None)]
    for t in ok1:
        test((t,), idx[t])
    pool = sorted((t for t in idx if len(idx[t]) >= minn), key=avg_of)[:45]
    for x in range(len(pool)):
        for y in range(x + 1, len(pool)):
            a, b = pool[x], pool[y]
            if _kind(a) == _kind(b) or not (pick(a, b) or pick(b, a)):
                continue
            test((a, b), idx[a] & idx[b])
    chosen, skipped = [], set()
    for _ in range(MAX_RULES):
        best, best_gain = None, 5.0
        for key, ids in cands.items():
            if key in chosen:
                continue
            gain = -sum(train[i]["v"] for i in ids if i not in skipped)
            if gain > best_gain:
                best, best_gain = key, gain
        if best is None:
            break
        chosen.append(best)
        skipped |= cands[best]
    return chosen


def _pickers():
    both = lambda a, b: ((b is None and _in_fam(a, FAM_BOTH))
                         or (b is not None and ((_in_fam(a, FAM_TSI) and _in_fam(b, FAM_ZSD))
                                                or (_in_fam(a, FAM_ZSD) and _in_fam(b, FAM_TSI))
                                                or (_in_fam(a, FAM_BOTH) and (_in_fam(b, FAM_TSI) or _in_fam(b, FAM_ZSD)))
                                                or (_in_fam(b, FAM_BOTH) and (_in_fam(a, FAM_TSI) or _in_fam(a, FAM_ZSD))))))
    return {"tsi": lambda a, b: _in_fam(a, FAM_TSI) and (b is None or _in_fam(b, FAM_TSI)),
            "zsd": lambda a, b: _in_fam(a, FAM_ZSD) and (b is None or _in_fam(b, FAM_ZSD)),
            "both": both,
            "ai": lambda a, b: True}


def _mine_all(train):
    return {k: [list(x) for x in _mine_avoid(train, pk)] for k, pk in _pickers().items()}


def _label(key):
    return "  +  ".join(x.split("=", 1)[1] if "=" in x else x for x in key)


# ------------------------------------------------------------------ scoring
def _drawdown(rs):
    peak = cur = dd = 0.0
    for r in rs:
        cur += r["v"]
        peak = max(peak, cur)
        dd = max(dd, peak - cur)
    return dd


def _pct(k, n):
    return (k / n * 100.0) if n else 0.0


def _line(name, title, ev, skip):
    taken = [r for r in ev if not (skip and skip(r))]
    cut = [r for r in ev if skip and skip(r)]
    n = len(taken)
    net = sum(r["v"] for r in taken)
    wins = sum(1 for r in taken if r["v"] > 0)
    good = [r["v"] for r in cut if r["v"] > 0]
    d = {"key": name, "title": title, "n": n, "wins": wins, "win_rate": _pct(wins, n),
         "net": net, "avg": (net / n) if n else 0.0,
         "sl": sum(1 for r in taken if r["w"] == "SL"), "be": sum(1 for r in taken if r["w"] == "BE"),
         "tp": [sum(r["r"][i] for r in taken) for i in range(4)],
         "other": sum(1 for r in taken if r["w"] in ("REV", "TIMEOUT", "OPEN")),
         "drawdown": _drawdown(taken),
         "skipped": len(cut), "saved": -sum(r["v"] for r in cut),
         "loss_avoided": -sum(r["v"] for r in cut if r["v"] < 0),
         "good_lost_n": len(good), "good_lost": sum(good), "luck_pct": None}
    if len(cut) >= 5 and len(ev) > len(cut):
        rnd = random.Random(11)
        vals = [r["v"] for r in ev]
        k = len(cut)
        hit = sum(1 for _ in range(LUCK_RUNS) if -sum(rnd.sample(vals, k)) >= d["saved"])
        d["luck_pct"] = hit / LUCK_RUNS * 100.0
    return d


def _verdict(bot, ln, total):
    if total < MIN_EVAL or ln["n"] < 10:
        return {"code": "TOO_FEW", "text": "Abhi data kam hai - result pe bharosa mat karo."}
    if ln["net"] > bot["net"]:
        if ln["luck_pct"] is not None and ln["luck_pct"] <= 10:
            return {"code": "BETTER", "text": "Profit badha aur luck ke chance kam hain."}
        return {"code": "MAYBE", "text": "Profit badha, par luck bhi ho sakta hai - aur data chahiye."}
    return {"code": "WORSE", "text": "Is se faida nahi hua (bot akela behtar ya barabar)."}


def _rule_info(key, train, ev, bot_ev, bot_train):
    """Measured facts about one scenario (no guessing): how its signals ended before (train) and after (ev)."""
    def hit(rs):
        return [r for r in rs if all(t in r["s"] for t in key)]
    tr, te = hit(train), hit(ev)

    def agg(rs):
        n = len(rs)
        return {"n": n, "avg": (sum(r["v"] for r in rs) / n) if n else 0.0, "win": _pct(sum(1 for r in rs if r["v"] > 0), n),
                "sl": _pct(sum(1 for r in rs if r["w"] == "SL"), n), "tp1": _pct(sum(r["r"][0] for r in rs), n)}
    a_tr, a_te, b_te = agg(tr), agg(te), agg(bot_ev)
    why = (f"Train me {a_tr['n']} signals, avg {a_tr['avg']:+.1f}%. Naye data me {a_te['n']} signals, avg {a_te['avg']:+.1f}% "
           f"(sab signals ka avg {b_te['avg']:+.1f}%). SL {a_te['sl']:.0f}% (sab: {b_te['sl']:.0f}%), "
           f"TP1 tak {a_te['tp1']:.0f}% (sab: {b_te['tp1']:.0f}%).")
    return {"label": _label(key), "train": a_tr, "eval": a_te, "why": why}


def _block(ev, train, rules):
    bot = _line("bot", "A. Bot akela (sab signals)", ev, None)
    lines = [bot]
    for k, title in VERSIONS:
        keys = [tuple(x) for x in (rules.get(k) or [])]
        ln = _line(k, title, ev, (lambda r, keys=keys: any(all(t in r["s"] for t in kk) for kk in keys)) if keys else None)
        ln["verdict"] = _verdict(bot, ln, len(ev)) if keys else \
            {"code": "NO_RULE", "text": "Pakka loser scenario nahi mila (data kam ya koi pattern hold nahi hua)."}
        ln["rules"] = [_rule_info(kk, train, ev, ev, train) for kk in keys]
        lines.append(ln)
    return {"n": len(ev), "from_ms": ev[0]["t"] if ev else None, "to_ms": ev[-1]["t"] if ev else None, "lines": lines}


# ------------------------------------------------------------------ the relationship table
def _relation(recs, kind):
    """Price-vs-Z (x TSI with/against the trade): how signals ended in each combination."""
    n = len(recs)
    cut = int(n * 0.6)
    groups = {}
    for i, r in enumerate(recs):
        pz = next((t for t in r["s"] if t.startswith(kind + "=")), None)
        ts = next((t for t in r["s"] if t.startswith("tsi_vs_trade=")), None)
        if pz and ts:
            groups.setdefault((pz.split("=", 1)[1], ts.split("=", 1)[1]), []).append((i, r))
    rows = []
    for (pz, ts), g in groups.items():
        if len(g) < 8:
            continue
        rs = [r for _, r in g]
        new = [r for i, r in g if i >= cut]
        m = len(rs)
        rows.append({"price_z": pz, "tsi": ts, "n": m, "win_rate": _pct(sum(1 for r in rs if r["v"] > 0), m),
                     "avg": sum(r["v"] for r in rs) / m, "sl": _pct(sum(1 for r in rs if r["w"] == "SL"), m),
                     "be": _pct(sum(1 for r in rs if r["w"] == "BE"), m), "tp1": _pct(sum(r["r"][0] for r in rs), m),
                     "n_new": len(new), "avg_new": (sum(r["v"] for r in new) / len(new)) if new else None})
    rows.sort(key=lambda x: -x["n"])
    return rows


# ------------------------------------------------------------------ public API
_build_lock = threading.RLock()     # one heavy build at a time (RLock: build() calls itself for the other tf)


def _norm_tf(tf):
    """The timeframe a request really means (same rule _build uses)."""
    tf = tf if tf in L.SIGNAL_TFS else str(_cfg("timeframe", "3m"))
    return tf if tf in L.SIGNAL_TFS else "3m"


def build(tf="", _deep=True):
    """Public entry. If another request is already building, answer from the last finished result OF THE SAME
    TIMEFRAME. Never from another timeframe (that used to show 3m numbers under the 5m / 15m chip). If this timeframe
    has no finished result yet, answer {"building": true} at once, so the app shows "Building 5m..." and asks again.
    Only the very first start-up call (warm) waits for the lock."""
    tf = _norm_tf(tf)
    if not _build_lock.acquire(blocking=False):
        try:
            with _lock:
                hit = _out_cache.get(tf)
            if hit and (hit[1].get("insight") is not None or not _deep):
                return hit[1]
        except Exception:
            pass
        return {"tf": tf, "building": True, "ts": time.time(), "history": None, "forward": None, "relation": {},
                "insight": None, "why": "Another timeframe is being calculated right now. This one is next."}
    try:
        return _build(tf, _deep)
    finally:
        _build_lock.release()


def warm():
    """Called once in the background after start-up so the first time the A/B tab opens it is instant."""
    try:
        build("")
    except Exception:
        pass


def _build(tf="", _deep=True):
    """The whole research scoreboard for one timeframe (default = the bot's timeframe). Never raises."""
    try:
        tf = _norm_tf(tf)
        with _lock:
            hit = _out_cache.get(tf)
            if hit and time.time() - hit[0] < _CACHE_S and (hit[1].get("insight") is not None or not _deep):
                return hit[1]
        lev = float(_cfg("leverage", 1) or 1)
        fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
        recs = _recs(tf, lev, fee)
        st = _state()
        now = int(time.time() * 1000)
        out = {"tf": tf, "leverage": lev, "signals": len(recs), "now_ms": now,
               "started_ms": st["start_ms"], "days": (now - st["start_ms"]) / DAY_MS,
               "lab": {}, "history": None, "forward": None, "relation": {},
               "caveats": ["Replay on real candles, not live trading: no slippage, orders always filled.",
                           "ROI = price move x leverage, app fee already inside every trade. Equal margin per trade.",
                           "Signals in the same market move are not independent - trust a result only when the "
                           "sample is big and the luck chance is low.",
                           "Ye sirf dekhna hai: koi rule live trading me lagaya nahi gaya."]}
        try:
            stt = L.status()
            out["lab"] = {"phase": stt.get("phase"), "pending": stt.get("pending"), "rows": stt.get("rows")}
        except Exception:
            pass
        n = len(recs)
        if n >= MIN_TRAIN + MIN_EVAL:
            cut = int(n * 0.6)
            hk = (tf, n // _HIST_STEP)          # history only changes slowly: redo it every _HIST_STEP new signals
            with _lock:
                hh = _hist_cache.get(tf)
            if hh and hh[0] == hk:
                out["history"], out["relation"] = hh[1], hh[2]
            else:
                out["history"] = _block(recs[cut:], recs[:cut], _mine_all(recs[:cut]))
                out["relation"] = {"pz3": _relation(recs, "pz3"), "pz10": _relation(recs, "pz10")}
                with _lock:
                    _hist_cache[tf] = (hk, out["history"], out["relation"])
        start = st["start_ms"]
        train = [r for r in recs if r["t"] < start]
        ev = [r for r in recs if r["t"] >= start]
        frozen = st["rules"].get(tf)
        if not isinstance(frozen, dict) and len(train) >= MIN_TRAIN:
            frozen = _mine_all(train)
            with _lock:
                st["rules"][tf] = frozen
                _save_state(st)
        out["forward"] = _block(ev, train, frozen if isinstance(frozen, dict) else {})
        if _deep:
            out["insight"] = _insight(tf, out, ev)
        with _lock:
            _out_cache[tf] = (time.time(), out)
        return out
    except Exception as e:
        return {"tf": tf, "error": f"{type(e).__name__}: {e}", "history": None, "forward": None, "relation": {}}


# ------------------------------------------------------------------ the simple "Insights" answer
IST_MS = 19_800_000             # day borders in Indian time
MIN_LIVE = 100                  # signals after the test started, before any upgrade talk
_STAGES = ("Stage 1: sirf shadow (abhi)", "Stage 2: paper me filter, chhoti size", "Stage 3: live, chhoti size",
           "Stage 4: poori size")


def _cand_line(blk):
    """Best of B..E by net ROI advantage over the bot, among lines that have a rule."""
    if not blk:
        return None, None
    lines = blk.get("lines") or []
    bot = lines[0] if lines else None
    best = None
    for ln in lines[1:]:
        if not ln.get("rules"):
            continue
        if best is None or ln["net"] > best["net"]:
            best = ln
    return bot, best


def _day_check(ev, keys):
    """On how many different days did skipping the rule's scenarios save money, and is one day most of it?"""
    per = {}
    for r in ev:
        if any(all(t in r["s"] for t in kk) for kk in keys):
            d = (r["t"] + IST_MS) // DAY_MS
            per[d] = per.get(d, 0.0) - r["v"]
    good = [v for v in per.values() if v > 0]
    total = sum(good)
    top_share = (max(good) / total) if total > 0 else 1.0
    return len(good), top_share


def _insight(tf, out, ev):
    """One plain answer: will the filter help, how sure are we, and the safe-to-upgrade checklist.
    Only measured numbers; the 'bharosa' word is just how many checklist ticks passed (not a probability)."""
    fwd, his = out.get("forward"), out.get("history")
    nf = fwd["n"] if fwd else 0
    use_fwd = nf >= MIN_EVAL
    src = fwd if use_fwd else his
    bot, cand = _cand_line(src)
    res = {"source": "forward" if use_fwd else ("history" if his else "none"), "tf": tf,
           "days": out.get("days"), "new_signals": nf, "candidate": None, "checks": [], "ticks": 0,
           "status": "MORE_DATA", "trust": "KAM", "kyun": [], "relation": [],
           "stage": {"now": 1, "allowed": 1, "names": list(_STAGES), "text": _STAGES[0]}}
    if not src or not bot:
        res["lines"] = ["Abhi pura data nahi aaya.", "Shadow Lab signals jama kar raha hai.", "Thoda wait karo."]
        res["checks"] = [{"ok": False, "t": "Abhi data hi nahi aaya"}]
        return res
    if cand is None:
        res["lines"] = [f"Bot akela: {bot['net']:+.0f}% ROI ({bot['n']} signals).",
                        "AI ko abhi koi pakka loser scenario nahi mila.",
                        "Bharosa: KAM - aur data chahiye."]
        res["checks"] = [{"ok": False, "t": "Koi pakka rule nahi mila"}]
        return res
    frozen = _state()["rules"].get(tf) or {}
    real = [tuple(x) for x in (frozen.get(cand["key"]) or [])]
    days_ok, top_share = _day_check(ev, real) if real else (0, 1.0)
    other = [x for x in L.SIGNAL_TFS if x != tf]
    agree = []
    for o_tf in other:
        try:
            ob = build(o_tf, _deep=False).get("forward")
            b2, c2 = (None, None)
            if ob and ob["n"] >= MIN_EVAL:
                b2 = ob["lines"][0]
                c2 = next((x for x in ob["lines"] if x.get("key") == cand["key"] and x.get("rules")), None)
            agree.append(bool(c2 and b2 and c2["net"] > b2["net"]))
        except Exception:
            agree.append(False)
    main_ok = use_fwd
    luck = cand.get("luck_pct")
    checks = [
        {"ok": nf >= MIN_LIVE, "t": f"Test shuru hone ke baad {MIN_LIVE}+ signals (abhi {nf})"},
        {"ok": bool(main_ok and cand["net"] > bot["net"]), "t": "Naye data pe (jo AI ne dekha nahi) filter bot se behtar"},
        {"ok": bool(main_ok and luck is not None and luck <= 10), "t": "Luck ka chance 10% se kam"
         + (f" (abhi {luck:.0f}%)" if luck is not None else "")},
        {"ok": bool(main_ok and cand["drawdown"] <= bot["drawdown"]), "t": "Drawdown (sabse bada giraav) bot se zyada nahi"},
        {"ok": bool(main_ok and cand["good_lost"] < cand["loss_avoided"]), "t": "Galat skip hue achhe trade < bache hue loss"},
        {"ok": bool(main_ok and days_ok >= 2 and top_share <= 0.7), "t": "Kam se kam 2 alag din me kaam kiya, sirf ek din ki move nahi"},
        {"ok": bool(main_ok and any(agree)), "t": "Doosre timeframe (3m/5m/15m) me bhi same result"},
    ]
    ticks = sum(1 for c in checks if c["ok"])
    worse = bool(main_ok and nf >= MIN_LIVE and cand["net"] <= bot["net"])
    status = "READY" if ticks == len(checks) else ("NO" if worse else "MORE_DATA")
    trust = "ZYADA" if ticks == len(checks) else ("MEDIUM" if ticks >= 5 else "KAM")
    allowed = 2 if status == "READY" else 1
    diff = cand["net"] - bot["net"]
    span = out.get("days") or 0
    where = f"{nf} naye signals, {span:.1f} din" if use_fwd else "purane data ka check (live test abhi chhota hai)"
    res.update({
        "status": status, "trust": trust, "ticks": ticks,
        "candidate": {"key": cand["key"], "title": cand["title"], "net": cand["net"], "bot_net": bot["net"],
                      "diff": diff, "n": cand["n"], "bot_n": bot["n"], "skipped": cand["skipped"],
                      "loss_avoided": cand["loss_avoided"], "good_lost_n": cand["good_lost_n"],
                      "good_lost": cand["good_lost"], "drawdown": cand["drawdown"], "bot_drawdown": bot["drawdown"],
                      "luck_pct": luck, "days_ok": days_ok},
        "lines": [f"Bot akela: {bot['net']:+.0f}% ROI ({where}).",
                  f"{cand['title'].split('. ', 1)[-1]}: {cand['net']:+.0f}% ROI, farq {diff:+.0f}%, "
                  f"{cand['skipped']} signal skip, {cand['good_lost_n']} achhe trade bhi gaye.",
                  f"Bharosa: {trust} ({ticks}/{len(checks)} checks pass)."],
        "checks": checks,
        "final": {"READY": "Abhi upgrade karna theek hai (pehle paper me chhoti size se).",
                  "NO": "Abhi upgrade karna theek nahi hai - naye data pe filter behtar nahi nikla.",
                  "MORE_DATA": "Abhi aur data chahiye - filter live me mat lagao."}[status],
        "stage": {"now": 1, "allowed": allowed, "names": list(_STAGES), "text": _STAGES[allowed - 1]},
        "kyun": [{"label": r_["label"], "why": r_["why"]} for r_ in cand["rules"][:3]],
        "relation": [{"price_z": x["price_z"], "tsi": x["tsi"], "n": x["n"], "avg": x["avg"], "win_rate": x["win_rate"]}
                     for x in ((out.get("relation") or {}).get("pz3") or [])[:4]],
    })
    return res
