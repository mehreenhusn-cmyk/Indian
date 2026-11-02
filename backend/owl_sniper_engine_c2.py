"""owl_sniper_engine_c2.py - OwlSniper ENGINE PART C2 of 3: the SD-length / settings SEARCH (train days only) and the OwlSniperEngine class (backend, plain python).
Imports owl_sniper_engine_a, _b and _c1. Nothing is traded, nothing is saved here. The engine is a WATCHER: it never opens or closes a trade
(live orders belong to owl_sniper_exec.py, which is OFF by default and needs a deliberate 2-step arm).
The search only ever looks at TRAIN days; only the one winner is then shown the TEST days once. "200 is wrong" is said ONLY when the winner also beats 200
on the TEST days, with enough trades and a t-stat >= 2. Else: NOT PROVEN and the settings stay as they are.
EXCLUDED on purpose: CHoCH and BOS (market structure)."""
import random

from owl_sniper_engine_b import DEFAULTS, EXCLUDED, build_features, raw_signal
from owl_sniper_engine_c1 import (MIN_DAYS, MIN_TRAIN_TRADES, MIN_TEST_TRADES, T_NEEDED, MARGIN_FRAC, SD_CURVE, cost_pct,
                                  stats_of, prep_sets, trades_for)

VERSION = "owl_sniper_engine_c2 1 (Part C2)"

def _score(st, capital):
    """TRAIN score: net USDT minus half the worst dip. Too few trades = unusable."""
    return -1e9 if st["trades"] < MIN_TRAIN_TRADES else st["net_usdt"] - 0.5 * st["worst_dip_usdt"]


def sample_cfg(rng):
    return {"sd_len": rng.randint(20, 200), "fast_ema": rng.randint(10, 40), "slow_ema": rng.randint(45, 75),
            "z_mult": round(rng.uniform(1.5, 2.5), 2), "regime_ratio": round(rng.uniform(0.8, 1.2), 2)}


def search_params(candle_sets, n_trials=60, seed=42, tp_pct=1.5, capital=10.0, base=None):
    """The honest search. Random trials look at TRAIN days only. The best TRAIN setting and the old one (200 / 30 / 50) are then both shown the TEST days once.
    -> dict with verdict BETTER_PROVEN / NOT_PROVEN / NOT_ENOUGH_DATA, both settings with train + test numbers, the SD-length curve and plain lines."""
    base_cfg = dict(DEFAULTS)
    base_cfg.update(base or {})
    sets, left = prep_sets(candle_sets)
    res = {"version": VERSION, "verdict": "NOT_ENOUGH_DATA", "coins_used": len(sets), "coins_left_out": left, "trials": 0, "tp_pct": tp_pct, "cost_pct": round(cost_pct(), 4),
           "split": None, "old": None, "best": None, "best_cfg": None, "curve": [], "guard": None, "lines": []}
    if not sets:
        res["lines"].append("Not enough whole days of candles (need at least %d days per coin). Settings stay as they are." % MIN_DAYS)
        return res
    res["split"] = {"train_days": min(s["days"][0] for s in sets), "test_days": min(s["days"][1] for s in sets)}

    def both(cfg, use_regime=True):
        a, b = trades_for(sets, cfg, tp_pct, use_regime, capital)
        return {"cfg": cfg, "train": stats_of(a, capital), "test": stats_of(b, capital)}, a, b

    old, _, _ = both(base_cfg)
    res["old"] = old
    rng = random.Random(seed)
    best_cfg, best_sc = None, -1e9
    for _ in range(int(n_trials)):
        cfg = dict(base_cfg, **sample_cfg(rng))
        if cfg["fast_ema"] >= cfg["slow_ema"]:
            continue
        a = trades_for(sets, cfg, tp_pct, True, capital, test=False)[0]
        sc = _score(stats_of(a, capital), capital)
        res["trials"] += 1
        if sc > best_sc:
            best_cfg, best_sc = cfg, sc
    for ln in SD_CURVE:                                       # the readable "is 200 right?" curve, only the SD length changes
        row, _, _ = both(dict(base_cfg, sd_len=ln))
        res["curve"].append({"sd_len": ln, "train_net": row["train"]["net_usdt"], "train_trades": row["train"]["trades"],
                             "test_net": row["test"]["net_usdt"], "test_trades": row["test"]["trades"]})
    if best_cfg is None:
        res["verdict"] = "NOT_PROVEN"
        res["lines"].append("No setting made %d or more trades on the TRAIN days. Settings stay as they are." % MIN_TRAIN_TRADES)
        return res
    best, _, _ = both(best_cfg)
    res["best"], res["best_cfg"] = best, best_cfg
    nog, _, _ = both(best_cfg, use_regime=False)              # what the sideways guard added or cost on the TEST days
    res["guard"] = {"test_net_with": best["test"]["net_usdt"], "test_trades_with": best["test"]["trades"], "test_net_without": nog["test"]["net_usdt"], "test_trades_without": nog["test"]["trades"]}
    bt, ot = best["test"], old["test"]
    proven = (bt["trades"] >= MIN_TEST_TRADES and bt["net_usdt"] > 0 and bt["net_usdt"] > ot["net_usdt"] + MARGIN_FRAC * capital and bt["t_stat"] is not None and bt["t_stat"] >= T_NEEDED)
    res["verdict"] = "BETTER_PROVEN" if proven else ("NOT_ENOUGH_DATA" if bt["trades"] < MIN_TEST_TRADES else "NOT_PROVEN")
    res["lines"] = calibration_lines(res)
    return res


