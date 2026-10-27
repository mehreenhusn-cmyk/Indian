"""brain_edge.py - Batch 3a: OPEN TRADE EDGE DECAY (observation / report only).

Question it answers for every OPEN Dual trade: "the reason we took this trade, is it still valid?"
It only READS the candles + indicators Dual Bot already built (S and Z in dual_lab.process) and writes ONE key, `edge`,
on the trade dict. It never closes, changes or rejects a trade, never reads a price feed, never calls an AI / API.
The words STRONG / STABLE / WEAKENING / REVERSED are PROVISIONAL labels (a first guess, not a proven prediction).
The raw numbers are stored too, so the labels can be retuned later without losing history. Once per NEW closed candle.

edge keys (d = +1 buy / -1 sell; every "with trade" number is multiplied by d, so + = with the trade):
  v    edge version ("e1")            lt   open time of the candle this was measured on     n  candles since entry
  f0   candles since entry at the FIRST observation (old open trades start late, nothing is back-filled)
  st   state word                     txt  one short line for the app           pg  progress word (progressing/stalling/reversing)
  sc   support now (0-6)   s0 at entry   s3 three candles ago   sw  the 6 reasons now as "110111" (see REASONS)
  zv   price Z in SD units (with trade)   zs  its change over 3 candles
  th   TSI histogram (with trade)         ths its change over 3 candles       tv  TSI value (with trade)
  wd   SD width change over 5 candles in %  (+ expanding, - contracting)
  ed   price distance to EMA50 in SD units (with trade)   es  EMA50 slope over 5 candles in SD units (with trade)
  ev   events since entry [opposite EMA50 cross, opposite Z candle, reversal-warning arrow]   ea  candles since the latest event (None = none)
  pm   [price momentum 5, Z momentum 5, TSI momentum 5] signs (+1 / -1 / 0)   ag  1 = price and Z agree, 0 = they disagree
  roi  ROI now = net after fee (same number as `live`), mfe best, gb given back (ROI points, leverage in, gross, same basis as Batch 2)   ma  candles since MFE last improved
  hs   one state letter per observation (S strong, T stable, W weakening, R reversed, N new, ? unknown), newest last
  hc   support count per observation (digits)   hr  ROI per observation   hz  zv per observation   (all capped at MAX_HIST)
  done 1 once the trade has closed (observation ended)
"""
import time

EDGE_VERSION = "e1"
MAX_HIST = 60                # observations kept per trade (about 0.8 KB of history)
NEW_BARS = 2                 # fewer closed candles since entry than this = NEW (too early to say)
SLOPE_K, WIDTH_K = 3, 5      # candles for the short slope, and for the width / EMA / momentum comparison
RECENT = 3                   # an opposite event / warning arrow counts as "now" for this many candles
PROG_R = 0.15                # progress: ROI change over SLOPE_K candles, in units of the trade's own risk (R)
GB_MIN_R, GB_FRAC = 0.5, 0.5 # "giveback over half of a real MFE": MFE must be at least this many R first
WIDTH_EPS = 5.0              # SD width change in % below which it is "flat"
REASONS = ("tsi_line", "tsi_zero", "z_ema", "cloud", "zsm", "ema50")
STATE_LETTER = {"STRONG": "S", "STABLE": "T", "WEAKENING": "W", "REVERSED": "R", "NEW": "N", "UNKNOWN": "?"}
HIST_KEYS = ("hs", "hc", "hr", "hz")
SCORE_MIN = 30               # closed trades with history needed before the scorecard gives a number
MAX_LIST = 60                # open trades listed in the report


def _sg(x, eps=1e-12):
    return 1 if x > eps else -1 if x < -eps else 0


def support(S, Z, k, d):
    """The 6 core entry reasons at candle k: 1 = still points with the trade, 0 = does not, None = not computable.
    Same six conditions as the entry tags (tag_lab.make_tags): TSI vs its signal line, TSI vs 0, Z vs its EMA30/EMA50,
    cloud colour, Z vs Z-SMA, price vs EMA50. Used on the entry candle AND now, so both counts are on one basis."""
    c = S["c"][k]
    tsi, diff, z, zsma, e50 = S["tsi"][k], S["diff"][k], S["z"][k], S["zsma"][k], S["e50"][k]
    zf, zs = Z["zf"][k], Z["zs"][k]
    out = [None if diff is None else int(diff * d > 0),
           None if tsi is None else int(tsi * d > 0),
           None if None in (z, zf, zs) else int(((z > zf) + (z > zs) if d > 0 else (z < zf) + (z < zs)) == 2),
           None if None in (zf, zs) else int((zf > zs) == (d > 0)),
           None if None in (z, zsma) else int((z > zsma) == (d > 0)),
           None if e50 is None else int((c - e50) * d > 0)]
    return out


