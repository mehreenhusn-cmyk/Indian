"""v2_bt_chart.py - Part 86a: BRAIN TRADER chart reading + TODAY page data (backend, read-only). It reads the CURRENT chart of a coin the way the owner reads it by eye:
price vs EMA50 and SD zone, TSI vs its ZERO line and vs its SIGNAL line, the histogram (RED / GREEN, growing / shrinking = the red storm), Z vs its ZERO line and vs Z-SMA, and where two of them CLASH
(price going up while TSI falls, TSI above zero but under its signal, ...). No new indicator: every number comes from v2_scalp_ind via v2_bt_state (Part 84b). Words only, never an order or advice.
extra(ctx, i) = the extra chart tags (saved in every Brain decision next to the Part 84b tags, so Part 91 can later group results by them). view() = the plain sentences for ONE coin now.
today() = the Today page: the daily report lines + the newest answer of the Brain for every coin it follows. Honest: a tag without enough candles is None and view() says WHY (v2_bt_why), never a guess.
NV = not validated: the limits (3 candles for direction, 0.3 SD = flat price) are starting values. Reads files read-only. No network, no write, no trading import.
Run (Termux, optional):  python3 backend/v2_bt_chart.py [--symbol BTCUSDT] [--interval 5m]  -> the plain sentences of that coin."""
import argparse
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_report as BR
import v2_bt_rules as R
import v2_bt_sim as M
import v2_bt_state as ST
import v2_bt_store as B
import v2_bt_why as W
import v2_scalp_ind as IND

VERSION = "v2_bt_chart 1 (Part 86a)"
DIR_BARS, FLAT_SD = 3, 0.3
EMPTY = {"price_dir": None, "tsi_vs_zero": None, "tsi_vs_signal": None, "tsi_dir": None, "hist_color": None, "storm": None, "z_vs_zero": None, "z_dir": None, "clash": []}


def _dir(a, b):
    return None if a is None or b is None else "RISING" if a > b else "FALLING" if a < b else "FLAT"


def extra(ctx, i):
    """The extra chart tags of candle i (candles 0..i only). All None when a number is missing."""
    ind, k = ctx["ind"], DIR_BARS
    t, sg, h, z, zs = ind["tsi"][i], ind["tsi_signal"][i], ind["hist"][i], ind["z"][i], ind["z_sma"][i]
    s = ind["sd_std"][i]
    if i < 12 or None in (t, sg, h, z) or not s or ind["tsi"][i - k] is None or ind["z"][i - k] is None or ind["hist"][i - k] is None:
        return dict(EMPTY, clash=[])
    mv = (ind["close"][i] - ind["close"][i - 12]) / s
    out = {"price_dir": "FLAT" if abs(mv) < FLAT_SD else "UP" if mv > 0 else "DOWN", "tsi_vs_zero": "ABOVE_ZERO" if t > 0 else "BELOW_ZERO", "tsi_vs_signal": "ABOVE" if t > sg else "BELOW",
           "tsi_dir": _dir(t, ind["tsi"][i - k]), "hist_color": "GREEN" if h > 0 else "RED", "z_vs_zero": "ABOVE_ZERO" if z > 0 else "BELOW_ZERO", "z_dir": _dir(z, ind["z"][i - k])}
    grow = abs(h) > abs(ind["hist"][i - k])
    out["storm"] = ("RED_BUILDING" if grow else "RED_FADING") if h < 0 else ("GREEN_BUILDING" if grow else "GREEN_FADING")
    c = []
    if out["price_dir"] == "UP" and out["tsi_dir"] == "FALLING":
        c.append("PRICE_UP_TSI_FALLING")
    if out["price_dir"] == "DOWN" and out["tsi_dir"] == "RISING":
        c.append("PRICE_DOWN_TSI_RISING")
    if out["tsi_vs_zero"] == "ABOVE_ZERO" and out["tsi_vs_signal"] == "BELOW":
        c.append("TSI_ABOVE_ZERO_BUT_UNDER_SIGNAL")
    if out["tsi_vs_zero"] == "BELOW_ZERO" and out["tsi_vs_signal"] == "ABOVE":
        c.append("TSI_BELOW_ZERO_BUT_OVER_SIGNAL")
    if zs is not None and ((z > 0 and z < zs) or (z < 0 and z > zs)):
        c.append("Z_ON_ONE_SIDE_OF_ZERO_OTHER_SIDE_OF_Z_SMA")
    out["clash"] = c
    return out


