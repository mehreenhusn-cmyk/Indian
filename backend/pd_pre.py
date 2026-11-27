"""pd_pre.py - Round 2 (28 Nov 2026): TAIYARI ME = PRE-PUMP / PRE-DUMP for the Pump / Dump tab. Read README_PUMPDUMP.md section 5 first.
Called from inside the existing pd_runner thread (once per pre_step_sec, no new thread, no Telegram, no order). It looks for coins that are about
to move: the price is still flat, but volume is rising and the buyers (or sellers) are arriving.
  * CANDIDATE (cheap, from the 20 s feed, no network call): volume of the last 15 min >= pre_vol_lo x the hour before, the 15 min move is under
    pre_move_max %, the 60 min range is tight (under pre_range_max %). Coins that are already in a START / RUNNING stage or already shown in
    Naye movers / Chal rahe are left out (they have moved). Max pre_max_cand coins get candle numbers (time frames 5m 15m 1h 2h only: fewer calls).
  * SIGNALS (candle numbers of the EXISTING pd_tsi.analyse, no new formula): TSI turns toward the side on 2+ time frames while it is still not far on
    that side (pre_tsi_max); the TSI histogram flips toward the side; taker share of the last candles on the side (buyers for pump, sellers for dump,
    pre_taker_hi). Each gives points (weights pw_* in pd_config). The price being near / below the EMA is allowed and not used.
  * A coin shows as TAIYARI ME when score >= pre_min_score and at least pre_min_signals of the 3 candle signals are on. It stays while the score
    is >= pre_stay_score, and goes away pre_drop_min minutes after the signals fade, or pre_max_min after it first showed. One side per coin.
  * LEAD TIME: when a coin later reaches START, on_start() writes how many minutes before the START the Taiyari me card first showed
    (<data>/pumpdump/pre_lead/<day>.jsonl). This is data for the study (Round 4).
  * CHANCE %: own files (pre_chance.json, pre_pending.json, pre_out/<day>.jsonl) through pd_chance.Chance("pre", ...). Worked = the coin moved
    pre_real_move % (3) the right way within pre_check_min (120) minutes. Both numbers are GUESSES until the owner confirms (README section 13).
Output: snapshot() -> the dict of GET /api/pd/pre."""
import bisect

import pd_chance
import pd_config as C
import pd_rank
import pd_store as ST

SIDES = ((1, "pump"), (-1, "dump"))
PRE_TFS = ("5m", "15m", "1h", "2h")


def _clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def flat_stats(h, now):
    """(move15 %, range60 %, low60, high60) of a coin from the feed, or None when the history is too short (needs about 40 min)."""
    i15 = pd_rank._at(h, now - 900)
    i60 = bisect.bisect_left(h.t, now - 3600)
    if i15 < 0 or i60 >= len(h.t) or now - h.t[i60] < 2400:
        return None
    seg = h.p[i60:]
    lo, hi = min(seg), max(seg)
    if lo <= 0 or not h.p[i15]:
        return None
    return (h.p[-1] / h.p[i15] - 1.0) * 100.0, (hi - lo) / lo * 100.0, lo, hi