def calibration_lines(res):
    """Plain lines for the Insight Report: what was tested, what won on TRAIN, what it did on TEST, and whether 200 is really wrong."""
    L = []
    sp, o, b = res.get("split"), res.get("old"), res.get("best")
    if not o:
        return list(res.get("lines") or [])
    L.append("Tested %d coins, %d random settings on %d TRAIN days; the winner was then shown %d unseen TEST days. Cost counted: %.2f%% per round trip (fee + slippage)." %
             (res["coins_used"], res["trials"], sp["train_days"], sp["test_days"], res["cost_pct"]))
    L.append("Old setting (SD %d, EMA %d/%d): TEST %d trades, net %+.2f USDT." % (o["cfg"]["sd_len"], o["cfg"]["fast_ema"], o["cfg"]["slow_ema"], o["test"]["trades"], o["test"]["net_usdt"]))
    if b:
        c = res["best_cfg"]
        L.append("TRAIN winner (SD %d, EMA %d/%d, stop %.2f SD, sideways ratio %.2f): TEST %d trades, net %+.2f USDT, worst dip %.2f USDT, t-stat %s." %
                 (c["sd_len"], c["fast_ema"], c["slow_ema"], c["z_mult"], c["regime_ratio"], b["test"]["trades"], b["test"]["net_usdt"], b["test"]["worst_dip_usdt"], b["test"]["t_stat"]))
    v = res["verdict"]
    if v == "BETTER_PROVEN":
        L.append("RESULT: the new setting beat the old one on unseen days with enough trades. It is now used%s." % ("; SD length 200 was NOT the best" if res["best_cfg"]["sd_len"] != 200 else ""))
    elif v == "NOT_ENOUGH_DATA":
        L.append("RESULT: too few TEST trades (need %d). Nothing is proven, settings stay as they are. More days of candles are needed." % MIN_TEST_TRADES)
    else:
        L.append("RESULT: NOT PROVEN. The winner did not clearly beat the old setting on unseen days (it can be luck). Settings stay as they are.")
    g = res.get("guard")
    if g:
        L.append("Sideways guard on TEST days: with guard %+.2f USDT (%d trades), without %+.2f USDT (%d trades)." % (g["test_net_with"], g["test_trades_with"], g["test_net_without"], g["test_trades_without"]))
    return L


class OwlSniperEngine:
    """Holds the settings: features + raw signal + regime (Part B) and calibrate() (SD-length search on train days, check on test days, USDT fees).
    The win-probability, the 85% floor and the Insight Report sit on top of this class in owl_sniper_prob.py. The engine is a WATCHER: it never opens or closes a trade."""

    def __init__(self, target_profit_pct=1.5, stop_loss_buffer_sd=2.0, capital_usdt=10.0, floor=0.85):
        self.tp_target = float(target_profit_pct) / 100.0
        self.capital = float(capital_usdt)
        self.floor = float(floor)
        self.optimal_config = dict(DEFAULTS, z_mult=float(stop_loss_buffer_sd))
        self.is_trained = False                 # becomes True when owl_sniper_prob.py has learned the win-probability
        self.calibrated = False
        self.calibration = None
        self.excluded = EXCLUDED

    def features(self, candles, cfg=None):
        """build_features with this engine's settings (or the cfg given, for the search)."""
        use = dict(self.optimal_config)
        use.update(cfg or {})
        return build_features(candles, use)

    def scan(self, candles):
        """Newest closed candle: raw signal + regime. -> dict. owl_sniper_prob.py puts the probability and the 85% floor on top of this."""
        S = self.features(candles)
        i = S["n"] - 1
        sig = raw_signal(S, i)
        return {"version": VERSION, "n": S["n"], "regime": sig["regime"], "side": sig["side"], "why": sig["why"], "z": sig["z"], "hist": sig["hist"],
                "sd_len": S["cfg"]["sd_len"], "blocked_by_regime": bool(sig["side"]) and sig["regime"] != "TRENDING"}

    def calibrate(self, candle_sets, n_trials=60, seed=42):
        """The honest search (see search_params). The settings change ONLY when the verdict is BETTER_PROVEN; else they stay as they are.
        candle_sets = one gap-free candle list per coin. -> the result dict (its "lines" are plain text for the Insight Report)."""
        res = search_params(candle_sets, n_trials, seed, self.tp_target * 100.0, self.capital, base=self.optimal_config)
        if res["verdict"] == "BETTER_PROVEN":
            self.optimal_config.update(res["best_cfg"])
        self.calibration, self.calibrated = res, res["verdict"] != "NOT_ENOUGH_DATA"
        return res

    def collect_trades(self, candle_sets):
        """The trades of the CURRENT settings, split into TRAIN and TEST (owl_sniper_prob.py learns the win-probability from TRAIN and checks the 85% floor on TEST). -> (train, test)."""
        sets, _left = prep_sets(candle_sets)
        return trades_for(sets, self.optimal_config, self.tp_target * 100.0, True, self.capital)