CLASH_TEXT = {"PRICE_UP_TSI_FALLING": "Dhyan: price upar ja raha hai par TSI gir raha hai (upar ki chaal mein jaan kam).",
              "PRICE_DOWN_TSI_RISING": "Dhyan: price neeche ja raha hai par TSI chadh raha hai (neeche ki chaal mein jaan kam).",
              "TSI_ABOVE_ZERO_BUT_UNDER_SIGNAL": "Dhyan: TSI zero ke upar hai par apni signal line ke neeche (taakat thandi pad rahi hai).",
              "TSI_BELOW_ZERO_BUT_OVER_SIGNAL": "Dhyan: TSI zero ke neeche hai par signal line ke upar (neeche ka dabaav kam ho raha hai).",
              "Z_ON_ONE_SIDE_OF_ZERO_OTHER_SIDE_OF_Z_SMA": "Dhyan: Z aur Z-SMA zero ke alag taraf hain."}
STORM_TEXT = {"RED_BUILDING": "Histogram RED aur badh raha hai (bechne ka dabaav ban raha hai).", "RED_FADING": "Histogram RED hai par chhota ho raha hai.",
              "GREEN_BUILDING": "Histogram GREEN aur badh raha hai (kharidne ka dabaav ban raha hai).", "GREEN_FADING": "Histogram GREEN hai par chhota ho raha hai."}


def lines_for(t, x):
    """Plain sentences for one candle: t = Part 84b tags, x = extra()."""
    ud = {"UP": "upar gaya", "DOWN": "neeche gaya", "FLAT": "lagbhag flat raha"}
    o = ["Price EMA50 ke %s hai, SD zone %s, pichhle 12 candle mein %s." % ("upar" if t.get("price_vs_ema") == "ABOVE" else "neeche", t.get("sd_zone"), ud.get(x["price_dir"], "?")),
         "TSI zero ke %s, signal line ke %s, %s." % ("upar" if x["tsi_vs_zero"] == "ABOVE_ZERO" else "neeche", "upar" if x["tsi_vs_signal"] == "ABOVE" else "neeche", "chadh raha hai" if x["tsi_dir"] == "RISING" else "gir raha hai"),
         STORM_TEXT.get(x["storm"], ""),
         "Z zero ke %s, Z-SMA ke %s, zero ki %s." % ("upar" if x["z_vs_zero"] == "ABOVE_ZERO" else "neeche", "upar" if t.get("z_vs_sma") == "ABOVE" else "neeche", "taraf" if t.get("z_way") == "TOWARD_ZERO" else "door ja raha hai")]
    o += [CLASH_TEXT[c] for c in x["clash"]]
    return [s for s in o if s]


def view(data_dir, symbol, interval="5m", now=None):
    """The CURRENT chart of one coin in plain sentences + what the Brain would answer now (nothing is saved)."""
    now = int(time.time() if now is None else now)
    run, need = M.load_run(data_dir, symbol, interval), IND.need_candles()
    if len(run) < need:
        w = W.why(data_dir, symbol, interval, now)
        return {"ready": False, "symbol": symbol, "interval": interval, "candles": len(run), "need": need, "why": w, "lines": [w["text"]]}
    i = len(run) - 1
    ctx = ST.prepare(run)
    t = ST.tags(ctx, i)
    x = extra(ctx, i)
    d = R.decide(ctx, t, i)
    lines = lines_for(t, x)
    lines.append("Brain abhi: %s (%s). %s" % (d["decision"], t.get("market_state"), d["reason"]))
    return {"ready": True, "symbol": symbol, "interval": interval, "candle_time": W.ist(run[i][0] + 300 if interval == "5m" else run[i][0] + 180), "tags": t, "chart": x, "brain": {"decision": d["decision"], "side": d["side"], "reason": d["reason"], "wait_for": d["wait_for"]}, "lines": lines}


def today(data_dir, source="PAPER", now=None):
    """The Today page: the daily report (plain lines, trades, waits, no-data reasons) + the newest answer per coin with its chart tags."""
    now = int(time.time() if now is None else now)
    rep = BR.build(data_dir, source, None, now)
    coins = []
    con = B.open_ro(data_dir)
    if con is not None:
        try:
            for sym, iv, ts, dec, side, st, why, snap in con.execute("SELECT d.symbol, d.interval, d.close_ts, d.decision, d.side, d.state, d.reason, d.snapshot FROM bt_decision d JOIN (SELECT symbol, MAX(close_ts) m FROM bt_decision WHERE source=? AND state<>'DATA_NOT_READY' GROUP BY symbol) n ON n.symbol=d.symbol AND n.m=d.close_ts WHERE d.source=? GROUP BY d.symbol ORDER BY d.close_ts DESC LIMIT 30", (source, source)):
                tg = (json.loads(snap or "{}").get("tags") or {})
                coins.append({"symbol": sym, "interval": iv, "time": W.ist(ts), "decision": dec, "side": side, "state": st, "reason": why, "storm": tg.get("storm"), "tsi_vs_zero": tg.get("tsi_vs_zero"), "clash": tg.get("clash") or []})
        except sqlite3.Error:
            coins = []
        finally:
            con.close()
    rep["coins"] = coins
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="5m", choices=("3m", "5m"))
    a = ap.parse_args(argv)
    print("\n".join(view(a.data, a.symbol, a.interval)["lines"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
