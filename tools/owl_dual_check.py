#!/usr/bin/env python3
"""tools/owl_dual_check.py - R16a: which "Dual today" number is right? READ ONLY (nothing is written, no network).
Prints, side by side, the three sources of the Dual numbers and says why they differ:
  1. dual_today      the permanent archive (dual_archive.db), closed since 00:00 UTC, alt coins, BTC apart = THE source now
  2. dual_desk groups the old Dashboard sum (trades OPENED today, finished, BTC inside)
  3. dual_lab file   dual_lab_data.json = the old Dual screen (only the newest ~600 trades are kept there)
Run (Termux, from the repo folder, with the real data folder):  python3 tools/owl_dual_check.py ~/storage/shared/owl_data"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import dual_desk as DK
import dual_today as DT
import universe_7d as U


def main(argv):
    base = argv[1] if len(argv) > 1 else (os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    now = time.time()
    t = DT.today(base, now)
    a, b = t["alts"], t["btc"]
    print("Day (UTC): %s   archive state: %s %s" % (t["day"], t["state"], t["err"]))
    print("1. dual_today (THE source): alts closed %d (won %d, lost %d), realized %+.2f USDT | open %d | BTC apart: closed %d, %+.2f USDT" % (a["closed"], a["wins"], a["losses"], a["realized"], a["open"], b["closed"], b["realized"]))
    g = DK.desk(base, now).get("groups", {})
    n = sum(c["n"] for x in g.values() for c in x.values())
    net = sum(c["net"] for x in g.values() for c in x.values())
    print("2. old Dashboard sum (opened today, finished, BTC inside): %d trades, %+.2f USDT" % (n, net))
    path = os.path.join(U._dir(base), "dual_lab_data.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            tr = (json.load(f) or {}).get("trades") or []
        d0 = t["since_ms"]
        alt = [x for x in tr if x.get("s") != DT.BTC and x.get("status") == "closed" and (x.get("closed_at") or x["t"] / 1000.0) * 1000 >= d0]
        usdt = sum(DT.MARGIN * (x.get("net") or 0.0) / 100.0 for x in alt)
        print("3. old Dual screen (dual_lab_data.json, %d trades kept in the file): %d closed today, %+.2f USDT" % (len(tr), len(alt), usdt))
        if len(tr) >= 590:
            print("   -> the file is full (about 600 kept): older trades of today are cut off, so this number is TOO SMALL. Source 1 is the complete one.")
    except Exception as e:
        print("3. dual_lab_data.json could not be read (%s: %s)" % (type(e).__name__, str(e)[:80]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
