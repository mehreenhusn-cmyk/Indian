"""owl_sniper_barriers.py - OwlSniper Round 19: the TRIPLE BARRIER on every signal (backend, plain python, NO numpy / pandas / sklearn).
Read-only: nothing is traded, nothing is saved, no network. Imports only owl_sniper_engine_b (signal, regime) and owl_sniper_engine_c1 (fee + slippage, simulator).
The idea (in plain words): every signal gets THREE exits that are set BEFORE the trade, scaled by how much the coin really moves (ATR = average candle range of the last 14 candles):
  profit barrier   entry +- K_TP x ATR   (default 2.0)   stop barrier  entry -+ K_SL x ATR   (default 1.0)   time barrier  HOLD candles (the engine's MAX_HOLD, 30) then close at the candle close.
If one candle touches both the stop and the profit line, the STOP counts first (the bad case). Fee + slippage are paid on both sides, like everywhere in the Sniper.
A stop wider than MAX_SL_PCT or tighter than MIN_SL_PCT of price is refused (same limits as the engine, made for a 10 USDT base).
plan_for_signal() gives the lines for a live signal card; barrier_label() works out what a past signal would have done; evidence() replays a whole period for the evidence check.
Nothing here is proven to make money: evidence() only shows what the same signals would have done with these exits, and compare_fixed() puts that next to the old fixed exit on the SAME signals."""
import owl_sniper_engine_b as B
import owl_sniper_engine_c1 as C

VERSION = "owl_sniper_barriers 1 (Round 19)"
ATR_LEN = 14
K_TP, K_SL = 2.0, 1.0
HOLD = C.MAX_HOLD


def atr_pct(S, i, n=ATR_LEN):
    """Average true range of the n candles ending at candle i, in % of that close. None while fewer than n + 1 candles exist."""
    if i < n or i >= S["n"]:
        return None
    tot = 0.0
    for k in range(i - n + 1, i + 1):
        pc = S["c"][k - 1]
        tot += max(S["h"][k] - S["l"][k], abs(S["h"][k] - pc), abs(S["l"][k] - pc))
    return tot / n / S["c"][i] * 100.0


def barriers(S, i, side, k_tp=K_TP, k_sl=K_SL, hold=HOLD):
    """The three lines of a signal at candle i. -> {ok, ...}. ok False carries a plain 'reason' (never a guessed number)."""
    v = atr_pct(S, i)
    if v is None or v <= 0:
        return {"ok": False, "reason": "volatility (ATR) is not known yet"}
    sl_pct, tp_pct, e = k_sl * v, k_tp * v, S["c"][i]
    if sl_pct > C.MAX_SL_PCT or sl_pct < C.MIN_SL_PCT:
        return {"ok": False, "reason": "the stop would be %.2f%% away; only %.2f%% to %.2f%% fits a 10 USDT base" % (sl_pct, C.MIN_SL_PCT, C.MAX_SL_PCT)}
    sgn = 1.0 if side == "LONG" else -1.0
    return {"ok": True, "side": side, "entry": e, "vol_pct": v, "sl_pct": sl_pct, "tp_pct": tp_pct, "hold": hold, "reward_risk": k_tp / k_sl,
            "sl": e * (1.0 - sgn * sl_pct / 100.0), "tp": e * (1.0 + sgn * tp_pct / 100.0)}


def barrier_label(S, i, plan, end=None):
    """What a signal at candle i did with its barriers. -> {why TP / SL / TIME, exit, held, gross_pct, net_pct, r} or None when no candle is left after i."""
    r = C.simulate_trade(S, i, plan["side"], plan["sl"], S["n"] if end is None else end, plan["tp_pct"], plan["hold"])
    if r is None:
        return None
    r["held"] = r["exit"] - i
    r["r"] = r["gross_pct"] / plan["sl_pct"]          # result in units of the risk taken (1R = the stop distance)
    return r


def plan_for_signal(S, i, k_tp=K_TP, k_sl=K_SL):
    """For a live card: the signal of candle i (EMA + TSI + Z + sideways guard) with its barrier lines. None when there is no allowed signal."""
    sig = B.raw_signal(S, i)
    if sig["side"] is None:
        return None
    if sig["regime"] != "TRENDING":
        return {"ok": False, "side": sig["side"], "reason": "market is sideways or not clear, signal blocked"}
    return dict(barriers(S, i, sig["side"], k_tp, k_sl), side=sig["side"], signal_why=sig["why"])


def evidence(S, lo, hi, k_tp=K_TP, k_sl=K_SL, capital=10.0):
    """Every allowed signal of candles [lo, hi) with triple-barrier exits, one trade at a time, never looking past hi.
    -> {trades, skipped, stats (same keys as the engine's stats_of), outcomes {TP, SL, TIME}, avg_held, avg_r}. Trades have the engine's keys, so stats_of works on them."""
    out, skip, outc = [], {"sideways": 0, "barrier_refused": 0}, {"TP": 0, "SL": 0, "TIME": 0}
    i = max(lo, B.warmup_end(S), ATR_LEN + 1, 1)
    while i < hi - 1:
        if not (S["long_x"][i] or S["short_x"][i]):
            i += 1
            continue
        sig = B.raw_signal(S, i)
        if sig["side"] is None:
            i += 1
            continue
        if sig["regime"] != "TRENDING":
            skip["sideways"] += 1
            i += 1
            continue
        plan = barriers(S, i, sig["side"], k_tp, k_sl)
        if not plan["ok"]:
            skip["barrier_refused"] += 1
            i += 1
            continue
        r = barrier_label(S, i, plan, hi)
        if r is None:
            break
        outc[r["why"]] += 1
        out.append({"i": i, "t": S["t"][i], "side": sig["side"], "entry": plan["entry"], "sl": plan["sl"], "tp": plan["tp"], "sl_pct": plan["sl_pct"], "exit_i": r["exit"],
                    "exit_t": S["t"][r["exit"]], "why": r["why"], "held": r["held"], "r": r["r"], "gross_pct": r["gross_pct"], "net_pct": r["net_pct"],
                    "net_usdt": capital * r["net_pct"] / 100.0, "win": r["net_pct"] > 0})
        i = r["exit"] + 1
    n = len(out)
    return {"trades": out, "skipped": skip, "stats": C.stats_of(out, capital), "outcomes": outc,
            "avg_held": (sum(t["held"] for t in out) / n) if n else None, "avg_r": (sum(t["r"] for t in out) / n) if n else None}


def compare_fixed(S, lo, hi, tp_fixed_pct=1.5, k_tp=K_TP, k_sl=K_SL, capital=10.0):
    """The SAME period with the old fixed exit (engine run_period: TP 1.5%, stop outside the SD band) and with the triple barrier. The two trade lists are different
    (other stops free other candles), so this is two honest results side by side, never a proof that one is better."""
    old = C.run_period(S, lo, hi, tp_fixed_pct, True, capital)
    new = evidence(S, lo, hi, k_tp, k_sl, capital)
    return {"fixed": {"stats": C.stats_of(old["trades"], capital), "skipped": old["skipped"]},
            "barrier": {"stats": new["stats"], "skipped": new["skipped"], "outcomes": new["outcomes"], "avg_held": new["avg_held"], "avg_r": new["avg_r"]}}
