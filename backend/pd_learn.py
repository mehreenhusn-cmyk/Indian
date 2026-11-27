"""pd_learn.py - the SELF-LEARNING of the Pump / Dump scanner (simple rules, not AI).
  1 OUTCOMES  every START is saved; after 15 / 30 / 60 min the move is checked: REAL = the coin moved 2%+ the right way inside 60 min, else FAKE.
  2 MISSED    a coin that moved 5%+ in 30 min with no alert is saved with its numbers (so the rules can be seen to be too strict).
  3 TUNER     once a day: a small report (which rule gave real pumps / dumps, which gave fake ones), a score penalty for coins that give fake alerts
              again and again (a small bonus for clean ones), and the start / watch volume threshold moves ONE small step (never outside its bounds),
              only after min_outcomes (100) checked alerts of the last 14 days. Every change is written down with its reason. auto_tune off = report only.
4 STUDY     (Round 4, Part 5) every START also keeps the indicator snapshot (TSI / Z / ZSM / EMA per time frame) and its move after 1 h / 4 h / 1 day in
              study_rows/<day>.jsonl. pd_study.py reads those rows once a day. This does NOT change outcomes, tuner or alerts.
Nothing here places an order."""
import time

import pd_config as C
import pd_store as ST

CHECKS = (15, 30, 60)
STUDY_H = (60, 240, 1440)   # minutes after the START that the study looks at