def signals(sgn, tfd, vr, rng):
    """-> (score 0-100, sig dict). sgn = +1 pre-pump / -1 pre-dump; tfd = {tf: numbers} (only the PRE_TFS)."""
    up = sgn > 0
    tsi_tfs = [tf for tf, d in tfd.items() if d.get("tsi") is not None and d.get("tsi_up") == up and sgn * d["tsi"] < C.get("pre_tsi_max")]
    hist_tfs = [tf for tf, d in tfd.items() if d.get("hist") is not None and d.get("hist_change") is not None
                and sgn * d["hist_change"] > 0 and sgn * (d["hist"] - d["hist_change"]) <= 0]
    shares = [d["taker_buy_share"] for tf, d in tfd.items() if tf in ("5m", "15m") and d.get("taker_buy_share") is not None]
    aligned = None
    if shares:
        s = sum(shares) / len(shares)
        aligned = s if up else 1.0 - s
    hi = C.get("pre_taker_hi")
    vlo, vhi = C.get("pre_vol_lo"), C.get("pre_vol_hi")
    parts = {"tsi": min(len(tsi_tfs), 3) / 3.0,
             "hist": min(len(hist_tfs), 2) / 2.0,
             "taker": 0.0 if aligned is None else _clamp01((aligned - 0.5) / max(hi - 0.5, 0.01)),
             "vol": 0.5 + 0.5 * _clamp01((vr - vlo) / max(vhi - vlo, 0.01)),
             "range": _clamp01(1.0 - rng / max(C.get("pre_range_max"), 0.1))}
    score = sum(parts[k] * C.get("pw_" + k) for k in parts)
    on = [len(tsi_tfs) >= 2, len(hist_tfs) >= 1, aligned is not None and aligned >= hi]
    sig = {"tsi": len(tsi_tfs), "hist": len(hist_tfs), "taker": None if aligned is None else round(aligned, 2), "n": sum(1 for x in on if x),
           "tsi_on": on[0], "hist_on": on[1], "taker_on": on[2]}
    return score, sig


def bucket(sgn, vr, sig, rng):
    """Short key for the learned chance: side | pre | volume class | signals on (2 or 3) | range class."""
    return "|".join(["pump" if sgn > 0 else "dump", "pre", "v1" if vr < 3.0 else "v2", "n3" if sig["n"] >= 3 else "n2", "r1" if rng < C.get("pre_range_max") / 2.0 else "r0"])


def _r(v, nd=2):
    return None if v is None else round(v, nd)


