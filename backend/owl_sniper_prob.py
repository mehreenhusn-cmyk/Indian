"""owl_sniper_prob.py - OwlSniper Part S3 of 7: the WIN-PROBABILITY, the 85% FLOOR, evaluate_live() and the INSIGHT REPORT (backend, plain python, NO numpy / pandas / sklearn / optuna).
Standalone and read-only. It only imports owl_sniper_engine.py (Parts S1 + S2, untouched). Nothing is traded, nothing is saved here (Part S4 saves the result file).
Why a NEW file: the engine file is already 487 lines and the owner rule is "no file over 350 lines", so Part S3 sits beside it, not inside it.
What it does:
  1. learn()      takes the TRAIN trades of the current engine settings and learns "how likely is this signal to win?" with a small logistic model (4 numbers in: Z-Score, TSI histogram, EMA cloud width, volatility ratio).
  2. The 85% floor is then judged on the TEST days ONLY (never seen by the model): the signals the model rated 85% or more must really have won at 85% or more, with at least 15 trades and a profit after fees.
     If that is not proven, NO signal can pass (reason is written plainly). The floor is never lowered to make it pass.
  3. evaluate_live(candles) looks at the newest closed candle: indicator signal -> sideways guard -> stop distance -> win chance -> 85% floor -> action + one plain report line for the Flutter screen.
Actions: STANDBY (not ready), SCANNING_MARKET (no signal), BLOCK_TRADE (a signal was stopped, the reason says why), SNIPER_LONG / SNIPER_SHORT (every check passed; this is a WATCH result, no order is ever sent).
Candles in: same two shapes as the engine (list of dicts or tuples), oldest first, the last one a CLOSED candle."""
import math

import owl_sniper_engine as E

VERSION = "owl_sniper_prob 1 (Part S3)"
FEATS = ("z_dir", "hist_dir", "gap_pct", "vi_ratio")      # z and hist are turned so that "+" always means "with the trade direction"
MIN_FIT_TRADES = 30                                         # fewer TRAIN trades than this = no honest model
MAX_FIT_ROWS = 3000                                         # more TRAIN trades than this: every k-th one is used (keeps the phone fast)
EPOCHS, LR, L2 = 300, 0.3, 1.0                              # plain gradient steps, small ridge pull so the weights stay calm
MIN_FLOOR_TRADES = E.MIN_TEST_TRADES                        # same 15 as the SD-length proof
CURVE_CUTS = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9)


# ---------------------------------------------------------------- the small maths (plain python)
def feat_vec(f):
    """One trade's numbers (the 'feat' dict of engine.run_period) -> the 4 model inputs."""
    d = f["dir"]
    return [f["z"] * d, f["hist"] * d, f["gap_pct"], f["vi_ratio"]]


def sigmoid(x):
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-min(x, 60.0)))
    e = math.exp(max(x, -60.0))
    return e / (1.0 + e)


def wilson_low(wins, n, z=1.96):
    """Lower end of the 95% range of a win rate (a small sample can look lucky; this shows how low it could really be)."""
    if n <= 0:
        return 0.0
    p = wins / float(n)
    den = 1.0 + z * z / n
    mid = p + z * z / (2.0 * n)
    spread = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return max(0.0, (mid - spread) / den)


def fit_standardizer(X):
    """Mean and population SD of every input column (SD 0 becomes 1, never a division error)."""
    n, k = len(X), len(X[0])
    mu = [sum(r[j] for r in X) / n for j in range(k)]
    sd = []
    for j in range(k):
        s = math.sqrt(sum((r[j] - mu[j]) ** 2 for r in X) / n)
        sd.append(s if s > 1e-9 else 1.0)
    return mu, sd


def fit_logistic(X, y, l2=L2, lr=LR, epochs=EPOCHS):
    """Logistic regression by plain batch gradient steps. X = standardized rows, y = 0 / 1. Starts from the base win rate. -> (weights, bias)."""
    n, k = len(X), len(X[0])
    p0 = min(max(sum(y) / float(n), 0.01), 0.99)
    w, b = [0.0] * k, math.log(p0 / (1.0 - p0))
    for _ in range(epochs):
        gw, gb = [0.0] * k, 0.0
        for r, t in zip(X, y):
            e = sigmoid(b + sum(w[j] * r[j] for j in range(k))) - t
            gb += e
            for j in range(k):
                gw[j] += e * r[j]
        b -= lr * gb / n
        for j in range(k):
            w[j] -= lr * (gw[j] / n + l2 * w[j] / n)
    return w, b


