"""pd_cool.py - Round 3 part A (28 Nov 2026): COOLING WATCH = pump, then sideways, then dump. Read README_PUMPDUMP.md section 6 first.
Goal: warn BEFORE the dump of a coin that pumped in the last 7-10 days (the owner's EVAA / PORTAL case). Called from inside the existing pd_runner
thread (once per cool_step_sec, no new thread, no Telegram, no order). It only READS Binance public data.
  * WATCH LIST (max cool_max coins, kept cool_keep_days = 10 days): gainers of <data>/top10_7d.json with a day gain >= cool_entry_gain %
    (that file is built by top10_7d.py, this module never rebuilds it) + any coin with 24h change >= cool_live_gain % today. Saved in cool_list.json.
  * CANDLES: only these coins, raw klines 15m / 1h / 4h, fetched ONLY when the next candle has closed, through the SAME call cap and Binance back-off
    as Round 1 (pd_tsi.Klines). Funding comes from ONE call to /fapi/v1/premiumIndex every cool_fund_min minutes (all coins).
  * STAGES (guess thresholds in pd_config, the study of Round 4 tunes them): TREND (near the high, higher highs, volume healthy), PEAK (top just made,
    3%+ under it, first hours), COOLING (5-40% under the peak, 12 h range tight, volume under half of the pump volume), WARNING (COOLING plus 3 of
    5 weakness tests), DUMP_START (price under the lowest low of the sideways part: from here the normal scanner takes over).
  * WEAKNESS TESTS: lower high formed; red candles have more volume than green; taker (buyers) share of the last 6 candles under 45%;
    TSI histogram red on 2+ of 15m / 1h / 4h; funding lower than 3 h ago.
  * CHANCE %: only for WARNING, own files (cool_chance.json, cool_pending.json, cool_out/<day>.jsonl) through pd_chance.Chance("cool", ...).
    Worked = the coin fell cool_real_move % (10) within cool_check_min (48 h). That rule is a GUESS until the owner confirms (README section 13).
Stage changes are logged in <data>/pumpdump/cool_events/<day>.jsonl (data for the study). Output: snapshot() -> GET /api/pd/cool.
Part B (next) = the app section."""
import calendar
import json
import os
import time

import pd_chance
import pd_config as C
import pd_store as ST
import pd_tsi

TFS = ("1h", "15m", "4h")
LIMIT = 300
ORDER = {"WARNING": 0, "DUMP_START": 1, "COOLING": 2, "PEAK": 3, "TREND": 4}


def _mean(x):
    return sum(x) / len(x) if x else 0.0


def structure(rows, price):
    """Closed 1h candles (oldest first) + live price -> numbers of the pump / cooling shape, or None when there are too few candles."""
    n = len(rows)
    if n < 60:
        return None
    op, hi, lo, cl = ([float(r[i]) for r in rows] for i in (1, 2, 3, 4))
    qv, tb = [float(r[7]) for r in rows], [float(r[10]) for r in rows]
    ip = n - 1 - hi[::-1].index(max(hi))
    peak = hi[ip]
    since = n - 1 - ip                                    # closed 1h candles since the candle that made the high
    if price > peak:
        peak, since = price, 0
    base = min(lo[max(0, ip - 168):ip + 1])
    pv = _mean(qv[max(0, ip - 5):ip + 1])
    q6 = sum(qv[-6:])
    red = sum(q for q, o, c in zip(qv[-12:], op[-12:], cl[-12:]) if c < o)
    green = sum(q for q, o, c in zip(qv[-12:], op[-12:], cl[-12:]) if c >= o)
    return {"peak": peak, "since": since, "pump_pct": (peak / base - 1.0) * 100.0 if base > 0 else 0.0, "drop": max(0.0, (peak - price) / peak * 100.0),
            "vol_ratio": (_mean(qv[-6:]) / pv) if pv > 0 else 1.0, "range12": (max(hi[-12:]) / min(lo[-12:]) - 1.0) * 100.0,
            "lower_high": max(hi[-6:]) < max(hi[-12:-6]), "red_vol": red > green, "taker6": (sum(tb[-6:]) / q6) if q6 > 0 else 0.5,
            "support": min(lo[-13:-1]), "swing_low": min(lo[-6:]),
            "higher_highs": max(hi[-12:]) > max(hi[-24:-12]), "vol_healthy": _mean(qv[-6:]) >= 0.6 * _mean(qv[-18:-6])}


