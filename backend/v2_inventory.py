"""v2_inventory.py - Part 3: DATA INVENTORY (read-only). Answers: "what data does the Owl app really have?"

The owner runs it ONCE on the phone and sends the JSON file. It never changes a database, setting, trade or live order.
Uses Part 1 (v2_inv_safe: read-only opener, WAL-safe snapshot, symlink check) and Part 2 (v2_inv_redact: fail-closed secret scrubber).
No network, no trading module, no new library.

Run (Termux):   python3 backend/v2_inventory.py            -> writes owl_inventory.json into the Download folder
                python3 backend/v2_inventory.py --data ~/owl_data --out /sdcard/Download/owl_inventory.json
The JSON holds names, counts, time ranges and labels only. Row VALUES are never copied (only a few short mode / timeframe labels).
If anything secret-looking is still in the report, NO file is written and only the field name is shown.

Evidence label per table (by row count and time column; a label is about data amount, NOT about profit):
  Not collected (0 rows) | Data incomplete (no usable time column, or bad timestamps) | Insufficient data (< 30 rows)
  | Exploratory (30-299 rows) | Watch (300+ rows, clean timestamps).
Paper / live mix: only reported when a column named like mode / paper / live / account exists; otherwise "NV" (not verifiable).
Tests: python3 test/test_v2_inventory.py
"""
import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inv_redact as R
import v2_inv_safe as S

VERSION = "v2_inventory 1 (Part 3)"
MAX_FILES, MAX_TABLES, MAX_LINES = 300, 80, 2000000
TIME_WORDS = ("timestamp", "time", "ts", "date", "created", "opened", "closed", "open_time", "close_time", "entry_time",
              "exit_time", "at")
SYMBOL_WORDS = ("symbol", "coin", "pair", "ticker")
TF_WORDS = ("timeframe", "tf", "interval")
MODE_WORDS = ("mode", "paper", "live", "account", "is_live", "is_paper", "real")
KNOWN = {                                           # verified by reading the repo (30 Oct); everything else = "NV"
    "dual_archive.db": "trade_archive.py / dual_desk.py / archive_tools.py (Dual Bot archive)",
    "owl.db": "api_server.py via db.init (main app data)",
    "trades.db": "config.py DB_PATH (main trades)",
    "brain_archive.db": "Brain modules (exact writer not verified: NV)",
}


def q(name):
    """Quote an SQL identifier (names come from the file itself)."""
    return '"' + str(name).replace('"', '""') + '"'


def label(rows, time_ok):
    if rows == 0:
        return "Not collected"
    if not time_ok:
        return "Data incomplete"
    if rows < 30:
        return "Insufficient data"
    return "Exploratory" if rows < 300 else "Watch"


def pick(cols, words):
    low = {c.lower(): c for c in cols}
    for w in words:                                  # exact name first, then "contains" (e.g. entry_ts)
        if w in low:
            return low[w]
    for w in words:
        for k, c in low.items():
            if w in k.split("_") or k.startswith(w + "_") or k.endswith("_" + w):
                return c
    return None