def predict(model, f):
    """Win chance 0..1 of one signal (f = its 'feat' dict)."""
    x = feat_vec(f)
    s = model["b"] + sum(model["w"][j] * (x[j] - model["mu"][j]) / model["sd"][j] for j in range(len(x)))
    return sigmoid(s)


def log_loss(ps, ys):
    """Average log loss (0.69 = a coin flip; lower is better). None for an empty list."""
    if not ps:
        return None
    tot = 0.0
    for p, t in zip(ps, ys):
        p = min(max(p, 1e-6), 1.0 - 1e-6)
        tot += -(t * math.log(p) + (1 - t) * math.log(1.0 - p))
    return round(tot / len(ps), 4)


def _rows(trades, ps, cut):
    """Win rate and net USDT of the trades whose win chance was >= cut."""
    sel = [t for t, p in zip(trades, ps) if p >= cut]
    w = sum(1 for t in sel if t["win"])
    return {"cut": cut, "trades": len(sel), "wins": w, "win_rate": (w / float(len(sel))) if sel else None,
            "win_low95": round(wilson_low(w, len(sel)), 3) if sel else None, "net_usdt": round(sum(t["net_usdt"] for t in sel), 4)}


# ---------------------------------------------------------------- learn + judge the floor
def learn_model(train, test, floor=0.85):
    """TRAIN trades -> model. TEST trades -> the honest check of the floor. -> dict (JSON friendly): ok, model, curve, floor_check, floor_verified, lines."""
    res = {"version": VERSION, "ok": False, "floor": floor, "train_n": len(train), "test_n": len(test), "model": None, "base_train": None, "base_test": None,
           "loss_train": None, "loss_test": None, "curve": [], "floor_check": None, "floor_verified": False, "feats": list(FEATS), "lines": []}
    L = res["lines"]
    wins = sum(1 for t in train if t["win"])
    if len(train) < MIN_FIT_TRADES:
        L.append("Win-chance model NOT learned: only %d TRAIN trades (need %d). More days of candles are needed. No signal can pass." % (len(train), MIN_FIT_TRADES))
        return res
    if wins in (0, len(train)):
        L.append("Win-chance model NOT learned: all %d TRAIN trades ended the same way (nothing to tell wins from losses). No signal can pass." % len(train))
        return res
    step = -(-len(train) // MAX_FIT_ROWS)
    use = train[::step] if step > 1 else train
    X = [feat_vec(t["feat"]) for t in use]
    y = [1 if t["win"] else 0 for t in use]
    mu, sd = fit_standardizer(X)
    Xs = [[(r[j] - mu[j]) / sd[j] for j in range(len(r))] for r in X]
    w, b = fit_logistic(Xs, y)
    model = {"w": [round(v, 6) for v in w], "b": round(b, 6), "mu": [round(v, 6) for v in mu], "sd": [round(v, 6) for v in sd]}
    res["model"], res["ok"] = model, True
    ptr = [predict(model, t["feat"]) for t in train]
    pte = [predict(model, t["feat"]) for t in test]
    res["base_train"] = wins / float(len(train))
    res["loss_train"] = log_loss(ptr, [1 if t["win"] else 0 for t in train])
    L.append("Win-chance model learned from %d TRAIN trades (%.0f%% of them won). It reads 4 numbers: Z-Score, TSI histogram, EMA cloud width, volatility ratio." % (len(train), 100.0 * res["base_train"]))
    if not test:
        L.append("There are no TEST trades, so the %.0f%% floor cannot be checked. No signal can pass." % (floor * 100))
        return res
    res["base_test"] = sum(1 for t in test if t["win"]) / float(len(test))
    res["loss_test"] = log_loss(pte, [1 if t["win"] else 0 for t in test])
    res["curve"] = [_rows(test, pte, c) for c in CURVE_CUTS]
    fc = _rows(test, pte, floor)
    res["floor_check"] = fc
    res["floor_verified"] = bool(fc["trades"] >= MIN_FLOOR_TRADES and fc["win_rate"] is not None and fc["win_rate"] >= floor and fc["net_usdt"] > 0)
    L.append("On %d unseen TEST trades %.0f%% won in all (log loss %s; 0.69 would be a coin flip)." % (len(test), 100.0 * res["base_test"], res["loss_test"]))
    if fc["trades"]:
        L.append("%.0f%% floor on TEST: %d signals rated %.0f%% or more, %d won (%.0f%%, could be as low as %.0f%%), net %+.2f USDT after fees." %
                 (floor * 100, fc["trades"], floor * 100, fc["wins"], 100.0 * fc["win_rate"], 100.0 * fc["win_low95"], fc["net_usdt"]))
    else:
        L.append("%.0f%% floor on TEST: no signal was rated %.0f%% or more." % (floor * 100, floor * 100))
    if res["floor_verified"]:
        L.append("RESULT: FLOOR PROVEN on unseen days. Signals of %.0f%% or more may pass." % (floor * 100))
    else:
        L.append("RESULT: FLOOR NOT PROVEN (needs %d or more signals at %.0f%%+ that really won %.0f%%+ and made a profit). No signal can pass. The floor is never lowered." % (MIN_FLOOR_TRADES, floor * 100, floor * 100))
    return res


# ---------------------------------------------------------------- the live engine
class OwlSniperLive(E.OwlSniperEngine):
    """OwlSniperEngine + the win-probability. It is a WATCHER: it never opens or closes a trade."""

    def __init__(self, target_profit_pct=1.5, stop_loss_buffer_sd=2.0, capital_usdt=10.0, floor=0.85, require_proof=True):
        E.OwlSniperEngine.__init__(self, target_profit_pct, stop_loss_buffer_sd, capital_usdt, floor)
        self.require_proof = bool(require_proof)       # True = a signal needs the TEST-day proof of the floor (the safe default)
        self.model = None
        self.model_result = None
        self.floor_verified = False

    # ---- learning
    def learn(self, candle_sets):
        """Learn the win chance from TRAIN trades of the CURRENT settings; judge the floor on TEST trades. Call calibrate() first (or use run_all)."""
        train, test = self.collect_trades(candle_sets)
        res = learn_model(train, test, self.floor)
        self.model_result, self.model = res, res["model"]
        self.is_trained, self.floor_verified = res["ok"], res["floor_verified"]
        return res

    def run_all(self, candle_sets, n_trials=60, seed=42):
        """Part S2 search + Part S3 learning in one go. -> one JSON friendly dict with all the plain lines (Part S4 saves it)."""
        cal = self.calibrate(candle_sets, n_trials, seed)
        prob = self.learn(candle_sets)
        return {"version": VERSION, "calibration": cal, "probability": prob, "config": dict(self.optimal_config), "is_trained": self.is_trained,
                "floor_verified": self.floor_verified, "lines": list(cal.get("lines") or []) + list(prob["lines"])}

    def export_model(self):
        """What a saved result file needs to bring the engine back without learning again."""
        return {"version": VERSION, "config": dict(self.optimal_config), "model": self.model, "floor": self.floor, "floor_verified": self.floor_verified,
                "floor_check": (self.model_result or {}).get("floor_check")}

    def load_model(self, d):
        """The other way round. A bad dict leaves the engine NOT trained (STANDBY)."""
        try:
            self.optimal_config.update(d["config"])
            self.model, self.floor = d["model"], float(d.get("floor", self.floor))
            self.floor_verified = bool(d.get("floor_verified")) and self.model is not None
            self.is_trained = self.model is not None and all(k in self.model for k in ("w", "b", "mu", "sd"))
        except (KeyError, TypeError, ValueError):
            self.model, self.is_trained, self.floor_verified = None, False, False
        return self.is_trained

    # ---- live
    def _out(self, action, reason, S=None, sig=None, p=None, **extra):
        cf = self.optimal_config
        regime = sig["regime"] if sig else "UNKNOWN"
        nice = {"TRENDING": "TRENDING (trades allowed)", "SIDEWAYS": "SIDEWAYS (trades blocked)", "UNKNOWN": "NOT CLEAR YET (trades blocked)"}[regime]
        parts = ["OwlSniper report: lookback SD length %d." % cf["sd_len"], "Market is %s." % nice]
        if sig and sig.get("z") is not None and sig.get("hist") is not None:
            parts.append("Z-Score %.2f, TSI histogram %.2f." % (sig["z"], sig["hist"]))
        parts.append(("Win chance %.1f%% (floor %.0f%%)." % (p * 100.0, self.floor * 100.0)) if p is not None else "No win chance is worked out (no signal passed the first checks).")
        parts.append(reason)
        out = {"version": VERSION, "action": action, "side": (sig or {}).get("side"), "reason": reason, "report": " ".join(parts), "regime": regime,
               "z": (sig or {}).get("z"), "hist": (sig or {}).get("hist"), "sd_len": cf["sd_len"], "confidence": p, "floor": self.floor,
               "floor_verified": self.floor_verified, "n": S["n"] if S else 0, "t": S["t"][-1] if S and S["n"] else None}
        out.update(extra)
        return out

    def evaluate_live(self, candles):
        """The newest CLOSED candle -> {"action", "reason", "report", ...}. Never raises on bad or young candles (they give STANDBY)."""
        try:
            S = self.features(candles)
        except (ValueError, KeyError, IndexError, TypeError) as e:
            return self._out("STANDBY", "The candles could not be read (%s)." % e.__class__.__name__)
        n, cf = S["n"], S["cfg"]
        if n < 2 or E.first_valid(S) >= n:
            return self._out("STANDBY", "Syncing candles: %d are here, about %d are needed." % (n, cf["sd_len"] + cf["regime_win"]), S)
        i = n - 1
        sig = E.raw_signal(S, i)
        if not self.is_trained or self.model is None:
            why = (self.model_result["lines"][-1] if self.model_result and self.model_result.get("lines") else "Run calibrate + learn first.")
            return self._out("STANDBY", "OwlSniper is not calibrated yet. " + why, S, sig)
        if sig["side"] is None:
            return self._out("SCANNING_MARKET", "Watching: " + "; ".join(sig["why"]) + ". No trade.", S, sig)
        side, entry = sig["side"], S["c"][i]
        if sig["regime"] != "TRENDING":
            return self._out("BLOCK_TRADE", "Market is sideways or not clear, so the %s crossover was blocked." % side, S, sig)
        sl = E.stop_price(S, i, side)
        dist = ((entry - sl) if side == "LONG" else (sl - entry)) / entry * 100.0 if sl is not None else 0.0
        if dist < E.MIN_SL_PCT or dist > E.MAX_SL_PCT:
            return self._out("BLOCK_TRADE", "The stop line is %.2f%% away; only %.2f%% to %.2f%% fits a %.0f USDT base." % (dist, E.MIN_SL_PCT, E.MAX_SL_PCT, self.capital), S, sig)
        feat = {"z": sig["z"], "hist": sig["hist"], "gap_pct": sig["gap_pct"], "vi_ratio": S["vi"][i] / S["vi_avg"][i], "dir": 1 if side == "LONG" else -1}
        p = predict(self.model, feat)
        if p < self.floor:
            return self._out("BLOCK_TRADE", "Win chance %.1f%% is below the %.0f%% floor, trade blocked." % (p * 100.0, self.floor * 100.0), S, sig, p)
        if self.require_proof and not self.floor_verified:
            return self._out("BLOCK_TRADE", "Win chance is high enough, but the %.0f%% floor is not proven on the TEST days, so the signal is held back." % (self.floor * 100.0), S, sig, p)
        tp = entry * (1.0 + self.tp_target) if side == "LONG" else entry * (1.0 - self.tp_target)
        return self._out("SNIPER_" + side, "All checks passed (%s). WATCH result only: no order is sent." % "; ".join(sig["why"]), S, sig, p,
                         entry_price=entry, stop_loss=sl, take_profit=tp, stop_pct=round(dist, 3))

    evaluate_live_opportunity = evaluate_live             # the name used in the first prompt

    def insight_report(self, live=None):
        """Everything the Flutter screen may print, as plain lines: what was tested, what was learned, whether the floor is proven, and the live line."""
        lines = list((self.calibration or {}).get("lines") or []) + list((self.model_result or {}).get("lines") or [])
        if not lines:
            lines = ["OwlSniper has not been calibrated yet."]
        return {"version": VERSION, "title": "OwlSniper insight report", "lines": lines, "live": (live or {}).get("report"), "floor": self.floor,
                "floor_verified": self.floor_verified, "is_trained": self.is_trained, "settings": dict(self.optimal_config)}