def _count(sup):
    return sum(1 for v in sup if v), sum(1 for v in sup if v is not None)


def _diff(a, b, d=1):
    return None if a is None or b is None else (a - b) * d


def _r(v, nd=2):
    return None if v is None else round(float(v), nd)


def _roi(entry, px, d, lev):
    return (px - entry) / entry * 100.0 * d * lev          # gross ROI points, before the fee (same basis as mfe / giveback)


def _events(S, Z, i, j, d):
    """Opposite EMA50 crosses, opposite Z black candles and reversal-warning arrows on candles i+1..j. -> (counts, candles since the latest, recent?)"""
    opp_x, opp_z, warn = (S["xdn"], Z["dn"], S["wdn"]) if d > 0 else (S["xup"], Z["up"], S["wup"])
    n = [0, 0, 0]
    last = None
    recent = [False, False, False]
    for k in range(i + 1, j + 1):
        hit = False
        for q, arr in enumerate((opp_x, opp_z, warn)):
            if arr[k]:
                n[q] += 1
                hit = True
                if j - k < RECENT:
                    recent[q] = True
        if hit:
            last = j - k
    return n, last, recent


def _mfe_age(S, i, j, d):
    """Candles since price last made a new best (price scan only, sim_rule is not touched)."""
    best, age = S["c"][i], 0
    for k in range(i + 1, j + 1):
        px = S["h"][k] if d > 0 else S["l"][k]
        if (px > best) if d > 0 else (px < best):
            best, age = px, 0
        else:
            age += 1
    return age


def _state(n, sc, sn, s0, sc_hist, ev_recent, tsi_wrong, roi_up, giveback_big):
    """PROVISIONAL label. -> (state, why)."""
    if n < NEW_BARS:
        return "NEW", "too early"
    if sn < 6 or sc is None:
        return "UNKNOWN", "indicator values missing"
    if (ev_recent[0] or ev_recent[1]) and tsi_wrong:
        return "REVERSED", "opposite cross / Z candle and TSI on the wrong side"
    falling2 = len(sc_hist) >= 3 and sc_hist[-1] < sc_hist[-2] < sc_hist[-3]
    if s0 is not None and s0 - sc >= 2:
        return "WEAKENING", "support dropped by %d since entry" % (s0 - sc)
    if falling2:
        return "WEAKENING", "support fell 2 candles in a row"
    if ev_recent[2]:
        return "WEAKENING", "reversal warning arrow"
    if giveback_big:
        return "WEAKENING", "gave back over half of a real MFE"
    if sc >= 5 and (s0 is None or sc >= s0) and roi_up:
        return "STRONG", "5+ reasons, not below entry, ROI rising"
    return "STABLE", "in between"


def observe(tr, S, Z, i, lv, lev, fee):
    """Measure one OPEN Dual trade on the newest closed candle and store the result in tr["edge"].
    i = entry candle index, lv = sim_rule result of the open replay (allow_open=True). Never raises, never changes anything but tr["edge"].
    -> the edge dict, or None (nothing measured)."""
    try:
        return _observe(tr, S, Z, i, lv, lev, fee)
    except Exception as ex:                                       # an observer problem must never reach the bot
        print("brain_edge: skipped %s %s: %s" % (tr.get("s"), tr.get("f"), ex), flush=True)
        return None


