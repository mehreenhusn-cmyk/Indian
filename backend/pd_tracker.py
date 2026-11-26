"""pd_tracker.py - keeps the STAGE of every coin that is moving, and makes ONE event when the stage changes (the only thing that reaches the app).
Pump side (+1): WATCH -> START -> RUNNING (one update per further +3% step) -> WEAK -> END.  Dump side (-1): the same, price going down.
  WATCH   volume starts to rise, price moves 0.5%+ (light hint, silent)
  START   volume 5x+ the coin's own hour, price 1%+ in 5 min (or 0.7%+ in 1 min), score 55+ (the main alert, with sound in the app)
  RUNNING the coin keeps going (+3% since START) with volume still 1.5x+; again one update per further 3% step
  WEAK    volume fell back under 1x, or price gave back 1.2%+ from its best: be careful
  END     weak for 10 min, or no follow-through 45 min after START: the coin leaves the list
No spam: one event per stage change (not per minute), at most max_active_side coins per side, one WATCH / START per coin per 30 min.
Nothing here is a buy or sell order."""
import pd_config as C
import pd_scorer as S

SIDES = ((1, "pump"), (-1, "dump"))
LIVE_STAGES = ("START", "RUNNING", "WEAK")


class Tracker:
    def __init__(self, emit):
        self.emit = emit          # emit(event dict)
        self.states = {}          # (symbol, side) -> state dict
        self.last_start = {}      # (symbol, side) -> time of the last START
        self.last_watch = {}
        self.last_any = {}        # (symbol, side) -> time of the last event of any stage (the missed-move check reads it)
        self.recent = []          # newest first: the last 20 START events (the app's alert sound reads them)
        self.adj = {}             # symbol -> score penalty / bonus from the tuner

    # -------------------------------------------------------------- read
    def active(self, side):
        out = []
        for (sym, sd), st in self.states.items():
            if sd == side:
                out.append((sym, st))
        return out

    def is_active(self, sym, side):
        return (sym, side) in self.states

    # -------------------------------------------------------------- step
    def eval_symbol(self, sym, f, now, qv24):
        for sgn, side in SIDES:
            try:
                self._one(sym, sgn, side, f, now, qv24)
            except Exception as e:                     # one coin must never stop the loop
                print(f"[pd] tracker {sym} {side}: {type(e).__name__}: {e}")

    def _weak(self, st, sgn, f, p):
        pull = sgn * (st["peak"] - p) / st["peak"] * 100.0
        return pull >= C.get("weak_pullback") or f["vr5"] < C.get("weak_vol")

    def _one(self, sym, sgn, side, f, now, qv24):
        key = (sym, side)
        st = self.states.get(key)
        sc = S.score(sgn, f, self.adj.get(sym, 0.0))
        p = f["p"]
        if st is None:
            stage = S.classify(sgn, f, sc)
            if stage is None:
                return
            if stage == "START" and now - self.last_start.get(key, 0) < C.get("cool_start_min") * 60:
                return
            if stage == "WATCH" and now - self.last_watch.get(key, 0) < C.get("cool_watch_min") * 60:
                return
            if not self._room(side, sc):
                return
            st = {"stage": stage, "t0": now, "p0": p, "peak": p, "step_p": p, "weak_t": None, "score": sc, "watch_p": p}
            self.states[key] = st
            if stage == "START":
                self.last_start[key] = now
            else:
                self.last_watch[key] = now
            self._event(sym, side, stage, f, now, qv24, sc, st, 0.0, "volume %.1fx, %+.1f%% in 5 min" % (S.vr(f), sgn * f["r5"]))
            return
        if sgn * (p - st["peak"]) > 0:
            st["peak"] = p
        gain = sgn * (p / st["p0"] - 1.0) * 100.0
        age = now - st["t0"]
        stg = st["stage"]
        st["cur"] = {"p": p, "gain": round(gain, 2), "r5": round(f["r5"], 2), "vr5": round(f["vr5"], 1), "score": round(sc, 1)}
        if stg == "WATCH":
            cand = S.classify(sgn, f, sc)
            if cand == "START" and now - self.last_start.get(key, 0) >= C.get("cool_start_min") * 60:
                watch_gain = gain
                st.update(stage="START", t0=now, p0=p, peak=p, step_p=p, score=sc)
                self.last_start[key] = now
                self._event(sym, side, "START", f, now, qv24, sc, st, watch_gain, "volume %.1fx, %+.1f%% in 5 min" % (S.vr(f), sgn * f["r5"]))
            elif age > C.get("watch_ttl_min") * 60 or (sgn * f["r5"] < 0.2 and S.vr(f) < 1.5):
                del self.states[key]                    # the hint faded: silent, no event
            return
        if stg == "START":
            if gain >= C.get("run_gain") and f["vr5"] >= C.get("run_vol"):
                st.update(stage="RUNNING", step_p=p, score=sc)
                self._event(sym, side, "RUNNING", f, now, qv24, sc, st, gain, "%+.1f%% since START, volume %.1fx" % (gain, f["vr5"]))
            elif age >= 180 and self._weak(st, sgn, f, p):
                self._to_weak(sym, side, f, now, qv24, sc, st, gain)
            elif age > C.get("start_fail_min") * 60 and gain < 1.0:
                self._end(sym, side, f, now, qv24, sc, st, gain, "no follow-through")
            return
        if stg == "RUNNING":
            if self._weak(st, sgn, f, p):
                self._to_weak(sym, side, f, now, qv24, sc, st, gain)
            elif sgn * (p / st["step_p"] - 1.0) * 100.0 >= C.get("run_gain"):
                st["step_p"] = p
                self._event(sym, side, "RUNNING", f, now, qv24, sc, st, gain, "%+.1f%% since START, volume %.1fx" % (gain, f["vr5"]))
            return
        if stg == "WEAK":
            if sgn * (p - st["peak"]) >= 0 and f["vr5"] >= 2.0 and gain > 0:
                st.update(stage="RUNNING", weak_t=None, step_p=p)
                self._event(sym, side, "RUNNING", f, now, qv24, sc, st, gain, "moving again, volume %.1fx" % f["vr5"])
            elif now - (st["weak_t"] or now) >= C.get("end_after_weak_min") * 60:
                self._end(sym, side, f, now, qv24, sc, st, gain, "weak for %d min" % C.get("end_after_weak_min"))

    # -------------------------------------------------------------- helpers
    def _to_weak(self, sym, side, f, now, qv24, sc, st, gain):
        st.update(stage="WEAK", weak_t=now)
        self._event(sym, side, "WEAK", f, now, qv24, sc, st, gain, "volume %.1fx, gave back %.1f%% from the best" % (f["vr5"], abs(st["peak"] / f["p"] - 1.0) * 100.0))

    def _end(self, sym, side, f, now, qv24, sc, st, gain, why):
        self.states.pop((sym, side), None)
        self._event(sym, side, "END", f, now, qv24, sc, st, gain, why)

    def _room(self, side, sc):
        cur = self.active(side)
        if len(cur) < C.get("max_active_side"):
            return True
        weak_watch = [(s["score"], sym) for sym, s in cur if s["stage"] == "WATCH"]
        if weak_watch:
            low = min(weak_watch)
            if sc > low[0]:
                self.states.pop((low[1], side), None)   # a better coin pushes the weakest WATCH out (silent)
                return True
        return False

    def _event(self, sym, side, stage, f, now, qv24, sc, st, gain, note):
        ev = {"id": "%d-%s-%s" % (int(now * 1000), sym, side), "ts": int(now), "day": C.day_of(now), "time": C.clock_of(now),
              "symbol": sym, "side": side, "stage": stage, "price": f["p"], "score": round(sc, 1),
              "r1": round(f["r1"], 2), "r5": round(f["r5"], 2), "r15": round(f["r15"], 2), "vr1": round(f["vr1"], 1), "vr5": round(f["vr5"], 1),
              "qv24": round(qv24), "gain": round(gain, 2), "brk": bool(f["brk_up"] if side == "pump" else f["brk_dn"]), "flat": bool(f["flat"]),
              "note": note}
        self.last_any[(sym, side)] = now
        if stage == "START":
            self.recent.insert(0, {"id": ev["id"], "symbol": sym, "side": side, "ts": ev["ts"], "price": ev["price"], "score": ev["score"]})
            del self.recent[20:]
        try:
            self.emit(ev)
        except Exception as e:
            print(f"[pd] emit failed: {type(e).__name__}: {e}")

    # -------------------------------------------------------------- snapshot (for the app + a restart)
    def snapshot(self):
        out = {"pump": [], "dump": []}
        for (sym, side), st in self.states.items():
            cur = st.get("cur") or {}
            out[side].append({"symbol": sym, "stage": st["stage"], "since": int(st["t0"]), "p0": st["p0"], "peak": st["peak"],
                              "price": cur.get("p", st["p0"]), "gain": cur.get("gain", 0.0), "r5": cur.get("r5", 0.0), "vr5": cur.get("vr5", 0.0),
                              "score": cur.get("score", round(st["score"], 1))})
        for side in out:
            out[side].sort(key=lambda r: -r["score"])
        return out