class Learner:
    def __init__(self):
        self.pending = []         # alerts waiting for their 15 / 30 / 60 min check
        self.last_missed = {}
        self._saved = 0.0
        self.tuner = ST.read_json("tuner.json", {})
        self.tuner.setdefault("coin_adj", {})
        self.tuner.setdefault("changes", [])
        self.tuner.setdefault("auto_tune", True)
        self.tuner.setdefault("last_tune_day", "")
        for p in ST.read_json("pending.json", {}).get("items", []):
            self.pending.append(p)
        self.sp = list(ST.read_json("study_pending.json", {}).get("items", []))   # STARTs waiting for their 1 h / 4 h / 1 day result (study only)

    # -------------------------------------------------------------- 1 outcomes
    def add_start(self, ev, feat=None):
        if feat:                                           # Round 4: the indicator snapshot at the START (None = no candle data yet, not studied)
            self.sp.append({"id": ev["id"], "symbol": ev["symbol"], "side": ev["side"], "ts": ev["ts"], "day": ev["day"], "price": ev["price"],
                            "score": ev["score"], "feat": feat, "m": {}, "mfe": 0.0, "mae": 0.0})
        self.pending.append({"id": ev["id"], "symbol": ev["symbol"], "side": ev["side"], "ts": ev["ts"], "day": ev["day"], "price": ev["price"],
                             "score": ev["score"], "brk": ev.get("brk", False), "flat": ev.get("flat", False), "vr5": ev.get("vr5", 0.0),
                             "mfe": 0.0, "mae": 0.0, "pct": {}})

    def track(self, prices, now):
        """prices: symbol -> last price. Updates best / worst move and writes the finished outcomes."""
        keep = []
        for o in self.pending:
            p = prices.get(o["symbol"])
            sgn = 1.0 if o["side"] == "pump" else -1.0
            if p:
                mv = sgn * (p / o["price"] - 1.0) * 100.0
                o["mfe"] = max(o["mfe"], mv)
                o["mae"] = min(o["mae"], mv)
                for m in CHECKS:
                    if str(m) not in o["pct"] and now >= o["ts"] + m * 60:
                        o["pct"][str(m)] = round(mv, 2)
            if "60" in o["pct"] or (now - o["ts"] > 3 * 3600):
                self._finish(o)
            else:
                keep.append(o)
        self.pending = keep
        self._track_study(prices, now)
        if now - self._saved > 60:
            self.save_pending(now)

    def _track_study(self, prices, now):
        """Round 4: the move (in the alert's direction, %) at 1 h / 4 h / 1 day after each START. A problem here never touches the alerts."""
        try:
            keep = []
            for o in self.sp:
                p = prices.get(o["symbol"])
                if p:
                    mv = (1.0 if o["side"] == "pump" else -1.0) * (p / o["price"] - 1.0) * 100.0
                    if now <= o["ts"] + STUDY_H[1] * 60:
                        o["mfe"], o["mae"] = max(o["mfe"], mv), min(o["mae"], mv)
                    for m in STUDY_H:
                        if str(m) not in o["m"] and now >= o["ts"] + m * 60:
                            o["m"][str(m)] = round(mv, 2)
                if str(STUDY_H[2]) in o["m"] or now - o["ts"] > 26 * 3600:
                    if "60" in o["m"]:
                        ST.append("study_rows", o["day"], {"id": o["id"], "symbol": o["symbol"], "side": o["side"], "ts": o["ts"], "day": o["day"], "price": o["price"],
                                                           "score": o["score"], "feat": o["feat"], "m60": o["m"].get("60"), "m240": o["m"].get("240"),
                                                           "m1440": o["m"].get("1440"), "mfe240": round(o["mfe"], 2), "mae240": round(o["mae"], 2)})
                else:
                    keep.append(o)
            self.sp = keep
        except Exception as e:
            print(f"[pd] study track failed: {type(e).__name__}: {e}")

    def _finish(self, o):
        last = o["pct"].get("60", o["pct"].get("30", o["pct"].get("15", 0.0)))
        rec = {"id": o["id"], "symbol": o["symbol"], "side": o["side"], "ts": o["ts"], "day": o["day"], "price": o["price"], "score": o["score"],
               "brk": o["brk"], "flat": o["flat"], "vr5": o["vr5"], "pct15": o["pct"].get("15"), "pct30": o["pct"].get("30"), "pct60": o["pct"].get("60"),
               "mfe": round(o["mfe"], 2), "mae": round(o["mae"], 2), "real": o["mfe"] >= C.get("real_move"), "last": last}
        ST.append("outcomes", o["day"], rec)

    def save_pending(self, now):
        self._saved = now
        try:
            ST.write_json("pending.json", {"items": self.pending})
            ST.write_json("study_pending.json", {"items": self.sp})
        except Exception as e:
            print(f"[pd] pending save failed: {e}")

    # -------------------------------------------------------------- 2 missed
    def check_missed(self, sym, f, now, tracker, qv24):
        for sgn, side in ((1, "pump"), (-1, "dump")):
            if sgn * f["r30"] < C.get("missed_move"):
                continue
            key = (sym, side)
            if tracker.is_active(sym, side) or now - tracker.last_any.get(key, 0) < 3600 or now - self.last_missed.get(key, 0) < 3600:
                continue
            self.last_missed[key] = now
            ST.append("missed", C.day_of(now), {"ts": int(now), "time": C.clock_of(now), "symbol": sym, "side": side, "price": f["p"], "r30": round(f["r30"], 2),
                                                "r5": round(f["r5"], 2), "r15": round(f["r15"], 2), "vr5": round(f["vr5"], 1), "vr1": round(f["vr1"], 1),
                                                "flat": bool(f["flat"]), "qv24": round(qv24), "warm": bool(f["warm"])})

    # -------------------------------------------------------------- 3 tuner
    def _recent_outcomes(self, days, now):
        out = []
        t = now
        for _ in range(days):
            out.extend(ST.read_day("outcomes", C.day_of(t)))
            t -= 86400
        return out

    @staticmethod
    def _rate(rows):
        n = len(rows)
        r = sum(1 for x in rows if x.get("real"))
        return {"n": n, "real": r, "rate": round(r / n, 2) if n else None}

    def tune_if_due(self, now, tracker):
        day = C.day_of(now)
        if self.tuner.get("last_tune_day") == day:
            return False
        if time.gmtime(now + C.get("tz_min") * 60).tm_hour == 0 and time.gmtime(now + C.get("tz_min") * 60).tm_min < 10:
            return False                                   # wait until 00:10 IST, so the day that just ended is complete
        self.run_tuner(now, tracker)
        return True

    def run_tuner(self, now, tracker):
        rows = self._recent_outcomes(14, now)
        total = self._rate(rows)
        rules = {
            "pump": self._rate([x for x in rows if x["side"] == "pump"]), "dump": self._rate([x for x in rows if x["side"] == "dump"]),
            "breakout": self._rate([x for x in rows if x.get("brk")]), "no_breakout": self._rate([x for x in rows if not x.get("brk")]),
            "flat_before": self._rate([x for x in rows if x.get("flat")]), "not_flat": self._rate([x for x in rows if not x.get("flat")]),
            "volume_5_to_8x": self._rate([x for x in rows if 5 <= (x.get("vr5") or 0) < 8]), "volume_8x_plus": self._rate([x for x in rows if (x.get("vr5") or 0) >= 8]),
            "score_55_70": self._rate([x for x in rows if 55 <= x["score"] < 70]), "score_70_plus": self._rate([x for x in rows if x["score"] >= 70]),
        }
        # coin penalty / bonus (needs 3+ checked alerts of the same coin)
        by = {}
        for x in rows:
            by.setdefault(x["symbol"], []).append(x)
        adj_old = dict(self.tuner.get("coin_adj", {}))
        adj_new = {}
        fake, clean = [], []
        for sym, lst in by.items():
            if len(lst) < 3:
                continue
            r = self._rate(lst)
            target = 0.0
            if r["rate"] < 0.30:
                target = -min(15.0, 5.0 * (len(lst) // 3))
                fake.append({"symbol": sym, **r})
            elif r["rate"] >= 0.70:
                target = 5.0
                clean.append({"symbol": sym, **r})
            cur = float(adj_old.get(sym, 0.0))
            step = max(-5.0, min(5.0, target - cur))      # moves at most 5 points a day
            if abs(cur + step) >= 0.5:
                adj_new[sym] = cur + step
        for sym, v in adj_old.items():                    # coins with no new data fade back to 0
            if sym not in by and abs(v) >= 0.5:
                step = -5.0 if v > 0 else 5.0
                nv = v + step if abs(v) > 5.0 else 0.0
                if abs(nv) >= 0.5:
                    adj_new[sym] = nv
        self.tuner["coin_adj"] = adj_new
        tracker.adj = dict(adj_new)
        changes = []
        missed_n = sum(len(ST.read_day("missed", C.day_of(now - i * 86400))) for i in range(14))
        enough = total["n"] >= C.get("min_outcomes")
        if self.tuner.get("auto_tune", True) and enough and total["rate"] is not None:
            old = C.get("start_vol")
            lo, hi, stp = C.TUNABLE["start_vol"]
            new = old
            why = ""
            if total["rate"] < 0.35:
                new, why = min(hi, old + stp), "only %d%% of the last %d alerts were real: stricter volume" % (round(total["rate"] * 100), total["n"])
            elif total["rate"] > 0.65 and missed_n > total["n"]:
                new, why = max(lo, old - stp), "%d%% real but %d missed moves: earlier volume trigger" % (round(total["rate"] * 100), missed_n)
            if new != old:
                C.set_override("start_vol", new)
                changes.append({"day": C.day_of(now), "key": "start_vol", "old": old, "new": new, "why": why})
        self.tuner["overrides"] = C.overrides()
        self.tuner["changes"] = (self.tuner.get("changes", []) + changes)[-50:]
        self.tuner["last_tune_day"] = C.day_of(now)
        ST.write_json("tuner.json", self.tuner)
        report = {"day": C.day_of(now), "generated": int(now), "outcomes_14d": total, "rules": rules, "missed_14d": missed_n,
                  "fake_coins": sorted(fake, key=lambda x: x["rate"])[:8], "clean_coins": sorted(clean, key=lambda x: -x["rate"])[:8],
                  "enough_data": enough, "min_outcomes": C.get("min_outcomes"), "changes_today": changes, "auto_tune": self.tuner.get("auto_tune", True),
                  "start_vol": C.get("start_vol"), "watch_vol": C.get("watch_vol")}
        ST.write_json("reports/%s.json" % C.day_of(now), report)
        ST.prune(C.get("keep_days"))
        return report

    def set_auto_tune(self, on):
        self.tuner["auto_tune"] = bool(on)
        ST.write_json("tuner.json", self.tuner)