def classify(st, price, weak_n):
    """-> TREND / PEAK / COOLING / WARNING / DUMP_START, or None (nothing to say: not a pump, or it already dumped 40%+)."""
    if st["pump_pct"] < C.get("cool_pump_min"):
        return None
    drop, since = st["drop"], st["since"]
    warn = weak_n >= C.get("cool_warn_min")
    if drop < C.get("cool_near_peak"):
        if warn:
            return "WARNING"
        return "TREND" if st["higher_highs"] and st["vol_healthy"] else None
    if since <= C.get("cool_peak_bars"):
        return "PEAK"
    if drop >= 5.0 and price < st["support"] * (1.0 - C.get("cool_break") / 100.0):
        return "DUMP_START"
    if 5.0 <= drop <= 40.0 and st["range12"] <= C.get("cool_range_max") and st["vol_ratio"] <= C.get("cool_vol_half"):
        return "WARNING" if warn else "COOLING"
    return None


class Cool:
    def __init__(self, klines, chance=None):
        self.kl = klines
        self.chance = chance or pd_chance.Chance("cool", C.get("cool_check_min"), "cool_real_move")
        self.coins = dict(ST.read_json("cool_list.json", {}).get("coins", {}))   # symbol -> {"since": epoch, "why": text, "gain": %}
        self.raw = {}             # (symbol, tf) -> {"next": epoch, "rows": closed candles, "an": pd_tsi.analyse numbers}
        self.fund = {}            # symbol -> [(epoch, funding rate)]
        self.fund_t = 0.0
        self.list_t = 0.0
        self.state = {}           # symbol -> {"stage", "since"}
        self.snap = {"ts": 0, "cool": []}
        self.last = 0.0

    def clear(self):
        self.raw.clear()
        self.fund.clear()
        self.state.clear()
        self.snap = {"ts": 0, "cool": []}
        self.last = self.fund_t = self.list_t = 0.0

    # ------------------------------------------------------------------ watch list
    def _refresh_list(self, feed, now):
        if now - self.list_t < C.get("cool_list_sec"):
            return
        self.list_t = now
        old = json.dumps(self.coins, sort_keys=True)
        try:
            with open(os.path.join(os.path.dirname(C.root()), "top10_7d.json"), encoding="utf-8") as f:
                days = (json.load(f) or {}).get("days", {})
            for day, v in days.items():
                ts = calendar.timegm(time.strptime(day, "%Y-%m-%d"))
                for sym, pct, _close in v.get("gainers", []):
                    if pct >= C.get("cool_entry_gain") and sym in feed.meta:
                        cur = self.coins.get(sym)
                        if cur is None or ts > cur["since"]:
                            self.coins[sym] = {"since": ts, "why": "top10_7d", "gain": round(pct, 1)}
        except Exception:
            pass                                          # no file yet: only the live rule works
        for sym, m in feed.meta.items():
            if m["chg24"] >= C.get("cool_live_gain"):
                self.coins[sym] = {"since": now, "why": "live", "gain": round(m["chg24"], 1)}
        keep = C.get("cool_keep_days") * 86400
        for sym in [s for s, c in self.coins.items() if now - c["since"] > keep]:
            del self.coins[sym]
        if len(self.coins) > int(C.get("cool_max")):
            newest = sorted(self.coins, key=lambda s: -self.coins[s]["since"])[:int(C.get("cool_max"))]
            self.coins = {s: self.coins[s] for s in newest}
        if json.dumps(self.coins, sort_keys=True) != old:
            ST.write_json("cool_list.json", {"coins": self.coins})

    # ------------------------------------------------------------------ data
    def _room(self, now):
        """True when Binance is not blocking us and the shared per-minute cap has room (one call is booked)."""
        kl = self.kl
        if now < kl.blocked_until:
            return False
        while kl.calls and kl.calls[0] < now - 60:
            kl.calls.popleft()
        if len(kl.calls) >= C.get("kline_calls_min"):
            return False
        kl.calls.append(now)
        return True

    def _pull(self, sym, tf, now):
        if not self._room(now):
            return False
        try:
            rows = self.kl.fetch(sym, tf, LIMIT)
        except pd_tsi.RateLimited as e:
            self.kl.blocked_until = now + e.wait
            self.kl.last_error = str(e)
            return False
        except Exception as e:
            old = self.raw.get((sym, tf))
            self.raw[(sym, tf)] = {"next": now + 120, "rows": old["rows"] if old else [], "an": old["an"] if old else None}
            self.kl.last_error = "%s: %s" % (type(e).__name__, str(e)[:80])
            return True
        sec = pd_tsi.TF_SEC[tf]
        nxt = (rows[-1][0] / 1000.0 + sec + 3) if rows else now + 120
        self.raw[(sym, tf)] = {"next": nxt if nxt > now else now + 60, "rows": [r for r in rows if r[0] / 1000.0 + sec <= now + 1], "an": pd_tsi.analyse(rows, tf, now)}
        return True

    def _fetch(self, now):
        made = 0
        for tf in TFS:
            for sym in self.coins:
                c = self.raw.get((sym, tf))
                if c is not None and now < c["next"]:
                    continue
                if made >= int(C.get("cool_step_max")) or not self._pull(sym, tf, now):
                    return
                made += 1

    def _funding(self, now):
        if not self.coins or now - self.fund_t < C.get("cool_fund_min") * 60 or not self._room(now):
            return
        self.fund_t = now
        try:
            import requests
            r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=10)
            if r.status_code in (418, 429):
                self.kl.blocked_until = now + (600 if r.status_code == 418 else 120)
                return
            rate = {d["symbol"]: float(d["lastFundingRate"]) for d in r.json() if d.get("symbol") in self.coins}
        except Exception as e:
            print("[pd] funding call failed: %s" % type(e).__name__)
            return
        for sym, v in rate.items():
            s = self.fund.setdefault(sym, [])
            s.append((now, v))
            while s and s[0][0] < now - 12 * 3600:
                s.pop(0)

    def _funding_down(self, sym, now):
        s = self.fund.get(sym) or []
        older = [v for t, v in s if t <= now - 3 * 3600]
        return None if not s or not older else s[-1][1] < older[-1]

    # ------------------------------------------------------------------ one step
    def update(self, feed, now):
        self.chance.track({s: h.p[-1] for s, h in feed.hist.items() if h.p}, now)
        if now - self.last < C.get("cool_step_sec"):
            return
        self.last = now
        self._refresh_list(feed, now)
        self._fetch(now)
        self._funding(now)
        cards = []
        for sym in self.coins:
            try:
                c = self._eval(feed, sym, now)
            except Exception as e:
                print("[pd] cool eval %s failed: %s: %s" % (sym, type(e).__name__, e))
                c = None
            if c:
                cards.append(c)
        cards.sort(key=lambda c: (ORDER[c["stage"]], -c["drop_pct"]))
        self.snap = {"ts": int(now), "cool": cards}

    def _eval(self, feed, sym, now):
        r1 = self.raw.get((sym, "1h"))
        if not r1 or not r1["rows"]:
            return None
        h = feed.hist.get(sym)
        price = h.p[-1] if h is not None and h.p else float(r1["rows"][-1][4])
        st = structure(r1["rows"], price)
        if st is None:
            return None
        an = {tf: self.raw[(sym, tf)]["an"] for tf in TFS if self.raw.get((sym, tf)) and self.raw[(sym, tf)]["an"]}
        weak_tf = [tf for tf, d in an.items() if d.get("hist") is not None and d["hist"] < 0]
        tests = {"lower_high": st["lower_high"], "red_vol": st["red_vol"], "taker": st["taker6"] < C.get("cool_taker_lo"),
                 "tsi_weak": (len(weak_tf) >= 2) if len(an) >= 2 else None, "funding_down": self._funding_down(sym, now)}
        weak_n = sum(1 for v in tests.values() if v is True)
        stage = classify(st, price, weak_n)
        if stage is None:
            self.state.pop(sym, None)
            return None
        s0 = self.state.get(sym)
        if s0 is None or s0["stage"] != stage:
            s0 = self.state[sym] = {"stage": stage, "since": now}
            ST.append("cool_events", C.day_of(now), {"ts": int(now), "time": C.clock_of(now), "symbol": sym, "stage": stage, "price": price, "drop": round(st["drop"], 1),
                                                     "weak_n": weak_n, "tests": tests})
        ch = None
        if stage == "WARNING":
            key = "dump|cool|n%d|%s" % (weak_n, "d1" if st["drop"] < 15.0 else "d2")
            ch = self.chance.rate(key, "dump", "cool")
            self.chance.add(sym, "dump", "cool", price, key, weak_n, now)
        fd = self.fund.get(sym)
        return {"symbol": sym, "stage": stage, "price": price, "peak": st["peak"], "pump_pct": round(st["pump_pct"], 1), "drop_pct": round(st["drop"], 1),
                "since_peak_min": st["since"] * 60, "stage_min": round((now - s0["since"]) / 60.0, 1), "level": st["swing_low"] if stage == "TREND" else st["support"],
                "tests": tests, "weak_n": weak_n, "tf_weak": weak_tf, "taker6": round(st["taker6"], 2), "vol_ratio": round(st["vol_ratio"], 2),
                "range12": round(st["range12"], 1), "funding": fd[-1][1] if fd else None, "why": self.coins[sym]["why"], "gain": self.coins[sym]["gain"], "chance": ch}

    # ------------------------------------------------------------------ for the app
    def snapshot(self, now):
        s = self.snap
        waiting = sum(1 for sym in self.coins if (sym, "1h") not in self.raw)
        return {"ready": bool(self.raw), "ts": s["ts"], "cool": s["cool"], "listed": len(self.coins), "waiting": waiting, "limited": self.kl.limited(now),
                "kline_error": self.kl.last_error, "min_outcomes": C.get("min_outcomes"), "check_min": C.get("cool_check_min"), "real_move": C.get("cool_real_move")}
