#!/usr/bin/env python3
"""
variant_lab.py - "Strategy Lab": ONE table that answers "what if the bot did X instead?". Read-only, own thread.

Idea in one line: take the bot's REAL signals (EMA50 cross, replayed on Binance candles with filter_lab.py), then re-run the SAME
signals under many scenarios and compare each one with the bot today:

  * Exit / stop-loss : wider SL, SL to entry + fee after TP1, exit at TP2, hold till the opposite signal (no TP4 exit)
  * Indicators       : TSI with the trade, Z with the trade, both agree, low chop (a scenario SKIPS some signals)
  * Bollinger        : squeeze / side / late / expanding (skips)
  * Bands            : EMA200 bands instead of SMA200 SD bands (TP levels move)
  * Combos           : a few mixes of the above

For each scenario the table shows: trades taken (vs the bot), net, win %, difference to the bot, "saved" (trades that got better),
"missed" (trades that got worse) and a verdict. A scenario is BETTER only when it beat the bot in BOTH the older 60% and the newer
40% of the signals. Nothing here changes the bot. It is a replay (no slippage), so it is evidence, not a promise.

  cd backend && python3 variant_lab.py 15m 14        # one timeframe, last 14 days
"""
import json
import math
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filter_lab as FL

BIG = 1e18
TFS = ("3m", "5m", "15m")
GROUP_ORDER = ["Exit and stop-loss", "Indicators (skip signals)", "Bollinger (skip signals)", "Bands", "Mixes"]


# ---------------------------------------------------------------- extra variants per signal (added while filter_lab collects)
def _ema200(S):
    e = S.get("_e200")
    if e is None:
        from recovered_bot import ai_ind_features as F
        e = S["_e200"] = F.ema(S["c"], 200, seed="sma")
    return e


def enrich(r, S, i, lev, fee):
    """r['x'] = {variant: [net ROI pts after fee, why, bars]} for exit / band variants. Same signal, same entry."""
    if not r.get("alt"):
        return
    is_long = r["a"] == "BUY"
    entry, base_sl, tps = r["e"], r["sl"], r["tp"]
    far = BIG if is_long else -BIG
    x = {}

    def put(key, sl, tp1, tp4):
        ret, why, bars = FL.sim_trade(S, i, is_long, entry, sl, tp1, tp4, 0.0)
        if why != "OPEN":
            x[key] = [round(ret * lev - fee, 3), why, bars]

    put("tp2", base_sl, tps[0], tps[1])                                   # leave at TP2
    put("run", base_sl, tps[0], far)                                      # no TP4 exit: SL / opposite cross only
    put("run_prev1", FL.sl_levels(S, i, is_long, entry, base_sl)["prev1"], tps[0], far)
    m, sd = _ema200(S)[i], S["std"][i]
    if m is not None and sd:                                              # SD ladder built around EMA200 instead of SMA200
        lv = [m + k * sd for k in (-3, -2, -1, 0, 1, 2, 3)]
        up = sorted(v for v in lv if v > entry)[:4] if is_long else sorted((v for v in lv if v < entry), reverse=True)[:4]
        if len(up) == 4:
            put("ema", base_sl, up[0], up[3])
    r["x"] = x


# ---------------------------------------------------------------- scenarios: fn(row) -> net of the scenario, or None = signal skipped
def _b(r):
    return r["alt"]["base|be0"][0]


def _alt(key):
    return lambda r: r["alt"][key][0] if key in r["alt"] else _b(r)


def _x(key):
    return lambda r: r["x"][key][0] if key in (r.get("x") or {}) else _b(r)


def _gate(fn):
    return lambda r: _b(r) if fn(r) else None


def _both(r):
    return FL._g_tsi_line(r) and FL._g_z_moving(r)


