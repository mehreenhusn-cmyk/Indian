"""chop_filter_lab.py - Part C2 (README_CHOP): the REPLAY. It replays the closed 5m candles already saved in v2_market.db (read only, NO download) and compares the CURRENT rule (take every EMA50 cross)
with the b3 filter at several score cut-offs, on 5m and on 15m (15m candles are built from the saved 5m candles, only complete 3-candle groups). Nothing is traded, nothing is sent, nothing in the repo is changed.
ENTRY is the only thing that differs. Every variant uses the SAME exits as chop_bot (stop = signal candle extreme, target = TP4 of the SD bands, a candle touching both counts as the stop, an opposite TAKE closes
the old trade as REVERSED, one trade per coin, cost = chop_filter.COST_PCT round trip), so the comparison is fair. Trades still open at the end of the data are dropped (not finished).
VARIANTS: current (every cross, FULL size) / filter 70-50 / filter 60-40 / filter 80-60 / filter 70-50 + bigger-timeframe block (5m only; 15m has no bigger timeframe in the saved data). The filter is asked ONCE per candle
with cut-offs 0 (hard blocks + score), then every variant applies its own cut-offs, its own soft brake and its own FULL / HALF size, exactly like chop_filter.decide. Late entries (scenario 5) are replayed too.
PERIOD: today (UTC day) / month (last 30 days) / all (everything saved; the store keeps 30 days of 5m). Candles before the period still warm the indicators; only signals inside the period are traded.
TRAIN / TEST: the whole days of the data are cut at 60%: the first 60% train, the last 40% test. Fewer than 5 days = no split, and a variant is judged only if it has 30 or more test trades.
RALLY CAPTURE: of the signals the current rule traded and that made RALLY_PCT or more net, how many the variant also took. LOSS AVOIDED: of the signals that lost, how many the variant skipped. Money = full size 10 USDT, what-if.
Nothing is applied: the replay only REPORTS. The owner decides about any cut-off (they are constants of chop_score.py).
Run (Termux, optional, read only):  python3 backend/chop_filter_lab.py [--data DIR] [--interval 5m|15m] [--period today|month|all]  -> prints the result and saves chop_b3_lab_<interval>_<period>.json in the data folder.
Also started by POST /api/v2/chop_lab (api/chop.py) as one background job. It can take minutes on a phone: it sleeps a little between coins so the backend stays responsive."""
import argparse
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_defs as D
import v2_scalp_ind as I
import chop_bot as B
import chop_filter as F
import chop_score as S

VERSION = "chop_filter_lab 1 (Part C2)"
RALLY_PCT = 1.0
MIN_TEST_TRADES, MIN_DAYS_SPLIT, TRAIN_FRAC, MAX_COINS = 30, 5, 0.6, 40
PERIODS, INTERVALS = ("today", "month", "all"), ("5m", "15m")
VARIANTS = (
    {"name": "current", "kind": "current"},
    {"name": "filter 70/50", "kind": "filter", "full": 70.0, "half": 50.0, "htf_block": False},
    {"name": "filter 60/40", "kind": "filter", "full": 60.0, "half": 40.0, "htf_block": False},
    {"name": "filter 80/60", "kind": "filter", "full": 80.0, "half": 60.0, "htf_block": False},
    {"name": "filter 70/50 + bigger timeframe block", "kind": "filter", "full": 70.0, "half": 50.0, "htf_block": True},
)
P0 = dict(F.P, full_cut=0.0, half_cut=0.0)
_job = {"running": False, "interval": None, "period": None, "done": 0, "total": 0, "started": None, "error": None}
_lock = threading.Lock()


