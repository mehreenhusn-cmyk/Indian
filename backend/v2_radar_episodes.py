"""v2_radar_episodes.py - Part 32: RADAR 4 of 6 (backend, read-only). The EPISODE rule: "one pump seen on 3 days in a row is ONE sample, not 3."
Over every saved cohort day (cohort_official) the same coin on the same side (GAINER or LOSER) on CONSECUTIVE UTC days is ONE episode. The first day is the
start; the later days are repeats. A day with no saved cohort splits an episode (a missing day is never bridged: unknown), and the same coin on the other side
starts a new episode. AUTHENTIC and PROXY rows of one episode are listed (mixed_sources says when both are inside). Used by v2_radar_outcomes (Part 31) so the
outcome counts can be shown for ALL rows and for NEW EPISODES ONLY. Read-only: store opened with mode=ro, never created, no network, no trading module.
Run (Termux):  python3 backend/v2_radar_episodes.py [--data DIR]   -> prints the episode list and counts as JSON."""
import argparse
import datetime
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_radar_episodes 1 (Part 32)"
LIST_CAP = 200                    # the printed list shows the newest 200 episodes (counts cover all of them)


def episodes(con):
    """-> list of episodes (symbol, kind, first_day, days, length_days, sources, mixed_sources), oldest first per coin. Rows with a bad day text are skipped and not counted."""
    rows = con.execute("SELECT day, kind, symbol, source FROM cohort_official ORDER BY symbol, kind, day").fetchall()
    eps, cur = [], None
    for day, kind, sym, src in rows:
        try:
            d = datetime.date.fromisoformat(day)
        except (TypeError, ValueError):
            continue
        if cur and cur["symbol"] == sym and cur["kind"] == kind and (d - cur["_last"]).days == 1:
            cur["days"].append(day)
            cur["_last"] = d
            cur["_src"].add(src)
        else:
            cur = {"symbol": sym, "kind": kind, "first_day": day, "days": [day], "_last": d, "_src": {src}}
            eps.append(cur)
    for e in eps:
        e.pop("_last")
        e["length_days"] = len(e["days"])
        e["sources"] = sorted(e.pop("_src"))
        e["mixed_sources"] = len(e["sources"]) > 1
    return eps


def mark(eps):
    """-> {(symbol, kind, day): {"first_day", "repeat", "day_no", "episode_days"}} so a cohort row can say whether it starts an episode or repeats one."""
    m = {}
    for e in eps:
        for i, day in enumerate(e["days"]):
            m[(e["symbol"], e["kind"], day)] = {"first_day": e["first_day"], "repeat": i > 0, "day_no": i + 1, "episode_days": e["length_days"]}
    return m


def build(con, now=None):
    now = int(time.time() if now is None else now)
    eps = episodes(con)
    rows = sum(e["length_days"] for e in eps)
    longest = max([e["length_days"] for e in eps] or [0])
    shown = sorted(eps, key=lambda e: (e["first_day"], e["symbol"]))[-LIST_CAP:]
    return {"tool": VERSION, "made_utc": datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), "read_only": True,
            "counts": {"cohort_rows": rows, "episodes": len(eps), "repeat_rows": rows - len(eps), "longest_episode_days": longest},
            "rule": "same coin + same side on consecutive UTC days = ONE episode; a day with no saved cohort splits it (never bridged); the other side is a new episode",
            "episodes": shown, "list_note": "newest %d episodes shown; the counts cover all of them" % LIST_CAP}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Radar episodes (read-only)")
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    import v2_inventory as I
    import v2_store as S
    path = S.store_path(I.find_data_dir(a.data))
    if not os.path.isfile(path):
        print("The market store is not created yet: nothing to report.")
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    try:
        print(json.dumps(build(con), indent=2, default=str))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
