"""chop_bot.py - Part C3 (README_CHOP): the LIVE PAPER bot b3 on the 5m timeframe. It reads the CLOSED 5m candles that v2_candles_ws.py already saves in v2_market.db (read only),
asks chop_filter.decide() on every EMA50 cross, and keeps its OWN paper trades and decision log in its OWN file chop_b3.db. The current bot (paper_trader, bot b1 / b2) is NOT touched and not read.
PAPER ONLY. No order code, no network, no exchange key. The switch is OFF until the owner turns it on (meta on = 1, route POST /api/v2/chop_switch). When OFF it only finishes its open trades and the verdicts.
RULES (same as the current bot where it is simple, README_CHOP section 3):
  entry      at the CLOSE of the signal candle; FULL = 10 USDT, HALF = 5 USDT, 1x; one open b3 trade per coin; an opposite TAKE closes the old one as REVERSED at that close; a SKIP never closes anything
  stop       the signal candle low (BUY) or high (SELL), fixed. target = TP4 of the same SD-band rule as recovered_bot/strategy.py (TP1-TP3 only shown as ticks). No break-even shift (simplified, C2 compares)
  exit check once per closed 5m candle, from the candle AFTER entry; a candle touching both stop and target counts as the STOP (pessimistic). Cost: chop_filter.COST_PCT round trip
  BTCUSDT is never traded here (only read for the BTC move bonus). Coins = the newest 40 with a fresh 5m candle. A coin starts from its newest closed candle (no history is replayed); at most 3 missed candles are caught up.
VERDICT TRACKER: every SKIP is judged later with chop_filter.skip_outcome() (RALLY_MISSED or LOSS_AVOIDED, net of cost); every TAKE gets its real result (WIN / LOSS). The log keeps the 9 score parts for chop_ledger / chop_score learning.
Called by api/chop.py every 30 s (step). Each call opens and closes its own database connections. Nothing here raises to the caller except step() argument errors."""
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_defs as D
import v2_scalp_ind as I
import v2_setup_finder as SF
import v2_store as ST
import chop_filter as F
import chop_score as S

