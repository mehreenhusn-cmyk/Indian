"""v2_replay.py - Part 50: SCALP LAB 2 of 8 (backend). The replay engine every Scalp Lab category will use. HYPOTHETICAL: it reads closed candles that are already saved and works out what a rule WOULD have done.
It places nothing, writes nothing, imports no trading code and no network code (import_guard() scans the Scalp Lab files for that; run it from a test or by hand).
RULES FIXED HERE (README4 9.7), starting values are marked NV = not validated, change them in the constants:
 1. EXECUTION = candle close. A signal is known only when its candle has CLOSED; the entry price is that candle's close (the first price anybody could have used). Nothing looks ahead.
 2. Only candles of ONE gap-free run are used (v2_setup_finder.runs); a gap is never bridged. If the window runs into a gap or the end of saved data the result is UNAVAILABLE, and if the window is simply not over yet it is PENDING. Neither is counted as 0.
 3. STOP AND TARGET IN THE SAME CANDLE: the STOP is taken (the unfavourable fill is assumed, never the favourable one) and the record says so (same_candle = True).
 4. TIME exit: after max_hold candles without a touch, exit at the close of the last candle.
 5. COSTS (NV): fee FEE_PCT and slippage SLIP_PCT per side, taken from the price move; net_pct = gross_pct - 2 x (fee + slippage). Raw price %, NOT leveraged ROI. Real fills may differ.
 6. NO TUNING ON THE SAME SAMPLE: holdout_cut() puts the NEWER part of the time range (HOLDOUT_FRAC) into HOLDOUT; rules are chosen on TRAIN and judged on HOLDOUT. Time order only, never random.
 7. INDICATORS: only the owner's two indicators may be named (ALLOWED_INDICATORS: EMA50 + SD bands on the main chart; TSI, Z-score, Z-SMA in the pane). check_indicators() refuses anything else.
 8. Fewer than MIN_N finished records = "too few to say anything". No win rate, no prediction, no order.
Run (Termux, optional):  python3 backend/v2_replay.py   -> import guard result."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_replay 1 (Part 50)"
FEE_PCT = 0.05                   # per side, in % of price (NV)
SLIP_PCT = 0.02                  # per side, in % of price (NV)
HOLDOUT_FRAC = 0.3               # the newest 30% of the time range is HOLDOUT (NV)
MIN_N = 30                       # below this a summary carries "too few to say anything"
ALLOWED_INDICATORS = ("ema50", "sd_band", "tsi", "z", "z_sma")
SIDES = ("LONG", "SHORT")
FINISHED_STATUSES = ("TARGET", "STOP", "TIME")
FILES = ("v2_replay.py", "v2_scalp_store.py", "v2_scalp_ind.py", "v2_scalp_ema.py")
FORBIDDEN = ("binance" + "_trader", "execution" + "_router", "place_market" + "_order", "import " + "requests", "urllib." + "request", "import " + "socket", "api" + "_key", "api" + "_secret", "live_trading" + "_enabled")


def cost_pct():
    return 2.0 * (FEE_PCT + SLIP_PCT)


def check_indicators(names):
    bad = [n for n in names if n not in ALLOWED_INDICATORS]
    if bad:
        raise ValueError("indicator not allowed (only the owner's two indicators): " + ", ".join(bad))
    return True


def holdout_cut(times):
    """The time from which candles belong to HOLDOUT, or None when there are fewer than 2 distinct times. Older = TRAIN, newer = HOLDOUT."""
    ts = sorted(set(int(t) for t in times))
    if len(ts) < 2:
        return None
    return ts[min(len(ts) - 1, max(1, int(len(ts) * (1.0 - HOLDOUT_FRAC))))]


def sample_of(ts, cut):
    return "HOLDOUT" if cut is not None and int(ts) >= cut else "TRAIN"


def simulate(run, i, side, stop, target, max_hold, step, now):
    """Replay of ONE hypothetical trade. run = gap-free list of candles (open_ts, o, h, l, c, v), i = the signal candle (closed). Entry = close of run[i].
    stop and target are PRICES chosen by the category from information known at candle i. -> dict with status TARGET / STOP / TIME / PENDING / UNAVAILABLE.
    Finished results carry entry, exit_price, hold_candles, gross_pct, net_pct, same_candle."""
    if side not in SIDES:
        raise ValueError("side must be LONG or SHORT")
    entry = run[i][4]
    if not (entry > 0 and stop > 0 and target > 0):
        raise ValueError("entry, stop and target must be positive prices")
    if (side == "LONG" and not stop < entry < target) or (side == "SHORT" and not target < entry < stop):
        raise ValueError("stop and target must sit on the correct sides of the entry")
    last = min(i + max_hold, len(run) - 1)
    for j in range(i + 1, last + 1):
        hi, lo = run[j][2], run[j][3]
        hit_stop = lo <= stop if side == "LONG" else hi >= stop
        hit_tgt = hi >= target if side == "LONG" else lo <= target
        if hit_stop:
            return _done("STOP", side, entry, stop, j - i, same=hit_tgt)
        if hit_tgt:
            return _done("TARGET", side, entry, target, j - i, same=False)
    if i + max_hold < len(run):
        return _done("TIME", side, entry, run[i + max_hold][4], max_hold, same=False)
    return {"status": "PENDING" if run[i][0] + step * (max_hold + 1) > now else "UNAVAILABLE"}


def _done(status, side, entry, px, held, same):
    g = (px - entry) / entry * 100.0 * (1 if side == "LONG" else -1)
    return {"status": status, "entry": entry, "exit_price": px, "hold_candles": held, "gross_pct": g, "net_pct": g - cost_pct(), "same_candle": same}


def _med(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if n == 0 else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0)


def summarize(rows):
    """rows = (status, net_pct, ...) of FINISHED records of ONE category. -> counts per exit, median net %, sum net %, with the too-few note. Never a win rate."""
    n = len(rows)
    out = {"n": n, "TARGET": 0, "STOP": 0, "TIME": 0}
    for r in rows:
        out[r[0]] = out.get(r[0], 0) + 1
    out["median_net_pct"] = None if n < MIN_N else _med([r[1] for r in rows])
    out["sum_net_pct"] = None if n < MIN_N else sum(r[1] for r in rows)
    if n < MIN_N:
        out["note"] = "too few to say anything (under %d finished records)" % MIN_N
    return out


def import_guard(folder=None):
    """Scans the Scalp Lab files for trading / network words. -> list of (file, word) hits; an empty list = clean."""
    folder = folder or os.path.dirname(os.path.abspath(__file__))
    hits = []
    for f in FILES:
        try:
            with open(os.path.join(folder, f), "r", encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            hits.append((f, "FILE NOT FOUND"))
            continue
        hits.extend((f, w) for w in FORBIDDEN if w in src)
    return hits


if __name__ == "__main__":
    h = import_guard()
    print(VERSION, "import guard:", "CLEAN" if not h else h)
    sys.exit(1 if h else 0)