class Pre:
    def __init__(self, klines, chance=None):
        self.kl = klines
        self.chance = chance or pd_chance.Chance("pre", C.get("pre_check_min"), "pre_real_move")
        self.active = {}          # (symbol, side) -> {"since", "seen", "miss", "card"}
        self.gone = {}            # (symbol, side) -> {"since", "last"}: coins that left the list (kept 6 h for the lead time)
        self.snap = {"ts": 0, "pre": {"pump": [], "dump": []}}
        self.last = 0.0
        self.ready_flag = False

    def clear(self):
        self.active.clear()
        self.gone.clear()
        self.snap = {"ts": 0, "pre": {"pump": [], "dump": []}}
        self.last = 0.0
        self.ready_flag = False

    # ------------------------------------------------------------------ one step
    def update(self, feed, tracker, now, exclude=()):
        self.chance.track({s: h.p[-1] for s, h in feed.hist.items() if h.p}, now)
        if now - self.last < C.get("pre_step_sec"):
            return
        self.last = now
        cand = []
        for sym, h in feed.hist.items():
            if sym in exclude or not h.t or h.t[-1] != now or tracker.is_active(sym, "pump") or tracker.is_active(sym, "dump"):
                continue
            fs = flat_stats(h, now)
            if fs is None:
                continue
            self.ready_flag = True
            mv, rng, lo, hi = fs
            if abs(mv) > C.get("pre_move_max") or rng > C.get("pre_range_max"):
                continue
            vr = pd_rank.vol_ratio15(h, now)
            if vr is None or vr < C.get("pre_vol_lo"):
                continue
            cand.append((vr, sym, mv, rng, lo, hi))
        cand.sort(key=lambda x: -x[0])
        cand = cand[:int(C.get("pre_max_cand"))]
        shown = {k[0] for k in self.active}
        order = [c[1] for c in cand if c[1] in shown] + [c[1] for c in cand if c[1] not in shown]
        try:
            self.kl.step(order, now, PRE_TFS)
        except Exception as e:
            print("[pd] pre kline step failed: %s: %s" % (type(e).__name__, e))
        ok = set()
        for vr, sym, mv, rng, lo, hi in cand:
            tfd = {tf: d for tf, d in self.kl.tf_data(sym).items() if tf in PRE_TFS}
            if len(tfd) < 2:
                continue
            sc = sorted(((signals(sgn, tfd, vr, rng), sgn, side) for sgn, side in SIDES), key=lambda x: -x[0][0])
            (best, sig), sgn, side = sc[0]
            if best - sc[1][0][0] < 5.0:          # both sides look the same: unclear, skip
                continue
            key = (sym, side)
            need = C.get("pre_stay_score") if key in self.active else C.get("pre_min_score")
            if best < need or sig["n"] < C.get("pre_min_signals"):
                continue
            ok.add(key)
            self._keep(feed, sym, side, sgn, vr, mv, rng, lo, hi, best, sig, tfd, now)
        self._clean(tracker, ok, now)
        pre = {"pump": [], "dump": []}
        for (sym, side), a in self.active.items():
            c = dict(a["card"])
            c["fading"] = (sym, side) not in ok
            c["since_min"] = round((now - a["since"]) / 60.0, 1)
            pre[side].append(c)
        for side in pre:
            pre[side].sort(key=lambda c: (c["fading"], -c["score"]))
            pre[side] = pre[side][:int(C.get("pre_max_side"))]
        self.snap = {"ts": int(now), "pre": pre}

    def _keep(self, feed, sym, side, sgn, vr, mv, rng, lo, hi, score, sig, tfd, now):
        self.active.pop((sym, "dump" if side == "pump" else "pump"), None)           # one side per coin
        a = self.active.get((sym, side))
        if a is None:
            a = self.active[(sym, side)] = {"since": now, "seen": now, "miss": 0.0, "card": {}}
        a["seen"], a["miss"] = now, 0.0
        price = feed.hist[sym].p[-1]
        key = bucket(sgn, vr, sig, rng)
        ch = self.chance.rate(key, side, "pre")
        self.chance.add(sym, side, "pre", price, key, int(score), now)
        a["card"] = {"symbol": sym, "side": side, "kind": "pre", "price": price, "vol_ratio": round(vr, 1), "move_15m": round(sgn * mv, 2), "range_pct": round(rng, 2),
                     "level": lo if sgn > 0 else hi, "score": int(round(score)), "sig": sig, "buyers_share": sig["taker"], "qv24": round(feed.meta[sym]["qv24"]),
                     "chg24": round(feed.meta[sym]["chg24"], 1), "tf_ready": len(tfd), "chance": ch,
                     "tf": {tf: {"tsi": _r(d.get("tsi")), "hist": _r(d.get("hist")), "hist_change": _r(d.get("hist_change")), "tsi_up": d.get("tsi_up"),
                                 "z200": _r(d.get("z200")), "zsm": _r(d.get("zsm")), "ema50": _r(d.get("ema50_dist"))} for tf, d in tfd.items()}}

    def _clean(self, tracker, ok, now):
        for key in list(self.active):
            a, sym = self.active[key], key[0]
            if key not in ok and not a["miss"]:
                a["miss"] = now
            started = tracker.is_active(sym, key[1])
            stale = a["miss"] and now - a["miss"] > C.get("pre_drop_min") * 60
            if started or stale or now - a["since"] > C.get("pre_max_min") * 60:
                self.gone[key] = {"since": a["since"], "last": now}
                del self.active[key]
        for key in [k for k, v in self.gone.items() if now - v["last"] > 6 * 3600]:
            del self.gone[key]

    # ------------------------------------------------------------------ lead time (called by pd_runner when a coin reaches START)
    def on_start(self, ev):
        """How many minutes before this START did the Taiyari me card first show? Returns minutes or None."""
        key = (ev["symbol"], ev["side"])
        src = self.active.get(key) or self.gone.get(key)
        if not src:
            return None
        lead = round((ev["ts"] - src["since"]) / 60.0, 1)
        ST.append("pre_lead", ev["day"], {"symbol": ev["symbol"], "side": ev["side"], "start_ts": ev["ts"], "pre_since": int(src["since"]), "lead_min": lead})
        return lead

    # ------------------------------------------------------------------ for the app
    def snapshot(self, now):
        s = self.snap
        return {"ready": self.ready_flag, "ts": s["ts"], "pre": s["pre"], "limited": self.kl.limited(now), "kline_error": self.kl.last_error,
                "min_outcomes": C.get("min_outcomes"), "check_min": C.get("pre_check_min"), "real_move": C.get("pre_real_move")}