SCENARIOS = [
    ("Exit and stop-loss", "sl_prev1", "Wider SL: previous candle", _alt("prev1|be0")),
    ("Exit and stop-loss", "sl_prev3", "Wider SL: last 3 candles", _alt("prev3|be0")),
    ("Exit and stop-loss", "sl_swing", "Wider SL: last 10 candles", _alt("swing10|be0")),
    ("Exit and stop-loss", "sl_atr", "Wider SL: 1.5 x ATR", _alt("atr15|be0")),
    ("Exit and stop-loss", "be_fee", "After TP1: SL to entry + fee", _alt("base|bef")),
    ("Exit and stop-loss", "tp2", "Exit at TP2 (not TP4)", _x("tp2")),
    ("Exit and stop-loss", "run", "Hold till opposite signal (no TP4 exit)", _x("run")),
    ("Exit and stop-loss", "run_prev1", "Hold till opposite + wider SL (prev candle)", _x("run_prev1")),
    ("Indicators (skip signals)", "tsi", "TSI with the trade", _gate(FL._g_tsi_line)),
    ("Indicators (skip signals)", "zmove", "Z moving with the trade", _gate(FL._g_z_moving)),
    ("Indicators (skip signals)", "zrule", "No long below mean / no short above", _gate(FL._g_z_user)),
    ("Indicators (skip signals)", "both", "TSI and Z both agree", _gate(_both)),
    ("Indicators (skip signals)", "chop", "Low chop (max 2 EMA50 crosses)", _gate(FL._g_chop)),
    ("Bollinger (skip signals)", "bb_sq", "Skip squeeze (sideways)", _gate(FL._g_bb_squeeze)),
    ("Bollinger (skip signals)", "bb_side", "Long above / short below mid band", _gate(FL._g_bb_side)),
    ("Bollinger (skip signals)", "bb_late", "Skip late (outside band)", _gate(FL._g_bb_not_late)),
    ("Bollinger (skip signals)", "bb_exp", "Only when bands expanding", _gate(FL._g_bb_expanding)),
    ("Bands", "ema", "EMA200 bands instead of SMA200 SD bands", _x("ema")),
    ("Mixes", "mix1", "Wider SL (prev) + skip squeeze",
     lambda r: _alt("prev1|be0")(r) if FL._g_bb_squeeze(r) else None),
    ("Mixes", "mix2", "TSI and Z agree + wider SL (prev)",
     lambda r: _alt("prev1|be0")(r) if _both(r) else None),
    ("Mixes", "mix3", "Hold till opposite + TSI with trade",
     lambda r: _x("run")(r) if FL._g_tsi_line(r) else None),
    ("Mixes", "mix4", "Hold till opposite + wider SL + skip squeeze",
     lambda r: _x("run_prev1")(r) if FL._g_bb_squeeze(r) else None),
]


# ---------------------------------------------------------------- the table
def _line(vals):
    n = len(vals)
    if not n:
        return {"n": 0, "net": 0.0, "avg": 0.0, "win": 0.0}
    return {"n": n, "net": round(sum(vals), 1), "avg": round(sum(vals) / n, 2),
            "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1)}


def analyse(rows):
    """rows: filter_lab replay rows (after enrich). -> {"n", "bot", "rows": [...], "answer": [...]}"""
    rs = [r for r in rows if r.get("alt")]
    if len(rs) < 40:
        return {"n": len(rs), "ok": False, "answer": [f"Only {len(rs)} usable signals - too few to compare. Run again later or use more days."]}
    old, new = FL.split_rows(rs)
    bot = _line([_b(r) for r in rs])
    out = {"ok": True, "n": len(rs), "n_old": len(old), "n_new": len(new), "bot": bot, "rows": []}
    for group, key, title, fn in SCENARIOS:
        vo = [fn(r) for r in old]
        vn = [fn(r) for r in new]
        do = [(0.0 if v is None else v) - _b(r) for v, r in zip(vo, old)]
        dn = [(0.0 if v is None else v) - _b(r) for v, r in zip(vn, new)]
        taken = [v for v in vo + vn if v is not None]
        d = do + dn
        zo, zn = FL._paired_z(do), FL._paired_z(dn)
        ch_o, ch_n = sum(1 for x in do if abs(x) > 1e-9), sum(1 for x in dn if abs(x) > 1e-9)
        if len(old) < FL.MIN_PAIR_OLD or len(new) < FL.MIN_PAIR_NEW or ch_o < FL.MIN_SKIP_OLD or ch_n < FL.MIN_SKIP_NEW:
            verdict = "not_enough"
        elif zo >= FL.Z_OLD and zn >= FL.Z_NEW:
            verdict = "better"
        elif zo <= -FL.Z_OLD and zn <= -FL.Z_NEW:
            verdict = "worse"
        else:
            verdict = "unclear"
        ln = _line(taken)
        out["rows"].append({
            "group": group, "key": key, "title": title, "taken": ln["n"], "net": ln["net"], "avg": ln["avg"], "win": ln["win"],
            "vs_bot": round(sum(d), 1), "saved": round(sum(x for x in d if x > 0), 1), "missed": round(-sum(x for x in d if x < 0), 1),
            "d_old": round(sum(do) / len(do), 2) if do else 0.0, "d_new": round(sum(dn) / len(dn), 2) if dn else 0.0,
            "verdict": verdict})
    better = sorted((r for r in out["rows"] if r["verdict"] == "better"), key=lambda r: -r["vs_bot"])
    unclear_pos = sorted((r for r in out["rows"] if r["verdict"] == "unclear" and r["vs_bot"] > 0), key=lambda r: -r["vs_bot"])
    ans = [f"Bot today: {bot['n']} trades, net {bot['net']} ROI pts after fees, win {bot['win']}%."]
    if better:
        ans.append("Beat the bot in BOTH older and newer data: " + "; ".join(f"{r['title']} ({r['vs_bot']:+.0f})" for r in better[:3]) + ".")
        ans.append("Keep the best one on paper for a few days before using it. Many tests on the same data can still give a lucky winner.")
    else:
        ans.append("No scenario beat the bot in BOTH halves. So nothing is proven yet.")
        if unclear_pos:
            ans.append("Looked a little better but not proven: " + "; ".join(f"{r['title']} ({r['vs_bot']:+.0f})" for r in unclear_pos[:3]) + ".")
    out["answer"] = ans
    return out


# ---------------------------------------------------------------- text version (terminal / report)
def text_report(res, tf, days):
    L = [f"STRATEGY LAB - {tf} candles, last {days} days (net = ROI pts after fee; replay, no slippage)"]
    L += res.get("answer", [])
    if res.get("ok"):
        L.append("scenario | trades | net | win% | vs bot | saved | missed | verdict")
        for g in GROUP_ORDER:
            for r in res["rows"]:
                if r["group"] == g:
                    L.append(f"[{g}] {r['title']} | {r['taken']} | {r['net']} | {r['win']} | {r['vs_bot']:+} | {r['saved']} | {r['missed']} | {r['verdict']}")
    return "\n".join(L)


# ---------------------------------------------------------------- background job + saved result (survives a restart)
_STATE = {"running": False, "progress": "", "tfs": {}, "days": 14}
_LOCK = threading.Lock()


def _file():
    base = os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/owl_data")
    return os.path.join(base, "variant_lab.json")


def _load():
    try:
        with open(_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("tfs"), dict):
            _STATE["tfs"] = d["tfs"]
            _STATE["days"] = int(d.get("days", 14))
    except Exception:
        pass


def _save():
    try:
        os.makedirs(os.path.dirname(_file()), exist_ok=True)
        tmp = _file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"tfs": _STATE["tfs"], "days": _STATE["days"]}, f)
        os.replace(tmp, _file())
    except Exception:
        pass


