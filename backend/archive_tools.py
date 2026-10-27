"""Part U5 (Z3b): two small read-only archive tools - check() and export_csv(). Nothing here writes to any file or database.

check()      does the permanent archive (dual_archive.db) hold EVERY finished trade that dual_lab_data.json still holds?
             match = yes, the Brain could later read the archive instead of the JSON | differ = some are missing (stay on the JSON) | none = nothing to compare yet.
export_csv() finished (or all) trades of the archive as CSV text, one line per trade, with the coin source tag (today / d7 / other) and USDT.
Routes: GET /api/archive_check, GET /api/archive_export. Command line: python3 tools/db_check.py, python3 tools/archive_export.py.
"""
import csv
import io
import json
import os
import sqlite3
import time

import universe_7d as U

BTC = "BTCUSDT"
_C = {"t": 0.0, "v": None}


def _ro(base):
    path = os.path.join(U._dir(base), "dual_archive.db")
    if not os.path.exists(path):
        return None
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)


def check(base=None):
    now = time.time()
    if base is None and _C["v"] is not None and now - _C["t"] < 60:
        return dict(_C["v"])
    out = {"state": "none", "json_closed": 0, "db_closed": 0, "missing": 0, "text": "Archive not started yet.", "err": ""}
    try:
        con = _ro(base)
        if con is not None:
            try:
                db_ids = {r[0] for r in con.execute("SELECT id FROM trades WHERE status = 'closed'")}
            finally:
                con.close()
            with open(os.path.join(U._dir(base), "dual_lab_data.json"), "r", encoding="utf-8") as f:
                js = json.load(f)
            ids = {str(t.get("id")) for t in (js.get("trades") or []) if t.get("status") == "closed"}
            out.update(json_closed=len(ids), db_closed=len(db_ids), missing=len(ids - db_ids))
            if not ids:
                out["text"] = "No finished trade in the JSON file yet."
            elif out["missing"] == 0:
                out["state"], out["text"] = "match", "Archive has all %d finished trades of the JSON file (and %d in total)." % (len(ids), len(db_ids))
            else:
                out["state"], out["text"] = "differ", "%d of %d finished trades are not in the archive yet. The Brain stays on the JSON file." % (out["missing"], len(ids))
    except FileNotFoundError:
        out["text"] = "Archive exists, JSON file not found yet."
    except Exception as ex:
        out["state"], out["err"] = "error", "%s: %s" % (type(ex).__name__, str(ex)[:100])
        out["text"] = "Archive check error: " + out["err"]
    if base is None:
        _C["t"], _C["v"] = now, dict(out)
    return out


def export_csv(base=None, days=None, closed_only=True, now_s=None):
    """CSV text. days = only the last N UTC days (None = everything). Money columns are USDT (BTC margin 1000, others 100)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "time_utc", "coin", "tf", "side", "signal", "status", "net_pct", "usdt", "exit_rule", "mode", "source"])
    con = _ro(base)
    if con is None:
        return buf.getvalue()
    try:
        log = U.load_log(base)
        since = 0 if not days else U.day_start_ms(time.time() if now_s is None else now_s) - (int(days) - 1) * U.DAY_MS
        q = "SELECT id, t, sym, tf, side, src, status, net, exit_rule, mode FROM trades WHERE t >= ?"
        q += " AND status = 'closed'" if closed_only else ""
        for i, t, sym, tf, side, src, st, net, ex, mode in con.execute(q + " ORDER BY t", (since,)):
            usdt = "" if net is None else round((1000.0 if sym == BTC else 100.0) * net / 100.0, 2)
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime((t or 0) / 1000.0))
            w.writerow([i, when, sym, tf, "LONG" if (side or 0) > 0 else "SHORT", src, st, net, usdt, ex, mode, U.tag_of(sym, t or 0, log)])
    finally:
        con.close()
    return buf.getvalue()
