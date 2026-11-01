"""v2_sys_health.py - Part M1a: SYSTEM HEALTH (backend, read-only). Mock picture 10 as an IDEA, but ONLY REAL FACTS: every card is measured right now from this machine's own files, or it says NOT AVAILABLE. Nothing is invented.
Cards (each = key, title, state OK / WARN / BAD / NOT AVAILABLE, value, sub line):
  backend      this backend process: online (it just answered) and how long it has been running (since this file was loaded)
  market_data  the candle store v2_market.db: how many coins got a 5m candle in the last hour
  candle_feed  age of the newest saved 5m candle (OK up to 10 min, WARN up to 30 min, then BAD)
  collector    the last health line the candle collector wrote
  brain_tick   the Brain auto-runner (v2_bt_auto_status.json): last tick age, errors, switch on / off
  brain_study  the 6-hour study job: age of the last study
  brain_data   v2_brain_trader.db: age of the newest Brain decision, open pretend trades PAPER and SHADOW (BT-02)
  safety       the Brain guard: kill switch ARMED / TRIPPED and the ledger check (reconciliation)
  cpu          load average of the last minute against the number of cores (NOT AVAILABLE if the phone does not allow it)
  ram          memory used from /proc/meminfo (NOT AVAILABLE if the phone does not allow it)
  disk         used space of the data folder's disk
  files        size of the two databases
NOT MEASURED (listed with the reason, never faked): WebSocket latency, API latency, reconnects, orders, AI assistant status. The backend does not measure them yet.
Headline: BAD anywhere = needs attention, WARN = mostly fine, else all measured systems OK. Times over 60 minutes are shown as hours + minutes.
Reads files only (stores opened read-only). No network, no write, no trading import. The route /api/v2/sys_health (api/v2_data.py) calls build().
Run (Termux, optional):  python3 backend/v2_sys_health.py [--data DIR]  -> the plain lines."""
import argparse
import os
import shutil
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_auto as AU
import v2_bt_guard as G
import v2_bt_store as B
import v2_store as S

VERSION = "v2_sys_health 1 (Part M1a)"
START = time.time()
NA = "NOT AVAILABLE"
NOT_MEASURED = (("WebSocket", "the backend does not measure a live socket"), ("API latency", "no timing is saved anywhere"), ("Reconnects", "no reconnect counter exists"),
                ("Orders", "the Brain only makes pretend trades; the main bot's order health is not measured here"), ("AI assistant", "no AI status is saved"))


def dur(sec):
    """Plain time text; over 60 minutes = hours + minutes (owner rule)."""
    s = max(0, int(sec))
    if s < 60:
        return "%d s" % s
    m = s // 60
    if m < 60:
        return "%d min" % m
    h, m = divmod(m, 60)
    if h < 24:
        return "%d h %d min" % (h, m)
    d, h = divmod(h, 24)
    return "%d d %d h %d min" % (d, h, m)


def card(key, title, state, value, sub=""):
    return {"key": key, "title": title, "state": state, "value": value, "sub": sub}


def _na(key, title, why):
    return card(key, title, NA, "-", why)


def _age_state(age, ok, warn):
    return "OK" if age <= ok else "WARN" if age <= warn else "BAD"


def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)


def market(data_dir, now):
    path = S.store_path(data_dir)
    if not os.path.isfile(path):
        return [_na("market_data", "Market data", "No candle store yet."), _na("candle_feed", "Candle feed", "No candle store yet."), _na("collector", "Collector", "No candle store yet.")]
    con = _ro(path)
    try:
        last = con.execute("SELECT MAX(open_ts) FROM candles WHERE interval='5m'").fetchone()[0]
        coins = con.execute("SELECT COUNT(DISTINCT symbol) FROM candles WHERE interval='5m' AND open_ts>=?", (now - 3600,)).fetchone()[0]
        col = con.execute("SELECT ts, status, note FROM collector_health ORDER BY ts DESC LIMIT 1").fetchone()
    finally:
        con.close()
    out = [card("market_data", "Market data", "OK" if coins else "BAD", "%d coins" % coins, "with a 5m candle in the last hour")]
    if last is None:
        out.append(_na("candle_feed", "Candle feed", "No 5m candle saved yet."))
    else:
        age = now - (last + 300)
        out.append(card("candle_feed", "Candle feed", _age_state(age, 600, 1800), "Healthy" if age <= 600 else "Late" if age <= 1800 else "Stale", "newest candle closed %s ago" % dur(age)))
    if col is None:
        out.append(_na("collector", "Collector", "The collector has not written a health line yet."))
    else:
        age = now - col[0]
        out.append(card("collector", "Collector", "OK" if str(col[1]).upper() in ("OK", "RUNNING", "HEALTHY") and age <= 1800 else "WARN", str(col[1]), "last line %s ago%s" % (dur(age), (" - " + str(col[2])[:60]) if col[2] else "")))
    return out