def _worker(days, lev, fee):
    FL.EXTRA_ENRICH = enrich
    try:
        coins = FL.default_coins(lambda m: None)
        for tf in TFS:
            def log(m, tf=tf):
                _STATE["progress"] = f"{tf}: {m}"
            try:
                rows = FL.collect(tf, days, coins, lev, fee, log)
                res = analyse(rows)
            except Exception as e:
                res = {"ok": False, "n": 0, "answer": [f"{tf} failed: {type(e).__name__}: {e}"]}
            res["t"] = time.time()
            res["days"] = days
            with _LOCK:
                _STATE["tfs"][tf] = res
            _save()
    except Exception as e:
        _STATE["progress"] = f"failed: {type(e).__name__}: {e}"
    finally:
        FL.EXTRA_ENRICH = None
        _STATE["running"] = False


def start(days=14, lev=10.0, fee=1.0):
    """starts 3m, 5m, 15m one after the other in ONE thread. Returns False if already running."""
    with _LOCK:
        if _STATE["running"]:
            return False
        _STATE["running"] = True
        _STATE["days"] = int(days)
        _STATE["progress"] = "starting..."
    threading.Thread(target=_worker, args=(int(days), float(lev), float(fee)), daemon=True, name="variant_lab").start()
    return True


def status():
    if not _STATE["tfs"] and not _STATE["running"]:
        _load()
    out = {"running": _STATE["running"], "progress": _STATE["progress"], "days": _STATE["days"], "tfs": {}}
    for tf in TFS:
        r = _STATE["tfs"].get(tf)
        if r is None:
            out["tfs"][tf] = {"state": "not run"}
        else:
            out["tfs"][tf] = dict(r, state="done", age_min=int((time.time() - r.get("t", time.time())) / 60))
    return out


def main(argv):
    tf = argv[1] if len(argv) > 1 else "15m"
    days = int(argv[2]) if len(argv) > 2 else 14
    if tf not in FL.TF_MS:
        print("timeframe must be 3m, 5m or 15m")
        return 1
    FL.EXTRA_ENRICH = enrich
    rows = FL.collect(tf, days, FL.default_coins(), 10.0, 1.0)
    print("\n" + text_report(analyse(rows), tf, days))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
