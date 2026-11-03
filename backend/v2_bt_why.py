"""v2_bt_why.py - Part 85b: BRAIN TRADER 6 of 8 (backend, read-only). WHY is there no data? The owner asked (1 Nov): do not only say "no data", say the REASON, so he can see what went wrong.
why(data_dir, symbol, interval, now) looks at the saved candles, the gap list, the collector's health lines and the collector's heartbeat, and answers with ONE code and ONE plain sentence (Roman Hinglish) plus the facts behind it:
  NO_MARKET_STORE   the collector never saved anything yet            COLLECTOR_OFF   the candle switch is OFF (v2_candles --off)
  COLLECTOR_STOPPED the worker is not running (Termux closed / Android killed it)          NOT_FOLLOWED   the coin is not on the collector's list (top gainers / losers only, max 40)
  FETCH_FAILED      the last try to get this coin from Binance failed (the error name is shown)      TOO_FEW   the coin is followed but the candles are not enough yet (how many, how long to wait)
  GAP_CUT           enough candles in total, but a HOLE cut them; the hole time and its reason are shown      STALE   the newest candle is too old        OK   ready
A gap is never bridged: the Brain uses only the newest gap-free run and says DATA_NOT_READY before it. The hole's reason comes from the gap list (v2_candles writes it): Binance gave no candle, or the collector was off too long to refill.
Times are shown in IST (UTC + 5:30); a time over 60 minutes is shown as hours + minutes. Reads the market store read-only; no network, no write, no trading import.
Run (Termux, optional):  python3 backend/v2_bt_why.py --symbol XYZUSDT [--interval 5m]  -> the reason for that coin."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_candles as K
import v2_defs as D
import v2_scalp_ind as IND
import v2_setup_finder as SF
import v2_store as S

VERSION = "v2_bt_why 1 (Part 85b)"
IST = 19800
GAP_TEXT = {"exchange returned no candle": "Binance did not give a candle for that time",
            "too old to refill": "the collector was off for too long (more than 8 hours); candles that old are not refilled"}


def dur(sec):
    m = max(0, int(sec)) // 60
    return "%d min" % m if m <= 60 else "%d h %02d min" % (m // 60, m % 60)


def ist(ts):
    return time.strftime("%d %b %H:%M", time.gmtime(int(ts) + IST)) + " IST"


def _gap_text(reason):
    for k, v in GAP_TEXT.items():
        if reason and reason.startswith(k):
            return v
    return reason or "no reason was saved (the coin was briefly outside the collector list, or the collector was off)"


def _out(code, text, **facts):
    return dict({"ok": code == "OK", "code": code, "text": text}, **facts)


def _runner(data_dir):
    try:
        import v2_runner as RU
        return RU.status(data_dir)
    except Exception:
        return None


def _hole(con, symbol, interval, runs, step):
    """The newest hole = between the last two runs. -> ((end of the older run, start of the newer run, missing candles), reason text)."""
    a, b = runs[-1][0][0], runs[-2][-1][0]
    row = con.execute("SELECT reason FROM gap_log WHERE kind='candle' AND symbol=? AND interval=? AND to_ts>=? AND from_ts<=? ORDER BY from_ts DESC LIMIT 1", (symbol, interval, b, a)).fetchone()
    return (b, a, (a - b) // step - 1), _gap_text(row[0] if row else None)


def why(data_dir, symbol, interval="5m", now=None):
    now, need, step = int(time.time() if now is None else now), IND.need_candles(), D.STEP[interval]
    path = S.store_path(data_dir)
    if not os.path.isfile(path):
        return _out("NO_MARKET_STORE", "The collector has not saved anything yet (the market store does not exist).")
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    try:
        good, _bad = D.clean_candles(D.candles_from_store(con, symbol, interval, 0, 2 ** 31), interval)
        runs = SF.runs(good, interval)
        run = runs[-1] if runs else []
        newest = good[-1][0] if good else None
        facts = {"symbol": symbol, "candles_total": len(good), "candles_in_run": len(run), "need": need}
        if len(run) >= need and newest is not None and now - newest <= 4 * step:
            note = ""
            if len(good) > len(run):                                    # an older part sits behind a hole: say it, with the reason
                note = " The earlier %d candles are behind a hole (%s) and are not used." % (len(good) - len(run), _hole(con, symbol, interval, runs, step)[1])
            return _out("OK", "Data is fine: %d candles in one gap-free run.%s" % (len(run), note), **facts)
        rn, col = _runner(data_dir), None                           # a collector problem is the main reason only when it is the whole story; otherwise it is added at the end
        if not K.is_enabled(data_dir):
            col = ("COLLECTOR_OFF", "The candle collector switch is OFF (v2_candles --off), so no new data is coming.")
        elif rn is not None and not rn["running"]:
            col = ("COLLECTOR_STOPPED", "The collector worker is not running (Termux was closed or Android killed it). Heartbeat %s." %
                   ("never seen" if rn["beat_age_s"] is None else dur(rn["beat_age_s"]) + " old"))
        more_txt = (" On top of that: " + col[1]) if col else ""
        fail = None
        for ts, note in con.execute("SELECT ts, note FROM collector_health WHERE status='CANDLES_FETCH_FAILED' AND note LIKE ? ORDER BY ts DESC LIMIT 5", ("%" + symbol + " " + interval + ":%",)).fetchall():
            seg = next((x for x in note.split("; ") if x.startswith(symbol + " " + interval + ": ")), None)
            if seg and fail is None:
                fail = (ts, seg.split(": ", 1)[1])
        if fail and now - fail[0] <= 2 * 3600 and (newest is None or fail[0] >= newest):
            return _out("FETCH_FAILED", "Fetching candles of this coin from Binance failed (%s), %s ago. It will be tried again next time." % (fail[1][:60], dur(now - fail[0])), last_error_ts=fail[0], **facts)
        if not good and col:
            return _out(col[0], col[1], **facts)
        if not good:
            on = symbol in K.pick_symbols(con, now)
            return _out("NOT_FOLLOWED", "Not a single candle of this coin is saved. " + (
                "The coin is on the collector list, the first candles have just not arrived yet." if on else
                "The collector keeps candles only of the top gainers / losers (max 40 coins); this coin is not on that list now."), on_list=on, **facts)
        if len(good) >= need and len(run) < need:
            (b, a, hole), txt = _hole(con, symbol, interval, runs, step)
            return _out("GAP_CUT", "A hole appeared between the candles (%d candles missing, %s to %s), so the Brain went DATA_NOT_READY at that point. Reason: %s. The new run has %d candles so far, %d are needed." %
                        (hole, ist(b + step), ist(a - step), txt, len(run), need) + more_txt, gap_from=b + step, gap_to=a - step, gap_reason=txt, **facts)
        if len(run) < need:
            more = need - len(run)
            cut = (" The earlier %d candles are behind a hole (reason: %s) and are not used." % (len(good) - len(run), _hole(con, symbol, interval, runs, step)[1])) if len(good) > len(run) else ""
            return _out("TOO_FEW", "The coin is followed but candles are too few: %d found, %d needed. About %s more is needed.%s" % (len(run), need, dur(more * step), cut) + more_txt, wait_sec=more * step, **facts)
        if col:
            return _out(col[0], col[1] + " The newest candle is %s old." % dur(now - newest), newest_ts=newest, **facts)
        return _out("STALE", "The newest candle is %s old (%s). The collector has not filled new data yet." % (dur(now - newest), ist(newest)), newest_ts=newest, **facts)
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="5m", choices=("3m", "5m"))
    a = ap.parse_args(argv)
    print(json.dumps(why(a.data, a.symbol, a.interval), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
