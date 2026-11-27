"""pd_rank.py - Round 1 (28 Nov 2026): NAYE MOVERS + CHAL RAHE for the Pump / Dump tab. Read README_PUMPDUMP.md section 4 first.
Called from inside the existing pd_runner thread (one cheap step per poll, no new thread, no Telegram, no order).
  * RANK: every poll the coins are ranked by the Binance 24h change (gainers: biggest +%, losers: biggest -%), from feed.meta (chg24).
    A short rank history (rank_hist_min) per coin shows how fast a coin climbs (example: place 31 -> 14 in 30 min).
  * NAYE MOVERS (kind "new"): rank > top_n, rank climbed mv_rank_gain places or more, volume ratio >= mv_vol, a small move already (mv_move_lo .. mv_move_hi %
    in 15 min, so it is early). Ranked by volume ratio x speed, NOT by the 24h %. Max mv_max_side per side. A coin is on ONE side only.
  * CHAL RAHE (kind "run"): coins that are in the Binance top-N gainers / losers now stay visible, and so do coins that were there in the last run_keep_min
    minutes (never dropped while they run). Each shows RUNNING or TIRING (volume of the last 15 min vs the hour before, buyers' share, price pull-back).
  * STRENGTH 0-100 (pd_tsi.strength) and CHANCE % (pd_chance.py) for every card; the numbers of the details sheet come with it.
Output: snapshot() -> a dict the route /api/pd/movers sends to the app."""
import bisect

import pd_chance
import pd_config as C
import pd_scorer as S
import pd_tsi

SIDES = ((1, "pump"), (-1, "dump"))


def _at(h, target, tol=150.0):
    """Index of the newest sample at or before `target` (epoch s), or -1 when none is close enough."""
    i = bisect.bisect_right(h.t, target) - 1
    return i if i >= 0 and target - h.t[i] <= tol else -1


def vol_ratio15(h, now):
    """Volume per minute of the last 15 min divided by the volume per minute of the hour before (None = not enough history)."""
    i15 = _at(h, now - 900)
    ib = _at(h, now - 3900, 600.0)
    if i15 < 0:
        return None
    if ib < 0:
        ib = 0
    span = h.t[i15] - h.t[ib]
    if span < 600:
        return None
    base = max((h.q[i15] - h.q[ib]) / (span / 60.0), 1.0)
    cur = max(0.0, h.q[-1] - h.q[i15]) / max((now - h.t[i15]) / 60.0, 1.0)
    return cur / base


