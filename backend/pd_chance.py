"""pd_chance.py - the learned CHANCE % of the Round 1 lists (Naye Movers + Chal rahe), README_PUMPDUMP.md section 7.
Every coin that enters a list is saved with its FEATURE BUCKET (side, kind, volume class, time frames that agree, TSI side of zero, histogram
direction, rank climb). After 60 min it is labelled: worked = the coin moved 2%+ further the right way (the same REAL rule as a START, pd_config real_move).
Chance of a bucket = worked / checked, with a safe start: a bucket with few samples is pulled toward the overall rate of its list (shrinkage).
The app says "andaaza" (estimate) until the bucket has min_outcomes (100) checked alerts; then it shows the real rate and the counts ("85 / 140").
Files in <data>/pumpdump/: movers_chance.json (counts), movers_pending.json (waiting for the check), movers_out/<day>.jsonl (every checked alert).
No order, no Telegram."""
import time

import pd_config as C
import pd_store as ST

CHECK_MIN = 60


def bucket(side, kind, vr, rank_gain, tfd, sgn):
    """A short text key. tfd = {tf: numbers} (pd_tsi.Klines.tf_data); sgn = +1 pump / -1 dump. Side-aligned: 's' = with the move, 'o' = against it."""
    v = "v1" if vr < 4 else ("v2" if vr < 8 else "v3")
    agree = 0
    for d in tfd.values():
        if d.get("tsi_up") is not None and d.get("hist_change") is not None and (d["tsi_up"] == (sgn > 0)) and sgn * d["hist_change"] > 0:
            agree += 1
    a = "a?" if not tfd else ("a0" if agree <= 1 else ("a1" if agree <= 3 else "a2"))
    z = "z?"
    zd = tfd.get("1h") or tfd.get("15m")
    if zd and zd.get("tsi") is not None:
        z = "zs" if sgn * zd["tsi"] > 0 else "zo"
    h = "h?"
    hd = tfd.get("15m")
    if hd and hd.get("hist_change") is not None:
        h = "hs" if sgn * hd["hist_change"] > 0 else "ho"
    r = "rt" if kind == "run" else ("r0" if rank_gain < 12 else ("r1" if rank_gain < 20 else "r2"))
    return "|".join(["pump" if sgn > 0 else "dump", kind, v, a, z, h, r])


class Chance:
    def __init__(self):
        self.stats = ST.read_json("movers_chance.json", {})
        self.stats.setdefault("buckets", {})
        self.stats.setdefault("kinds", {})
        self.pending = list(ST.read_json("movers_pending.json", {}).get("items", []))
        self.last_log = {}
        self._saved = 0.0

    def add(self, sym, side, kind, price, key, score, now):
        """Save one alert for the later check. One per coin + side + kind per 60 min. Returns True when saved."""
        k = (sym, side, kind)
        if now - self.last_log.get(k, 0.0) < CHECK_MIN * 60:
            return False
        self.last_log[k] = now
        self.pending.append({"id": "%d-%s-%s-%s" % (int(now), sym, side, kind), "symbol": sym, "side": side, "kind": kind, "ts": int(now), "day": C.day_of(now),
                             "price": price, "bucket": key, "score": score, "mfe": 0.0})
        return True

    def track(self, prices, now):
        keep, done = [], False
        for o in self.pending:
            p = prices.get(o["symbol"])
            sgn = 1.0 if o["side"] == "pump" else -1.0
            if p and o["price"]:
                o["mfe"] = max(o["mfe"], sgn * (p / o["price"] - 1.0) * 100.0)
            if now >= o["ts"] + CHECK_MIN * 60:
                self._finish(o)
                done = True
            else:
                keep.append(o)
        self.pending = keep
        if done:
            ST.write_json("movers_chance.json", self.stats)
        if now - self._saved > 60:
            self._saved = now
            try:
                ST.write_json("movers_pending.json", {"items": self.pending})
            except Exception as e:
                print("[pd] movers pending save failed: %s" % e)

    def _finish(self, o):
        worked = o["mfe"] >= C.get("real_move")
        for tbl, key in ((self.stats["buckets"], o["bucket"]), (self.stats["kinds"], "%s|%s" % (o["side"], o["kind"]))):
            w, n = tbl.get(key, [0, 0])
            tbl[key] = [w + (1 if worked else 0), n + 1]
        ST.append("movers_out", o["day"], {"id": o["id"], "symbol": o["symbol"], "side": o["side"], "kind": o["kind"], "ts": o["ts"], "price": o["price"],
                                           "bucket": o["bucket"], "score": o["score"], "mfe": round(o["mfe"], 2), "worked": worked})

    def rate(self, key, side, kind):
        """-> {"pct": 0-100, "est": True = still an estimate, "worked": n, "checked": n}."""
        wo, no = self.stats["kinds"].get("%s|%s" % (side, kind), [0, 0])
        p0 = (wo + C.get("chance_prior") * 10.0) / (no + 10.0)
        w, n = self.stats["buckets"].get(key, [0, 0])
        if n >= C.get("min_outcomes"):
            return {"pct": int(round(100.0 * w / n)), "est": False, "worked": w, "checked": n}
        k = C.get("chance_k")
        return {"pct": int(round(100.0 * (w + k * p0) / (n + k))), "est": True, "worked": w, "checked": n}
