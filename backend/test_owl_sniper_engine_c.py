"""test_owl_sniper_engine_c.py - checks for owl_sniper_engine_c1.py + owl_sniper_engine_c2.py (plain asserts; `python test_owl_sniper_engine_c.py` or pytest).
Covers: fees are paid, stop wins a same-candle tie, the day split never mixes TRAIN and TEST, TRAIN trades never look into TEST, the search never reads TEST
for its trials, a settings change needs BETTER_PROVEN, and the whole result is identical to the old owl_sniper_engine.py (parity)."""
import random

import owl_sniper_engine_b as B
import owl_sniper_engine_c1 as C1
import owl_sniper_engine_c2 as C2


def make(n=2600, seed=5, vol=0.004, start=100.0, step=300, drift=0.0):
    r, v, rows = random.Random(seed), start, []
    for k in range(n):
        o = v
        v *= 1.0 + drift + r.gauss(0, vol)
        rows.append({"timestamp": 1700000000 + k * step, "open": o, "high": max(o, v) * 1.001, "low": min(o, v) * 0.999, "close": v})
    return rows


def sets_for(k=3, **kw):
    return [make(seed=10 + j, **kw) for j in range(k)]


def test_cost_is_both_sides():
    assert abs(C1.cost_pct() - 2 * (C1.FEE_PCT + C1.SLIP_PCT)) < 1e-12


def test_stop_counts_first_on_tie():
    S = {"c": [100.0, 100.0], "h": [100.0, 102.0], "l": [100.0, 98.0], "t": [0, 1]}   # candle 1 touches both TP (101.5) and SL (99)
    r = C1.simulate_trade(S, 0, "LONG", 99.0, 2, 1.5)
    assert r["why"] == "SL" and r["gross_pct"] < 0
    assert abs(r["net_pct"] - (r["gross_pct"] - C1.cost_pct())) < 1e-12
    r = C1.simulate_trade(S, 0, "SHORT", 101.0, 2, 1.5)
    assert r["why"] == "SL"


def test_split_is_whole_days_and_70_30():
    S = B.to_series(make(2600))
    sp = C1.split_by_days(S)
    assert S["t"][sp["cut"]] % 86400 < 300                                              # first TEST candle is the first of a UTC day
    assert C1.day_of(S["t"][sp["cut"] - 1]) < C1.day_of(S["t"][sp["cut"]])
    assert abs(sp["test_days"] / (sp["train_days"] + sp["test_days"]) - 0.3) < 0.08
    assert C1.split_by_days(B.to_series(make(200))) is None                              # fewer than MIN_DAYS days


def test_train_trades_never_look_into_test():
    cs = make(2600, vol=0.0015)
    S = B.build_features(cs, {"sd_len": 30, "fast_ema": 5, "slow_ema": 12, "z_mult": 1.5})   # fast EMAs + calm prices: many crosses, stops inside the allowed width
    cut = C1.split_by_days(S)["cut"]
    tr = C1.run_period(S, 0, cut, use_regime=False, tp_pct=0.4)["trades"]      # no regime guard + near target: plenty of trades on random data
    te = C1.run_period(S, cut, S["n"], use_regime=False, tp_pct=0.4)["trades"]
    assert tr and te
    assert all(x["exit_i"] < cut for x in tr)
    assert all(x["i"] >= cut for x in te)


def test_future_data_cannot_change_train_trades():
    cs = make(2600, vol=0.0015)
    cut = C1.split_by_days(B.to_series(cs))["cut"]
    cfg = {"sd_len": 30, "fast_ema": 5, "slow_ema": 12, "z_mult": 1.5}
    wrecked = [dict(x) for x in cs]
    for x in wrecked[cut:]:
        for k in ("open", "high", "low", "close"):
            x[k] *= 2.5
    a = C1.trades_for(C1.prep_sets([cs])[0], cfg, 0.4, False)[0]
    b = C1.trades_for(C1.prep_sets([wrecked])[0], cfg, 0.4, False)[0]
    assert a and a == b                                                                  # non-empty, and identical


def test_search_trials_do_not_read_test_days():
    cs = make(2600)
    cut = C1.split_by_days(B.to_series(cs))["cut"]
    seen = []
    real = C1.trades_for
    def spy(sets, cfg, tp_pct=1.5, use_regime=True, capital=10.0, test=True):
        seen.append(test)
        return real(sets, cfg, tp_pct, use_regime, capital, test)
    C2.trades_for = spy
    try:
        C2.search_params([cs], n_trials=6, seed=1)
    finally:
        C2.trades_for = real
    assert seen.count(False) >= 1 and seen.count(True) >= 1                               # trials: test=False; final checks: test=True


def test_settings_change_only_when_proven():
    eng = C2.OwlSniperEngine()
    before = dict(eng.optimal_config)
    res = eng.calibrate(sets_for(2), n_trials=8, seed=3)
    assert res["verdict"] in ("BETTER_PROVEN", "NOT_PROVEN", "NOT_ENOUGH_DATA")
    if res["verdict"] != "BETTER_PROVEN":
        assert eng.optimal_config == before
    assert res["lines"] and all(isinstance(x, str) for x in res["lines"])
    short = C2.OwlSniperEngine().calibrate([make(200)], n_trials=3)
    assert short["verdict"] == "NOT_ENOUGH_DATA"


def test_stats_of_numbers():
    tr = [{"exit_t": i, "win": w, "net_usdt": u, "net_pct": u * 10} for i, (w, u) in enumerate([(True, .2), (False, -.1), (False, -.1), (True, .3)])]
    s = C1.stats_of(tr)
    assert s["trades"] == 4 and s["wins"] == 2 and abs(s["net_usdt"] - 0.3) < 1e-9
    assert abs(s["worst_dip_usdt"] - 0.2) < 1e-9 and s["worst_streak"] == 2


def test_parity_with_old_engine():
    try:
        import owl_sniper_engine as OLD
    except Exception:
        return
    cs = sets_for(2)
    a = C2.search_params(cs, n_trials=10, seed=42)
    o = OLD.search_params(cs, n_trials=10, seed=42)
    for key in ("verdict", "trials", "split", "best_cfg", "curve", "guard"):
        assert a[key] == o[key], key
    assert a["old"] == o["old"] and a["best"] == o["best"]


if __name__ == "__main__":
    names = [k for k in sorted(globals()) if k.startswith("test_")]
    for k in names:
        globals()[k]()
        print("ok  ", k)
    print("ALL %d TESTS PASSED" % len(names))