def _observe(tr, S, Z, i, lv, lev, fee):
    if lv is None or tr.get("status") != "open" or not tr.get("take", True):
        return None
    j = S["n"] - 1
    if j <= i:
        return None
    old = tr.get("edge") if isinstance(tr.get("edge"), dict) else None
    if old and old.get("lt") == S["t"][j] and old.get("v") == EDGE_VERSION:
        return old                                               # this closed candle was already measured
    d, entry, sl = tr["d"], tr["entry"], tr["sl"]
    n = j - i
    k3, k5 = max(i, j - SLOPE_K), max(i, j - WIDTH_K)
    sup = support(S, Z, j, d)
    sc, sn = _count(sup)
    s0 = _count(support(S, Z, i, d))[0]
    s3 = _count(support(S, Z, k3, d))[0]
    hist_sc = [int(ch) for ch in (old or {}).get("hc", "") if ch.isdigit()]
    z, z3, z5 = S["z"][j], S["z"][k3], S["z"][k5]
    dj, d3, d5 = S["diff"][j], S["diff"][k3], S["diff"][k5]
    tsi, tsi5 = S["tsi"][j], S["tsi"][k5]
    std, e50, e50_5 = S["std"][j], S["e50"][j], S["e50"][k5]
    w, w5 = S["width"][j], S["width"][k5]
    wd = None if not w or not w5 else (w / w5 - 1.0) * 100.0
    zv = None if z is None else z * d
    zs = _diff(z, z3, d)
    th = None if dj is None else dj * d
    ths = _diff(dj, d3, d)
    ed = None if not std or e50 is None else (S["c"][j] - e50) / std * d
    es = None if not std or e50 is None or e50_5 is None else (e50 - e50_5) / std * d
    pm = [_sg((S["c"][j] - S["c"][k5]) * d), _sg(_diff(z, z5, d) or 0.0), _sg(_diff(tsi, tsi5, d) or 0.0)]
    ag = int(pm[0] * pm[1] > 0) if pm[0] and pm[1] else 0
    ev, ea, recent = _events(S, Z, i, j, d)
    risk = abs(entry - sl) / entry * 100.0 * lev                 # 1R in ROI points (the trade's own risk)
    roi_now = _roi(entry, S["c"][j], d, lev)
    roi_k3 = _roi(entry, S["c"][k3], d, lev)
    mfe, gb = lv.get("mfe", 0.0), lv.get("giveback", 0.0)
    delta = (roi_now - roi_k3) / risk if risk else 0.0
    pg = "progressing" if delta > PROG_R else "reversing" if delta < -PROG_R else "stalling"
    ma = _mfe_age(S, i, j, d)
    gb_big = bool(risk and mfe >= GB_MIN_R * risk and gb > GB_FRAC * mfe)
    tsi_wrong = th is not None and th < 0
    st, why = _state(n, sc if sn == 6 else None, sn, s0, hist_sc + [sc], recent, tsi_wrong, delta > 0, gb_big)
    prev = old or {}
    hs = (prev.get("hs", "") + STATE_LETTER[st])[-MAX_HIST:]
    hc = (prev.get("hc", "") + str(sc))[-MAX_HIST:]
    hr = (list(prev.get("hr") or []) + [_r(roi_now - fee, 1)])[-MAX_HIST:]
    hz = (list(prev.get("hz") or []) + [_r(zv, 2)])[-MAX_HIST:]
    txt = "%s - %d of 6 reasons still with trade (was %d)" % (st, sc, s0) if st not in ("NEW", "UNKNOWN") else "%s - %s" % (st, why)
    tr["edge"] = {
        "v": EDGE_VERSION, "lt": S["t"][j], "n": n, "f0": prev.get("f0", n), "st": st, "txt": txt, "why": why, "pg": pg,
        "sc": sc, "s0": s0, "s3": s3, "sw": "".join("?" if v is None else str(v) for v in sup),
        "zv": _r(zv), "zs": _r(zs), "th": _r(th), "ths": _r(ths), "tv": _r(None if tsi is None else tsi * d, 1),
        "wd": _r(wd, 1), "ed": _r(ed), "es": _r(es), "ev": ev, "ea": ea, "pm": pm, "ag": ag,
        "roi": _r(roi_now - fee, 1), "mfe": _r(mfe, 1), "gb": _r(gb, 1), "ma": ma,
        "hs": hs, "hc": hc, "hr": hr, "hz": hz, "t": int(time.time())}
    return tr["edge"]


def close(tr):
    """The trade finished: mark the observation as ended (nothing else changes). Never raises."""
    try:
        if isinstance(tr.get("edge"), dict):
            tr["edge"]["done"] = 1
    except Exception:
        pass


def slim_edge(tr):
    """The edge of a trade WITHOUT the history lists (for the app view: small). None if the trade has no edge."""
    e = tr.get("edge")
    if not isinstance(e, dict):
        return None
    return {k: v for k, v in e.items() if k not in HIST_KEYS}