def to_15m(cs):
    """5m candles -> 15m candles (only complete, consecutive groups of 3 that start on a 15m mark)."""
    by = {}
    for c in cs:
        by.setdefault(c[0] // 900 * 900, []).append(c)
    out = []
    for b in sorted(by):
        g = by[b]
        if len(g) == 3 and g[0][0] == b and g[1][0] - g[0][0] == 300 and g[2][0] - g[1][0] == 300:
            out.append((b, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[2][4], sum(x[5] for x in g)))
    return out


def _runs(cs, step):
    out, cur = [], []
    for c in cs:
        if cur and c[0] - cur[-1][0] != step:
            out.append(cur)
            cur = []
        cur.append(c)
    if cur:
        out.append(cur)
    return out


def _new_state():
    return {"open": None, "losses": 0, "trades": []}


def _finish(st, t, ts, px, reason):
    w = 1 if t["side"] == "BUY" else -1
    net = (px - t["entry"]) * w / t["entry"] * 100.0 - F.COST_PCT
    st["trades"].append({"key": t["key"], "ts": t["ts"], "net": round(net, 4), "usdt": round(net / 100.0 * t["invest"], 4), "why": reason})
    st["losses"] = st["losses"] + 1 if net < 0 else 0
    st["open"] = None


def _manage(st, cd, step):
    t = st["open"]
    if t is None or cd[0] + step <= t["entry_ts"]:
        return
    w = 1 if t["side"] == "BUY" else -1
    if (cd[3] <= t["stop"]) if w > 0 else (cd[2] >= t["stop"]):
        _finish(st, t, cd[0] + step, t["stop"], "STOP")
    elif (cd[2] >= t["tp4"]) if w > 0 else (cd[3] <= t["tp4"]):
        _finish(st, t, cd[0] + step, t["tp4"], "TARGET")


def _enter(st, run, ind, i, side, invest, key, step):
    cd = run[i]
    t = st["open"]
    if t is not None and t["side"] == side:
        return
    w = 1 if side == "BUY" else -1
    entry, stop, tps = cd[4], (cd[3] if side == "BUY" else cd[2]), B.tp_levels(ind, i, side)
    if tps is None or (entry - stop) * w <= 0 or (tps[3] - entry) * w <= 0:
        return
    if t is not None:
        _finish(st, t, cd[0] + step, entry, "REVERSED")
    st["open"] = {"side": side, "entry": entry, "stop": stop, "tp4": tps[3], "invest": invest, "key": key, "ts": cd[0], "entry_ts": cd[0] + step}


def _consume(var, st, run, ind, i, res, key, step, late):
    """One variant looks at the shared decision of candle i and trades or not."""
    if var["kind"] == "current":
        if not late:
            _enter(st, run, ind, i, res["side"], B.FULL_USDT, key, step)
        return
    if res["action"] != "TAKE" or (var["htf_block"] and res["states"]["htf_agree"] is False):
        return
    size = S.size_for(res["score"], st["losses"], var["full"], var["half"])[0]
    if size == "NONE":
        return
    if size == "FULL" and res["size"] != "FULL":
        size = "HALF"
    _enter(st, run, ind, i, res["side"], B.FULL_USDT if size == "FULL" else B.FULL_USDT / 2.0, key, step)


def _btc_move(m, ts, step):
    a, b = m.get(ts), m.get(ts - 3 * step)
    return None if not a or not b else (a - b) / b * 100.0


def _replay_run(sym, run, step, variants, start, btcmap, use_htf, weights):
    ind = I.compute(run)
    states = [_new_state() for _ in variants]
    late = None
    for i in range(1, len(run)):
        cd = run[i]
        for st in states:
            _manage(st, cd, step)
        if cd[0] < start:
            continue
        htf = None
        btc = _btc_move(btcmap, cd[0], step)
        if late is not None and i - late["i"] > F.P["late_bars"]:
            late = None
        if late is not None and i > late["i"]:
            htf = B.htf_side_at(run, i) if use_htf else None
            r = F.decide(run, ind, i, htf_side=htf, btc_move_pct=btc, weights=weights, p=P0, late_from={"i": late["i"], "side": late["side"]})
            if r["action"] == "TAKE":
                for v, st in zip(variants, states):
                    _consume(v, st, run, ind, i, r, (sym, late["ts"]), step, True)
                late = None
        if I.ema_cross(ind, i) is None:
            continue
        r = F.decide(run, ind, i, htf_side=B.htf_side_at(run, i) if use_htf else None, btc_move_pct=btc, weights=weights, p=P0)
        if r["action"] == "NONE" or r.get("side") is None:
            continue
        for v, st in zip(variants, states):
            _consume(v, st, run, ind, i, r, (sym, cd[0]), step, False)
        if r.get("late_candidate"):
            late = {"i": i, "side": r["side"], "ts": cd[0]}
    return [st["trades"] for st in states]


def _stats(trs):
    n = len(trs)
    if not n:
        return {"trades": 0}
    return {"trades": n, "win_pct": round(100.0 * sum(1 for t in trs if t["net"] > 0) / n, 1), "avg_net_pct": round(sum(t["net"] for t in trs) / n, 4), "profit_usdt": round(sum(t["usdt"] for t in trs), 2)}


def _summarise(variants, all_trades, interval, period, coins):
    base = {t["key"]: t for t in all_trades[0]}
    days = sorted({t["ts"] // 86400 for t in all_trades[0]})
    split = days[int(len(days) * TRAIN_FRAC)] * 86400 if len(days) >= MIN_DAYS_SPLIT else None
    win_keys = [k for k, t in base.items() if t["net"] >= RALLY_PCT]
    lose_keys = [k for k, t in base.items() if t["net"] < 0]
    out = []
    for v, trs in zip(variants, all_trades):
        taken = {t["key"] for t in trs}
        tr = [t for t in trs if split is not None and t["ts"] < split]
        te = [t for t in trs if split is not None and t["ts"] >= split]
        out.append({"name": v["name"], "cuts": None if v["kind"] == "current" else [v["full"], v["half"]], "htf_block": bool(v.get("htf_block")),
                    "all": _stats(trs), "train": _stats(tr) if split is not None else None, "test": _stats(te) if split is not None else None,
                    "rally_capture_pct": round(100.0 * sum(1 for k in win_keys if k in taken) / len(win_keys), 1) if win_keys else None,
                    "loss_avoided_pct": round(100.0 * sum(1 for k in lose_keys if k not in taken) / len(lose_keys), 1) if lose_keys else None,
                    "rally_missed_usdt": round(sum(base[k]["usdt"] for k in win_keys if k not in taken), 2),
                    "loss_avoided_usdt": round(-sum(base[k]["usdt"] for k in lose_keys if k not in taken), 2)})
    cur = out[0]
    best = None
    for o in out[1:]:
        if split is None:
            o["verdict"] = "too few days for a train / test check (need %d)" % MIN_DAYS_SPLIT
        elif o["test"]["trades"] < MIN_TEST_TRADES:
            o["verdict"] = "too few test trades (%d, need %d)" % (o["test"]["trades"], MIN_TEST_TRADES)
        else:
            tr_ok = o["train"]["trades"] > 0 and o["train"].get("avg_net_pct", -9) > cur["train"].get("avg_net_pct", 9)
            te_ok = o["test"].get("avg_net_pct", -9) > cur["test"].get("avg_net_pct", 9)
            o["verdict"] = "BETTER than current on train and test" if tr_ok and te_ok else "better on test only" if te_ok else "WORSE than current on test"
            if tr_ok and te_ok and (best is None or o["test"]["avg_net_pct"] > best["test"]["avg_net_pct"]):
                best = o
    return {"version": VERSION, "interval": interval, "period": period, "coins": coins, "days": len(days), "split_ts": split, "rally_pct": RALLY_PCT, "variants": out,
            "best": best["name"] if best else None, "applied": False,
            "note": "Nothing is applied. Money = full size 10 USDT what-if, after cost. 'best' needs a win on BOTH train and test with 30+ test trades."}


def period_start(period, now):
    return now // 86400 * 86400 if period == "today" else now - 30 * 86400 if period == "month" else 0


def run(data_dir, interval="5m", period="month", now=None, progress=None):
    """The replay. -> result dict (see _summarise) or {"error": text}. Read only on v2_market.db."""
    if interval not in INTERVALS or period not in PERIODS:
        return {"error": "interval must be 5m or 15m, period today, month or all"}
    now = int(now if now is not None else time.time())
    sdb = B.open_store_ro(data_dir)
    if sdb is None:
        return {"error": "the market store is not created yet"}
    step = 300 if interval == "5m" else 900
    variants = [v for v in VARIANTS if not (interval == "15m" and v.get("htf_block"))]
    try:
        def load(sym):
            cs = D.clean_candles(D.candles_from_store(sdb, sym, "5m", 0, now), "5m")[0]
            return to_15m(cs) if interval == "15m" else cs
        btcmap = {c[0]: c[4] for c in load("BTCUSDT")}
        syms = [r[0] for r in sdb.execute("SELECT symbol, COUNT(*) n FROM candles WHERE interval='5m' GROUP BY symbol ORDER BY n DESC LIMIT ?", (MAX_COINS + 1,)).fetchall() if r[0] not in B.SKIP_COINS][:MAX_COINS]
        weights, start = S.load_weights(B.weights_path(data_dir)), period_start(period, now)
        all_trades, used = [[] for _ in variants], 0
        for k, sym in enumerate(syms):
            for rn in [x for x in _runs(load(sym), step) if len(x) >= I.need_candles() + 5]:
                for acc, trs in zip(all_trades, _replay_run(sym, rn, step, variants, start, btcmap, interval == "5m", weights)):
                    acc.extend(trs)
                used += 1
            if progress:
                progress(k + 1, len(syms))
            time.sleep(0.05)
        return _summarise(variants, all_trades, interval, period, used)
    finally:
        sdb.close()


def result_path(data_dir, interval, period):
    return os.path.join(os.path.realpath(data_dir), "chop_b3_lab_%s_%s.json" % (interval, period))


def save_result(data_dir, res):
    p = result_path(data_dir, res["interval"], res["period"])
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(res, f)
    os.replace(p + ".tmp", p)


def load_result(data_dir, interval, period):
    try:
        with open(result_path(data_dir, interval, period), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def job_status():
    with _lock:
        return dict(_job)


def _work(data_dir, interval, period):
    def prog(done, total):
        with _lock:
            _job["done"], _job["total"] = done, total
    try:
        res = run(data_dir, interval, period, progress=prog)
        if "error" in res:
            raise RuntimeError(res["error"])
        save_result(data_dir, res)
    except Exception as e:
        with _lock:
            _job["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    finally:
        with _lock:
            _job["running"] = False


def start_job(data_dir, interval, period):
    """-> (started, text). One replay at a time."""
    if interval not in INTERVALS or period not in PERIODS:
        return False, "interval must be 5m or 15m, period today, month or all"
    with _lock:
        if _job["running"]:
            return False, "a replay is already running"
        _job.update({"running": True, "interval": interval, "period": period, "done": 0, "total": 0, "started": int(time.time()), "error": None})
    threading.Thread(target=_work, args=(data_dir, interval, period), name="owl-chop-lab", daemon=True).start()
    return True, "started"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--period", default="month")
    a = ap.parse_args(argv)
    res = run(a.data, a.interval, a.period, progress=lambda d, t: print("coin %d of %d" % (d, t), file=sys.stderr))
    if "error" not in res:
        save_result(a.data, res)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