class Rank:
    def __init__(self, klines, chance):
        self.kl = klines
        self.chance = chance
        self.rh = {}              # symbol -> [t list, up-rank list, down-rank list], one sample per rank_sample_sec
        self.sticky = {}          # (symbol, side) -> {"since", "seen"}: coins that were in the top-N (Chal rahe keeps them)
        self.snap = {"ready": False, "ts": 0, "movers": {"pump": [], "dump": []}, "running": {"pump": [], "dump": []}}
        self.first = 0.0

    def clear(self):
        self.rh.clear()
        self.sticky.clear()
        self.kl.clear()
        self.snap = {"ready": False, "ts": 0, "movers": {"pump": [], "dump": []}, "running": {"pump": [], "dump": []}}
        self.first = 0.0

    # ------------------------------------------------------------------ ranks
    def _ranks(self, feed):
        up = sorted(feed.meta, key=lambda s: -feed.meta[s]["chg24"])
        dn = sorted(feed.meta, key=lambda s: feed.meta[s]["chg24"])
        return {s: i + 1 for i, s in enumerate(up)}, {s: i + 1 for i, s in enumerate(dn)}

    def _sample(self, up, dn, now):
        self.first = self.first or now
        gap = C.get("rank_sample_sec")
        keep = C.get("rank_hist_min") * 60
        for s in up:
            r = self.rh.get(s)
            if r is None:
                r = self.rh[s] = [[], [], []]
            if r[0] and now - r[0][-1] < gap:
                continue
            r[0].append(now)
            r[1].append(up[s])
            r[2].append(dn.get(s, 999))
            if r[0][0] < now - keep:
                k = bisect.bisect_left(r[0], now - keep)
                del r[0][:k], r[1][:k], r[2][:k]
        for s in [s for s in self.rh if s not in up]:
            del self.rh[s]

    def _before(self, sym, idx, now, sec):
        r = self.rh.get(sym)
        if not r or not r[0]:
            return None
        i = bisect.bisect_right(r[0], now - sec) - 1
        return r[idx][i] if i >= 0 and (now - sec) - r[0][i] <= 120 else None

    # ------------------------------------------------------------------ one step
    def update(self, feed, tracker, now):
        up, dn = self._ranks(feed)
        self._sample(up, dn, now)
        poll = C.get("poll_sec")
        topn = int(C.get("top_n"))
        ranks = {1: up, -1: dn}
        cand = {"pump": [], "dump": []}
        feats = {}
        for sgn, side in SIDES:
            for sym, rk in ranks[sgn].items():
                h = feed.hist.get(sym)
                if h is None or not h.t or h.t[-1] != now:
                    continue
                if rk <= topn:
                    st = self.sticky.setdefault((sym, side), {"since": now, "seen": now})
                    st["seen"] = now
                    self.sticky.pop((sym, "dump" if side == "pump" else "pump"), None)   # one side per coin
                    continue
                b30 = self._before(sym, 1 if sgn > 0 else 2, now, 1800)
                b10 = self._before(sym, 1 if sgn > 0 else 2, now, 600)
                gain = max([rk0 - rk for rk0 in (b30, b10) if rk0 is not None] or [0])
                if gain < C.get("mv_rank_gain"):
                    continue
                f = feats.get(sym) or S.features(h, now, feed.meta[sym]["qv24"], poll)
                feats[sym] = f
                if not f or not f.get("warm"):
                    continue
                d15, d5, vr = sgn * f["r15"], sgn * f["r5"], S.vr(f)
                if vr < C.get("mv_vol") or d5 < C.get("mv_r5_min") or not (C.get("mv_move_lo") <= d15 <= C.get("mv_move_hi")):
                    continue
                cand[side].append((vr * max(d15, 0.1), sym, rk, gain, f, vr, d15))
        movers = {"pump": [], "dump": []}
        taken = set()
        for sgn, side in SIDES:
            cand[side].sort(key=lambda x: -x[0])
            for raw, sym, rk, gain, f, vr, d15 in cand[side]:
                if sym in taken or len(movers[side]) >= C.get("mv_max_side"):
                    continue
                taken.add(sym)
                movers[side].append(self._card(feed, sym, side, sgn, "new", f, vr, d15, rk, gain, now, raw))
        running = self._running(feed, ranks, now, taken)
        order = [r["symbol"] for side in movers for r in movers[side]] + [r["symbol"] for side in running for r in running[side]]
        try:
            self.kl.step(list(dict.fromkeys(order)), now)
        except Exception as e:
            print("[pd] kline step failed: %s: %s" % (type(e).__name__, e))
        for grp in (movers, running):
            for side in grp:
                for card in grp[side]:
                    self._finish_card(card, feed, now)
        self.snap = {"ready": self.ready(now), "ts": int(now), "movers": movers, "running": running}
        self.chance.track({s: h.p[-1] for s, h in feed.hist.items() if h.p}, now)

    def ready(self, now):
        return bool(self.first) and now - self.first >= 10 * 60

    def _card(self, feed, sym, side, sgn, kind, f, vr, d15, rk, gain, now, raw=0.0):
        h = feed.hist[sym]
        recent = [p for t, p in zip(h.t, h.p) if t >= now - 1800] or [f["p"]]
        return {"symbol": sym, "side": side, "kind": kind, "price": f["p"], "rank": rk, "rank_gain": gain, "chg24": round(feed.meta[sym]["chg24"], 1),
                "move_15m": round(d15, 2), "move_5m": round(sgn * f["r5"], 2), "vol_ratio": round(vr, 1), "raw": round(raw, 2),
                "level": min(recent) if sgn > 0 else max(recent), "qv24": round(feed.meta[sym]["qv24"]), "_f": f, "_sgn": sgn}

    def _running(self, feed, ranks, now, taken):
        keep = C.get("run_keep_min") * 60
        topn = int(C.get("top_n"))
        out = {"pump": [], "dump": []}
        for k in [k for k, v in self.sticky.items() if now - v["seen"] > keep or k[0] not in feed.hist]:
            del self.sticky[k]
        for sgn, side in SIDES:
            rows = []
            for (sym, sd), st in self.sticky.items():
                if sd != side or sym in taken:
                    continue
                h = feed.hist.get(sym)
                if h is None or not h.t or h.t[-1] != now:
                    continue
                f = S.features(h, now, feed.meta[sym]["qv24"], C.get("poll_sec"))
                if not f:
                    continue
                rk = ranks[sgn].get(sym, 999)
                c = self._card(feed, sym, side, sgn, "run", f, S.vr(f), sgn * f["r15"], rk, 0, now)
                c["in_top"] = rk <= topn
                c["vol15"] = vol_ratio15(h, now)
                rows.append(c)
            out[side] = rows
        return out

    def _finish_card(self, c, feed, now):
        f, sgn, sym, side, kind = c.pop("_f"), c.pop("_sgn"), c["symbol"], c["side"], c["kind"]
        tfd = self.kl.tf_data(sym)
        st = pd_tsi.strength(sgn, c["vol_ratio"], c["move_15m"], c["rank_gain"], tfd)
        c["strength"], c["partial"], c["tf_agree"], c["tf_ready"], c["parts"] = st["score"], st["partial"], st["tf_agree"], st["tf_ready"], st["parts"]
        shares = [d["taker_buy_share"] for tf, d in tfd.items() if tf in ("5m", "15m") and d.get("taker_buy_share") is not None]
        share = (sum(shares) / len(shares)) if shares else None
        c["buyers_share"] = None if share is None else round(share if sgn > 0 else 1.0 - share, 2)
        c["tf"] = {tf: {"tsi": _r(d.get("tsi")), "hist": _r(d.get("hist")), "hist_change": _r(d.get("hist_change")), "tsi_up": d.get("tsi_up"), "above0": d.get("tsi_above_zero"),
                        "z200": _r(d.get("z200")), "z50": _r(d.get("z50")), "zsm": _r(d.get("zsm")), "ema30": _r(d.get("ema30_dist")), "ema50": _r(d.get("ema50_dist"))}
                   for tf, d in tfd.items()}
        if kind == "run":
            v15 = c.pop("vol15", None)
            c["vol15"] = None if v15 is None else round(v15, 2)
            pts = [v15 is not None and v15 < C.get("tire_vol"), c["move_15m"] <= 0, c["buyers_share"] is not None and c["buyers_share"] < C.get("tire_share")]
            h15 = tfd.get("15m")
            pts.append(bool(h15 and h15.get("hist_change") is not None and sgn * h15["hist_change"] < 0))
            c["tiring"] = sum(1 for x in pts if x) >= 2
        key = pd_chance.bucket(side, kind, c["vol_ratio"], c["rank_gain"], tfd, sgn)
        c["chance"] = self.chance.rate(key, side, kind)
        if kind == "new" or c.get("in_top"):
            self.chance.add(sym, side, kind, c["price"], key, c["strength"], now)

    # ------------------------------------------------------------------ for the app
    def snapshot(self, now):
        s = self.snap
        return {"ready": s["ready"], "ts": s["ts"], "movers": s["movers"], "running": s["running"], "limited": self.kl.limited(now), "kline_error": self.kl.last_error,
                "rank_warm_min": round(max(0.0, 10.0 - ((now - self.first) / 60.0)), 1) if self.first else 10.0, "kline_cached": len(self.kl.cache),
                "min_outcomes": C.get("min_outcomes")}


def _r(v, nd=2):
    return None if v is None else round(v, nd)