def _lines(e):
    """Three short plain lines: TSI, Z / SD bands, EMA (provisional wording, numbers are with-trade)."""
    def sgn(x, a, b):
        return "n/a" if x is None else a if x > 0 else b if x < 0 else "flat"
    wd = e.get("wd")
    sd = "n/a" if wd is None else "expanding" if wd > WIDTH_EPS else "contracting" if wd < -WIDTH_EPS else "flat"
    return [
        "TSI %s, histogram %s" % (sgn(e.get("th"), "with trade", "against trade"), sgn(e.get("ths"), "growing", "shrinking")),
        "Z %s SD (%s), SD bands %s" % ("n/a" if e.get("zv") is None else "%+.1f" % e["zv"], sgn(e.get("zs"), "rising", "falling"), sd),
        "EMA50 %s SD away, slope %s" % ("n/a" if e.get("ed") is None else "%+.1f" % e["ed"], sgn(e.get("es"), "with trade", "against trade"))]


def scorecard(trades):
    """MEASUREMENT ONLY: did trades that showed WEAKENING / REVERSED at any time end worse than the others? Never touches a trade.
    Caution (said in the text): a long trade has more candles to show WEAKENING once, so read it as a hint, not a proof."""
    done = [t for t in trades if t.get("status") == "closed" and t.get("net") is not None and isinstance(t.get("edge"), dict)
            and len(t["edge"].get("hs", "")) >= 2]
    out = {"status": "collecting", "n": len(done), "need": SCORE_MIN, "groups": [],
           "text": "Collecting: %d finished trades with edge history, the scorecard needs %d. Labels are provisional." % (len(done), SCORE_MIN)}
    if len(done) < SCORE_MIN:
        return out

    def grp(name, sel):
        g = [t for t in done if sel(t["edge"]["hs"])]
        nets = [t["net"] for t in g]
        return {"key": name, "n": len(g), "avg_net": _r(sum(nets) / len(nets), 1) if nets else None,
                "win_pct": int(round(100.0 * sum(1 for x in nets if x > 0) / len(nets))) if nets else None}
    out["groups"] = [grp("weak_or_reversed", lambda h: "W" in h or "R" in h), grp("never_weak", lambda h: "W" not in h and "R" not in h),
                     grp("reversed", lambda h: "R" in h), grp("strong_seen", lambda h: "S" in h)]
    a, b = out["groups"][0], out["groups"][1]
    out["status"] = "ready"
    out["text"] = ("Trades that showed WEAKENING or REVERSED ended at %s (avg ROI), the others at %s. Measurement only; longer trades have more "
                   "chances to show WEAKENING, and the labels are provisional." % (a["avg_net"], b["avg_net"]))
    return out


def report(trades):
    """The Brain's view of every OPEN taken Dual trade that has an edge + counts per state + the scorecard. Read only. -> dict for the view JSON."""
    opens = [t for t in trades if t.get("status") == "open" and isinstance(t.get("edge"), dict)]
    counts = {"STRONG": 0, "STABLE": 0, "WEAKENING": 0, "REVERSED": 0, "NEW": 0, "UNKNOWN": 0}
    items = []
    for t in sorted(opens, key=lambda x: x.get("t", 0), reverse=True):
        e = t["edge"]
        counts[e.get("st", "UNKNOWN")] = counts.get(e.get("st", "UNKNOWN"), 0) + 1
        if len(items) < MAX_LIST:
            items.append({"s": t.get("s"), "f": t.get("f"), "d": t.get("d"), "t": t.get("t"), "st": e.get("st"), "txt": e.get("txt"),
                          "pg": e.get("pg"), "lines": _lines(e), "roi": e.get("roi"), "mfe": e.get("mfe"), "gb": e.get("gb"),
                          "sc": e.get("sc"), "s0": e.get("s0"), "n": e.get("n"), "hs": e.get("hs", "")[-20:]})
    return {"version": EDGE_VERSION, "provisional": True, "open": len(opens), "counts": counts, "items": items,
            "score": scorecard(trades),
            "note": "Observation only. STRONG / STABLE / WEAKENING / REVERSED are provisional labels, not proven predictions; nothing is closed, changed or rejected."}