def brain(data_dir, now):
    st = AU.read_status(data_dir)
    if not st:
        tick = card("brain_tick", "Brain tick", NA, "-", "The auto-runner has not saved a status yet.")
        study = _na("brain_study", "Brain study", "No study saved yet.")
    else:
        lt, ls = (st.get("last_tick") or {}).get("ts"), (st.get("last_study") or {}).get("ts")
        on = AU.is_enabled(data_dir)
        err = st.get("tick_errors", 0)
        if lt is None:
            tick = card("brain_tick", "Brain tick", "WARN", "No tick yet", "the runner is %s" % ("ON" if on else "OFF"))
        else:
            age = now - lt
            tick = card("brain_tick", "Brain tick", _age_state(age, 900, 3600) if on else "WARN", "%s ago" % dur(age) if on else "Switched OFF", "%d tick error(s) so far%s" % (err, (", last: " + str((st.get("last_error") or {}).get("name"))) if err else ""))
        study = _na("brain_study", "Brain study", "No study has run yet.") if ls is None else card("brain_study", "Brain study", _age_state(now - ls, 8 * 3600, 24 * 3600), "%s ago" % dur(now - ls), "runs every 6 hours")
    con = B.open_ro(data_dir)
    if con is None:
        return [tick, study, _na("brain_data", "Brain data", "No Brain Trader file yet."), _na("safety", "Safety", "No Brain Trader file yet.")]
    try:
        last = con.execute("SELECT MAX(close_ts) FROM bt_decision").fetchone()[0]
        paper, shadow = len(B.open_trades(con, "PAPER")), len(B.open_trades(con, "SHADOW"))
        kill, rec = G.is_killed(con), G.reconcile(con, now)
    finally:
        con.close()
    data = _na("brain_data", "Brain data", "No decision saved yet.") if last is None else card("brain_data", "Brain data", _age_state(now - last, 900, 3600), "%s ago" % dur(now - last), "newest decision; open trades: %d PAPER, %d SHADOW" % (paper, shadow))
    safe = card("safety", "Safety", "BAD" if kill or rec["state"] == "FAIL" else "WARN" if rec["state"] == "WARN" else "OK", "KILL SWITCH ON" if kill else "Armed", "ledger check: %s (%d orphan, %d stuck)" % (rec["state"], rec["orphan_closes"], rec["stuck_open"]))
    return [tick, study, data, safe]


def machine(data_dir):
    out = []
    try:
        n, load = os.cpu_count() or 1, os.getloadavg()[0]
        out.append(card("cpu", "CPU load", "OK" if load < 0.7 * n else "WARN" if load < 1.5 * n else "BAD", "%.2f" % load, "1-minute load on %d core(s)" % n))
    except (OSError, AttributeError):
        out.append(_na("cpu", "CPU load", "This phone does not allow reading the load."))
    try:
        mem = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("MemTotal", "MemAvailable"):
                    mem[k] = int(v.split()[0]) * 1024.0
        tot, av = mem["MemTotal"], mem["MemAvailable"]
        pct = (tot - av) / tot * 100.0
        out.append(card("ram", "RAM", "OK" if pct < 80 else "WARN" if pct < 92 else "BAD", "%.0f%%" % pct, "%.1f GB used of %.1f GB" % ((tot - av) / 1e9, tot / 1e9)))
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        out.append(_na("ram", "RAM", "This phone does not allow reading memory."))
    try:
        u = shutil.disk_usage(os.path.realpath(data_dir))
        pct = u.used / u.total * 100.0
        out.append(card("disk", "Disk space", "OK" if pct < 80 else "WARN" if pct < 92 else "BAD", "%.0f%%" % pct, "%.1f GB used of %.1f GB" % (u.used / 1e9, u.total / 1e9)))
    except OSError:
        out.append(_na("disk", "Disk space", "The data folder was not found."))
    sizes = []
    for name in (S.DB_NAME, B.DB_NAME if hasattr(B, "DB_NAME") else "v2_brain_trader.db"):
        try:
            sizes.append("%s %.1f MB" % (name, os.path.getsize(os.path.join(os.path.realpath(data_dir), name)) / 1e6))
        except OSError:
            sizes.append("%s missing" % name)
    out.append(card("files", "Data files", "OK", "%d files" % len(sizes), "; ".join(sizes)))
    return out


def build(data_dir, now=None):
    now = int(time.time() if now is None else now)
    cards = [card("backend", "Backend", "OK", "Online", "running for %s (since this file was loaded)" % dur(now - START))]
    for fn in (lambda: market(data_dir, now), lambda: brain(data_dir, now), lambda: machine(data_dir)):
        try:
            cards += fn()
        except Exception as e:                                         # one bad check never hides the others
            cards.append(_na("check_%d" % len(cards), "A check", "It failed (%s)." % type(e).__name__))
    bad = sum(1 for c in cards if c["state"] == "BAD")
    warn = sum(1 for c in cards if c["state"] == "WARN")
    na = sum(1 for c in cards if c["state"] == NA)
    head = ("Needs attention: %d red" % bad) if bad else ("Mostly fine: %d warning(s)" % warn) if warn else "All measured systems OK"
    return {"ready": True, "framework": VERSION, "live": "LOCKED", "headline": head, "bad": bad, "warn": warn, "not_available": na, "cards": cards,
            "not_measured": [{"title": t, "why": w} for t, w in NOT_MEASURED],
            "note": "Every card is measured right now from this machine's own files. A card that cannot be measured says NOT AVAILABLE; the not-measured list is never faked. Read-only."}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    a = ap.parse_args(argv)
    r = build(a.data)
    print(r["headline"])
    for c in r["cards"]:
        print(" %-14s %-14s %-18s %s" % (c["title"], c["state"], c["value"], c["sub"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