def iso(v):
    """Epoch seconds / milliseconds -> UTC text. Text stays as stored. Returns (text, kind)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        x = float(v)
        if x > 1e17:
            x /= 1e9
        elif x > 1e14:
            x /= 1e6
        elif x > 1e11:
            x /= 1e3
        if 1e8 < x < 4e9:
            return datetime.datetime.fromtimestamp(x, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), "epoch"
        return str(v), "number"
    return str(v)[:40], "text"


def epoch_of(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        x = float(v)
        x = x / 1e3 if x > 1e11 else x
        return x if 1e8 < x < 4e9 else None
    return None


def one(con, sql):
    try:
        return con.execute(sql).fetchone()
    except Exception:
        return None


def table_report(con, name, now):
    t = {"table": name}
    cols = [(r[1], r[2] or "") for r in con.execute("PRAGMA table_info(%s)" % q(name))]
    names = [c for c, _ in cols]
    t["columns"] = [{"name": c, "type": ty} for c, ty in cols][:80]
    rows = (one(con, "SELECT count(*) FROM %s" % q(name)) or [None])[0]
    if rows is None:
        t.update(status="error", reason="row count failed", label="Data incomplete")
        return t
    t["rows"] = rows
    tc = pick(names, TIME_WORDS)
    time_ok, problems = False, []
    if tc and rows:
        mn, mx, nul = (one(con, "SELECT min(%s), max(%s), sum(%s IS NULL OR %s = '') FROM %s"
                           % (q(tc), q(tc), q(tc), q(tc), q(name))) or (None, None, None))
        a, ka = iso(mn) if mn is not None else (None, None)
        b, kb = iso(mx) if mx is not None else (None, None)
        t["time"] = {"column": tc, "first": a, "last": b, "kind": ka or kb,
                     "zone": "UTC (epoch numbers)" if "epoch" in (ka, kb) else "as stored in the file (zone NV)"}
        if nul:
            problems.append("%d empty timestamps" % nul)
        e = epoch_of(mx)
        if e and e > now + 86400:
            problems.append("timestamps in the future")
        time_ok = mn is not None and not (nul and nul >= rows)
        if ka == "number":
            problems.append("time column is not epoch seconds/milliseconds")
            time_ok = False
    elif not tc:
        problems.append("no time column found")
    sc, tfc, mc = pick(names, SYMBOL_WORDS), pick(names, TF_WORDS), pick(names, MODE_WORDS)
    if sc and rows:
        t["symbols_distinct"] = (one(con, "SELECT count(DISTINCT %s) FROM %s" % (q(sc), q(name))) or [None])[0]
        if tc and rows <= 500000:                    # duplicate rate = same symbol + same time seen more than once
            d = one(con, "SELECT count(*) - count(DISTINCT %s || '|' || %s) FROM %s WHERE %s IS NOT NULL"
                    % (q(sc), q(tc), q(name), q(tc)))
            if d and d[0] is not None:
                t["duplicate_rows"] = d[0]
                t["duplicate_rate"] = round(d[0] / float(rows), 4)
    if tfc and rows:
        vals = con.execute("SELECT %s, count(*) FROM %s GROUP BY 1 ORDER BY 2 DESC LIMIT 10" % (q(tfc), q(name))).fetchall()
        t["timeframes"] = {str(v)[:12]: n for v, n in vals}
    if mc and rows:
        vals = con.execute("SELECT %s, count(*) FROM %s GROUP BY 1 ORDER BY 2 DESC LIMIT 6" % (q(mc), q(name))).fetchall()
        t["paper_live_column"] = {"column": mc, "values": {str(v)[:16]: n for v, n in vals}}
        t["paper_live_mix"] = "column exists - owner/Claude must read the values; not decided here"
    else:
        t["paper_live_mix"] = "NV (no mode / paper / live column)"
    t["problems"] = problems
    t["label"] = label(rows, time_ok)
    t["safe_for_research"] = bool(t["label"] in ("Exploratory", "Watch") and not problems)
    return t


def db_report(path, roots):
    out = {"kind": "sqlite", "bytes": os.path.getsize(path)}
    try:
        with S.open_safe(path, roots) as db:
            out["open_mode"] = db.label()
            tabs = [r[0] for r in db.con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                                 "ORDER BY name")]
            out["tables_total"] = len(tabs)
            out["tables"] = []
            now = time.time()
            for n in tabs[:MAX_TABLES]:
                try:
                    out["tables"].append(table_report(db.con, n, now))
                except Exception:
                    out["tables"].append({"table": n, "status": "error", "reason": "could not be read", "label": "Data incomplete"})
            labels = [t["label"] for t in out["tables"]]
            out["label"] = "Not collected" if labels and all(x == "Not collected" for x in labels) else (
                "Data incomplete" if not labels or "Data incomplete" in labels else labels[0] if len(set(labels)) == 1 else "Mixed")
    except (S.UnsafePath, S.OpenFailed) as e:
        out.update(status="not opened", reason=str(e), label="Data incomplete")
    return out


def text_file_report(path, ext, roots):
    out = {"kind": ext.lstrip("."), "bytes": os.path.getsize(path)}
    try:
        real, link = S.resolve_under(path, roots)
    except S.UnsafePath as e:
        out.update(status="not opened", reason=str(e), label="Data incomplete")
        return out
    if link:
        out["symlink_inside_allowed_folder"] = True
    try:
        if ext == ".json":
            if out["bytes"] > 5 * 1024 * 1024:
                out.update(status="skipped", reason="over 5 MB for key listing", label="Data incomplete")
                return out
            with open(real, "r", encoding="utf-8", errors="replace") as f:
                out["key_paths"] = R.key_paths(json.load(f))[:200]          # names only, never values
            out["label"] = "Exploratory" if out["key_paths"] else "Not collected"
            return out
        n, first, bad = 0, None, 0
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                n += 1
                if first is None:
                    first = line
                if ext == ".jsonl" and n <= 50:
                    try:
                        json.loads(line)
                    except ValueError:
                        bad += 1
                if n >= MAX_LINES:
                    out["counting_stopped_at"] = MAX_LINES
                    break
        out["lines"] = n
        if first is not None:
            if ext == ".csv":
                out["header_columns"] = [c.strip()[:40] for c in first.split(",")][:80]
            else:
                try:
                    out["key_paths"] = R.key_paths(json.loads(first))[:80]
                except ValueError:
                    out["key_paths"] = []
        out["unparsable_in_first_50"] = bad
        out["label"] = label(max(n - (1 if ext == ".csv" else 0), 0), bool(n) and not bad)
    except Exception:
        out.update(status="error", reason="could not be read", label="Data incomplete")
    return out


def find_data_dir(arg=None):
    base = arg or os.environ.get("OWL_DATA_DIR")
    if not base:
        try:
            with open(os.path.expanduser("~/.owl_data_dir"), "r", encoding="utf-8") as f:
                base = f.read().strip()
        except Exception:
            base = ""
    return os.path.expanduser(base or "~/owl_data")


def default_out():
    for d in ("/storage/emulated/0/Download", os.path.expanduser("~/storage/downloads"), os.getcwd()):
        if os.path.isdir(d) and os.access(d, os.W_OK):
            return os.path.join(d, "owl_inventory.json")
    return os.path.join(os.getcwd(), "owl_inventory.json")


def build_report(data_dir):
    root = os.path.realpath(data_dir)
    rep = {"tool": VERSION, "made_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
           "read_only": True, "data_folder_name": os.path.basename(root), "files": {}, "summary": {}}
    if not os.path.isdir(root):
        rep["summary"] = {"error": "data folder not found", "files_seen": 0}
        return rep
    seen, skipped = [], 0
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x not in ("__pycache__", "node_modules"))
        if os.path.relpath(d, root).count(os.sep) >= 2:
            dirs[:] = []
        for fn in sorted(files):
            ext = os.path.splitext(fn)[1].lower()
            if ext in (".db", ".sqlite", ".sqlite3", ".json", ".jsonl", ".csv"):
                if len(seen) < MAX_FILES:
                    seen.append(os.path.join(d, fn))
                else:
                    skipped += 1
    counts = {}
    for p in seen:
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        ext = os.path.splitext(p)[1].lower()
        try:
            st = os.stat(p)
            if ext in (".db", ".sqlite", ".sqlite3"):
                r = db_report(p, [root])
            else:
                r = text_file_report(p, ext, [root])
            r["modified_utc"] = datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            r["written_by"] = KNOWN.get(os.path.basename(p), "NV (not verified)")
        except OSError:
            r = {"status": "error", "reason": "file vanished or unreadable", "label": "Data incomplete"}
        rep["files"][rel] = r
        counts[r.get("label", "?")] = counts.get(r.get("label", "?"), 0) + 1
    rep["summary"] = {"files_seen": len(seen), "files_over_limit": skipped, "by_label": counts,
                      "note": "Labels describe amount and timestamp quality only. They say nothing about profit."}
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl data inventory (read-only)")
    ap.add_argument("--data", help="data folder (default: OWL_DATA_DIR, ~/.owl_data_dir, ~/owl_data)")
    ap.add_argument("--out", help="report file (default: Download/owl_inventory.json)")
    a = ap.parse_args(argv)
    data, out = find_data_dir(a.data), a.out or default_out()
    rep = build_report(data)
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: the report still looked secret in these fields, so NO file was written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Inventory written: %s  (%d files checked)" % (out, rep["summary"].get("files_seen", 0)))
    print("Nothing was changed. Send this JSON file to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