VERSION = "chop_bot 1 (Part C3)"
DB_NAME = "chop_b3.db"
WEIGHTS_NAME = "chop_b3_weights.json"
INTERVAL, STEP = "5m", 300
FULL_USDT = 10.0
MAX_COINS, LOAD, FRESH_S, CATCHUP = 40, 520, 900, 3
JUDGE_PER_TURN, JUDGE_DROP_S = 30, 3 * 86400
SKIP_COINS = ("BTCUSDT",)
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS cursor (symbol TEXT PRIMARY KEY, last_ts INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS late (symbol TEXT PRIMARY KEY, cand_ts INTEGER NOT NULL, side TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, interval TEXT NOT NULL, candle_ts INTEGER NOT NULL, side TEXT, action TEXT NOT NULL,"
    " size TEXT, score REAL, scenario INTEGER, rule TEXT, why TEXT, late INTEGER NOT NULL DEFAULT 0, parts TEXT, trade_id INTEGER, v_net REAL, v_exit TEXT, v_final INTEGER NOT NULL DEFAULT 0,"
    " v_label TEXT, UNIQUE (symbol, candle_ts, late))",
    "CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, interval TEXT NOT NULL, side TEXT NOT NULL, size TEXT NOT NULL, invest REAL NOT NULL,"
    " entry_ts INTEGER NOT NULL, entry_px REAL NOT NULL, stop REAL NOT NULL, tp1 REAL, tp2 REAL, tp3 REAL, tp4 REAL, tp_hit INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN',"
    " exit_ts INTEGER, exit_px REAL, exit_reason TEXT, net_pct REAL, net_usdt REAL, decision_id INTEGER, score REAL)",
)


def open_db(data_dir):
    root = os.path.realpath(data_dir)
    if not os.path.isdir(root):
        raise ST.StoreRefused("data folder not found")
    con = sqlite3.connect(os.path.join(root, DB_NAME), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=10000")
    con.execute("PRAGMA journal_mode=WAL")
    for sql in SCHEMA:
        con.execute(sql)
    return con


def open_store_ro(data_dir):
    path = ST.store_path(data_dir)
    if not os.path.isfile(path):
        return None
    return sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)


def weights_path(data_dir):
    return os.path.join(os.path.realpath(data_dir), WEIGHTS_NAME)


def is_on(db):
    r = db.execute("SELECT value FROM meta WHERE key='on'").fetchone()
    return bool(r and r["value"] == "1")


def set_on(db, on):
    db.execute("INSERT OR REPLACE INTO meta VALUES ('on', ?)", ("1" if on else "0",))


def tp_levels(ind, i, side):
    """TP1-TP4 from the SD bands of candle i, the same rule as recovered_bot/strategy.py calculate_tp_levels. None if the bands do not exist yet."""
    mean, sd, c = ind["sd_mean"][i], ind["sd_std"][i], ind["close"][i]
    if mean is None or not sd:
        return None
    b = [mean + k * sd for k in (-3, -2, -1, 0, 1, 2, 3)]
    if side == "SELL":
        b.reverse()
        j = next((x for x in range(7) if c > b[x]), 6)
    else:
        j = next((x for x in range(7) if c < b[x]), 6)
    return tuple(b[min(j + m, 6)] for m in range(4))


def htf_side_at(run, i):
    """ABOVE / BELOW = last complete 15m close vs EMA50 of the 15m candles built from this 5m run (only candles up to i). None if too few."""
    e = i
    while e >= 0 and (run[e][0] + STEP) % 900 != 0:
        e -= 1
    closes = [run[k][4] for k in range(e, 1, -3)][:160][::-1] if e >= 2 else []
    if len(closes) < 51:
        return None
    em = I.ema(closes, 50)[-1]
    return None if em is None else ("ABOVE" if closes[-1] > em else "BELOW")


def _btc_map(sdb, now):
    return {r[0]: float(r[4]) for r in D.candles_from_store(sdb, "BTCUSDT", INTERVAL, now - 60 * STEP, now)}


def _btc_move(m, ts):
    a, b = m.get(ts), m.get(ts - 3 * STEP)
    return None if not a or not b else (a - b) / b * 100.0


def rule_of(res):
    """One short name per rule, so the ledger can say which rule is right or wrong."""
    sc, w = res["scenario"], res["why"]
    if res["action"] == "TAKE":
        return "late entry" if sc == 5 else "breakout key" if "breakout key" in w else "take"
    if sc == 4:
        return "chop gate"
    if sc == 3:
        return "Z+TSI both against"
    if sc == 8:
        return "late chase"
    if w.startswith("target"):
        return "fee check"
    if w.startswith("score"):
        return "score cut-off"
    if w.startswith("bigger"):
        return "bigger timeframe"
    return "late entry rejected" if sc == 5 else "other"


def _close(db, t, ts, px, reason, hit):
    w = 1 if t["side"] == "BUY" else -1
    net = (px - t["entry_px"]) * w / t["entry_px"] * 100.0 - F.COST_PCT
    db.execute("UPDATE trades SET status='CLOSED', exit_ts=?, exit_px=?, exit_reason=?, tp_hit=?, net_pct=?, net_usdt=? WHERE id=?",
               (int(ts), px, reason, int(hit), round(net, 4), round(net / 100.0 * t["invest"], 4), t["id"]))
    if t["decision_id"]:
        db.execute("UPDATE decisions SET v_net=?, v_exit=?, v_final=1, v_label=? WHERE id=?", (round(net, 4), reason, "WIN" if net > 0 else "LOSS", t["decision_id"]))
    return net


def _manage(db, t, cd):
    """One closed candle for one open trade. -> net % if it closed, else None."""
    ts, h, l = cd[0], cd[2], cd[3]
    if ts + STEP <= t["entry_ts"]:
        return None
    w = 1 if t["side"] == "BUY" else -1
    hit = t["tp_hit"]
    for k in (1, 2, 3, 4):
        lvl = t["tp%d" % k]
        if lvl is not None and ((h >= lvl) if w > 0 else (l <= lvl)):
            hit = max(hit, k)
    if (l <= t["stop"]) if w > 0 else (h >= t["stop"]):
        return _close(db, t, ts + STEP, t["stop"], "STOP", hit)
    if hit >= 4:
        return _close(db, t, ts + STEP, t["tp4"], "TARGET", 4)
    if hit != t["tp_hit"]:
        db.execute("UPDATE trades SET tp_hit=? WHERE id=?", (hit, t["id"]))
    return None


def _open_row(db, sym):
    return db.execute("SELECT * FROM trades WHERE symbol=? AND status='OPEN'", (sym,)).fetchone()


def _coin_losses(db, sym):
    n = 0
    for r in db.execute("SELECT net_usdt FROM trades WHERE symbol=? AND status='CLOSED' ORDER BY id DESC LIMIT 6", (sym,)).fetchall():
        if r["net_usdt"] is not None and r["net_usdt"] < 0:
            n += 1
        else:
            break
    return n


def _record(db, sym, cd, res, late):
    cur = db.execute("INSERT OR IGNORE INTO decisions (symbol, interval, candle_ts, side, action, size, score, scenario, rule, why, late, parts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (sym, INTERVAL, cd[0], res["side"], res["action"], res["size"], res["score"], res["scenario"], rule_of(res), res["why"], 1 if late else 0, json.dumps(res.get("parts"))))
    return cur.lastrowid if cur.rowcount else None


def _na(db, did, why):
    db.execute("UPDATE decisions SET action='SKIP', size='NONE', rule=?, why=?, v_final=1, v_label='NA' WHERE id=?", (why, why, did))


def _take(db, sym, run, ind, i, res, did):
    """Open the paper trade for a TAKE. -> True if a trade was opened."""
    cd, side = run[i], res["side"]
    t = _open_row(db, sym)
    if t is not None and t["side"] == side:
        _na(db, did, "already open")
        return False
    if t is not None:
        _close(db, t, cd[0] + STEP, cd[4], "REVERSED", t["tp_hit"])
    w = 1 if side == "BUY" else -1
    entry, stop, tps = cd[4], (cd[3] if side == "BUY" else cd[2]), tp_levels(ind, i, side)
    if tps is None or (entry - stop) * w <= 0 or (tps[3] - entry) * w <= 0:
        _na(db, did, "no valid stop or target")
        return False
    inv = FULL_USDT if res["size"] == "FULL" else FULL_USDT / 2.0
    cur = db.execute("INSERT INTO trades (symbol, interval, side, size, invest, entry_ts, entry_px, stop, tp1, tp2, tp3, tp4, decision_id, score) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (sym, INTERVAL, side, res["size"], inv, cd[0] + STEP, entry, stop, tps[0], tps[1], tps[2], tps[3], did, res["score"]))
    db.execute("UPDATE decisions SET trade_id=? WHERE id=?", (cur.lastrowid, did))
    return True


def _step_symbol(db, sdb, sym, now, on, weights, btcmap):
    out = {"decisions": 0, "opened": 0, "closed": 0}
    good, _bad = D.clean_candles(D.candles_from_store(sdb, sym, INTERVAL, now - (LOAD + 2) * STEP, now), INTERVAL)
    runs = SF.runs(good, INTERVAL)
    if not runs:
        return out
    run = runs[-1]
    last = run[-1][0]
    cur = db.execute("SELECT last_ts FROM cursor WHERE symbol=?", (sym,)).fetchone()
    if cur is None:
        db.execute("INSERT OR REPLACE INTO cursor VALUES (?,?)", (sym, last))
        return out
    new = [k for k, cd in enumerate(run) if cd[0] > cur["last_ts"]][-CATCHUP:]
    if not new:
        return out
    ind = I.compute(run)
    pos = {cd[0]: k for k, cd in enumerate(run)}
    for i in new:
        cd = run[i]
        t = _open_row(db, sym)
        if t is not None and _manage(db, t, cd) is not None:
            out["closed"] += 1
        if not on:
            continue
        btc, losses = _btc_move(btcmap, cd[0]), _coin_losses(db, sym)
        lr = db.execute("SELECT cand_ts, side FROM late WHERE symbol=?", (sym,)).fetchone()
        if lr is not None:
            idx = pos.get(lr["cand_ts"])
            if idx is None or i - idx > F.P["late_bars"]:
                db.execute("DELETE FROM late WHERE symbol=?", (sym,))
            elif i > idx:
                res = F.decide(run, ind, i, htf_side=htf_side_at(run, i), btc_move_pct=btc, coin_losses=losses, weights=weights, late_from={"i": idx, "side": lr["side"]})
                if res["action"] == "TAKE":
                    db.execute("DELETE FROM late WHERE symbol=?", (sym,))
                    did = _record(db, sym, cd, res, True)
                    if did:
                        out["decisions"] += 1
                        out["opened"] += 1 if _take(db, sym, run, ind, i, res, did) else 0
        if I.ema_cross(ind, i) is None:
            continue
        res = F.decide(run, ind, i, htf_side=htf_side_at(run, i), btc_move_pct=btc, coin_losses=losses, weights=weights)
        if res["action"] == "NONE" or res.get("side") is None:
            continue
        did = _record(db, sym, cd, res, False)
        if not did:
            continue
        out["decisions"] += 1
        if res["action"] == "TAKE":
            out["opened"] += 1 if _take(db, sym, run, ind, i, res, did) else 0
        elif res.get("late_candidate"):
            db.execute("INSERT OR REPLACE INTO late VALUES (?,?,?)", (sym, cd[0], res["side"]))
    db.execute("INSERT OR REPLACE INTO cursor VALUES (?,?)", (sym, last))
    return out


def judge(db, sdb, now):
    """The verdict of every SKIP: what it would have made (chop_filter.skip_outcome). Final when the stop or target was touched or 24 candles passed. -> number of rows updated."""
    n = 0
    rows = db.execute("SELECT id, symbol, candle_ts, side FROM decisions WHERE action='SKIP' AND v_final=0 AND side IS NOT NULL AND candle_ts<=? ORDER BY id LIMIT ?", (now - 2 * STEP, JUDGE_PER_TURN)).fetchall()
    for r in rows:
        if now - r["candle_ts"] > JUDGE_DROP_S:
            db.execute("UPDATE decisions SET v_final=1, v_label='NA' WHERE id=?", (r["id"],))
            continue
        good, _bad = D.clean_candles(D.candles_from_store(sdb, r["symbol"], INTERVAL, r["candle_ts"] - 260 * STEP, r["candle_ts"] + (F.P["horizon"] + 1) * STEP), INTERVAL)
        run = next((x for x in SF.runs(good, INTERVAL) if any(c[0] == r["candle_ts"] for c in x)), None)
        if run is None:
            continue
        k = next(j for j, c in enumerate(run) if c[0] == r["candle_ts"])
        o = F.skip_outcome(run, I.compute(run), k, r["side"])
        if o is None:
            if now - r["candle_ts"] > (F.P["horizon"] + 3) * STEP:
                db.execute("UPDATE decisions SET v_final=1, v_label='NA' WHERE id=?", (r["id"],))
            continue
        db.execute("UPDATE decisions SET v_net=?, v_exit=?, v_final=?, v_label=? WHERE id=?", (o["net_pct"], o["exit"], 1 if o["final"] else 0, o["label"], r["id"]))
        n += 1
    return n


def _live_symbols(db, sdb, now):
    rows = sdb.execute("SELECT symbol, MAX(open_ts) m FROM candles WHERE interval=? GROUP BY symbol HAVING m>=? ORDER BY symbol LIMIT ?", (INTERVAL, now - FRESH_S - STEP, MAX_COINS + 1)).fetchall()
    syms = [r[0] for r in rows if r[0] not in SKIP_COINS][:MAX_COINS]
    for r in db.execute("SELECT DISTINCT symbol FROM trades WHERE status='OPEN'").fetchall():
        if r["symbol"] not in syms:
            syms.append(r["symbol"])
    return syms


def last_prices(data_dir, syms):
    """{symbol: close of the newest saved 5m candle} for the open-trade view. {} on any problem."""
    out = {}
    try:
        sdb = open_store_ro(data_dir)
        if sdb is None:
            return out
        try:
            for s in syms:
                r = sdb.execute("SELECT c FROM candles WHERE symbol=? AND interval=? ORDER BY open_ts DESC LIMIT 1", (s, INTERVAL)).fetchone()
                if r:
                    out[s] = float(r[0])
        finally:
            sdb.close()
    except Exception:
        pass
    return out


def step(data_dir, now=None):
    """One turn: manage open trades, decide on new closed candles (only when ON), judge old SKIPs. -> small summary dict."""
    now = int(now if now is not None else time.time())
    db = open_db(data_dir)
    try:
        on = is_on(db)
        sdb = open_store_ro(data_dir)
        if sdb is None:
            return {"on": on, "note": "the market store is not created yet"}
        try:
            weights = S.load_weights(weights_path(data_dir))
            btcmap = _btc_map(sdb, now)
            tot = {"on": on, "coins": 0, "decisions": 0, "opened": 0, "closed": 0, "errors": 0}
            for sym in _live_symbols(db, sdb, now):
                try:
                    r = _step_symbol(db, sdb, sym, now, on, weights, btcmap)
                    tot["coins"] += 1
                    for k in ("decisions", "opened", "closed"):
                        tot[k] += r[k]
                except Exception:
                    tot["errors"] += 1
            tot["judged"] = judge(db, sdb, now)
            tot["ts"] = now
            return tot
        finally:
            sdb.close()
    finally:
        db.close()
