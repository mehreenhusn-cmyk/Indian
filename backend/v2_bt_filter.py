"""v2_bt_filter.py - Part 88b: BRAIN TRADER TAKE / SKIP FILTER candidates + A/B test (backend, read-only, COUNTERFACTUAL).
From the night review (Part 88a) it takes the groups that are AVOID (30+ closed trades, net below 0 in BOTH halves of their history) and turns the worst ones into FILTER CANDIDATES, in words:
'Skip when <chart tag> is <value>'. At most 2 candidates per night (README5 3.3: few changes, never a pile of rules). For each: how many trades it would have skipped, what those trades lost, and a HOLDOUT CHECK
= the same group's newest trades (sample HOLDOUT or NEW) must also be negative (CONFIRMS / AGAINST / NOT ENOUGH YET, needs 10 trades).
A/B: A = BT-01 as it is. B = 'BT-02 candidate' = BT-01 minus the trades the candidates would have skipped. Both are worked out on the SAME closed trades, so nothing is traded twice and nothing new is saved.
HONEST LIMIT (said on the screen): a filter chosen from past trades always looks better on those same trades. Only NEW trades after the filter is frozen can prove it, so the status is never more than
'LOOKS BETTER ON PAST TRADES' until the owner says OK and a real BT-02 runs next to BT-01 on new signals. BT-02 is NOT running. This file changes no rule, no version, no live bot.
Reads v2_brain_trader.db read-only. No network, no write, no trading import. Run (Termux, optional):  python3 backend/v2_bt_filter.py [--source PAPER]  -> the plain lines."""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_review as RV
import v2_bt_store as B

VERSION = "v2_bt_filter 1 (Part 88b)"
MAX_CANDIDATES, HOLDOUT_MIN, DAY, MAX_SKIP_SHARE = 2, 10, 86400, 0.5      # a filter that skips more than half of ALL trades is not a filter (NV)
TITLES = dict(RV.DIMS)


def _holdout(ts):
    h = [t for t in ts if t["sample"] in ("HOLDOUT", "NEW")]
    n, net = len(h), round(sum(t["net"] for t in h), 2)
    st = "NOT ENOUGH YET" if n < HOLDOUT_MIN else "CONFIRMS" if net < 0 else "AGAINST"
    return {"n": n, "net_usdt": net, "status": st, "need": HOLDOUT_MIN}


def candidates(trades):
    """The worst AVOID groups (one per dimension and label), most losing first, at most MAX_CANDIDATES. A candidate that would skip the same trades as a better one is not added twice, and together the candidates may skip at most half of all trades."""
    found = []
    for dim, title in RV.DIMS:
        for lab, ts in RV.groups(trades, dim).items():
            g = RV.grade([(t["ts"], t["net"]) for t in ts])
            if g["verdict"] == "AVOID":
                found.append({"dim": dim, "title": title, "label": lab, "rule": "Skip when %s is: %s" % (title, lab), "skips": g["n"], "skipped_net_usdt": g["net_usdt"], "older_net": g["older_net"], "newer_net": g["newer_net"],
                              "holdout": _holdout(ts), "_ids": set(id(t) for t in ts)})
    found.sort(key=lambda c: c["skipped_net_usdt"])
    out, seen = [], set()
    for c in found:
        if len(out) >= MAX_CANDIDATES:
            break
        if c["_ids"] <= seen or len(seen | c["_ids"]) > MAX_SKIP_SHARE * len(trades):
            continue
        seen |= c["_ids"]
        out.append(c)
    return out


def ab(trades, cands, day_start):
    ids = set()
    for c in cands:
        ids |= c["_ids"]
    keep = [t for t in trades if id(t) not in ids]
    a, b = RV.grade([(t["ts"], t["net"]) for t in trades]), RV.grade([(t["ts"], t["net"]) for t in keep])
    td = lambda xs: round(sum(t["net"] for t in xs if t["ts"] >= day_start), 2)
    return {"A": dict(a, name="BT-01 (running)"), "B": dict(b, name="BT-02 candidate (NOT running)"), "skipped": len(trades) - len(keep), "today_A_net": td(trades), "today_B_net": td(keep)}


def build(data_dir, source="PAPER", now=None):
    now = int(time.time() if now is None else now)
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    con = B.open_ro(data_dir)
    if con is None:
        return {"ready": False, "source": source, "lines": ["No Brain Trader file yet."], "note": "no Brain Trader file yet"}
    try:
        trades = RV.closed_trades(con, source)
    finally:
        con.close()
    cands = candidates(trades)
    res = {"ready": True, "framework": VERSION, "source": source, "total_closed": len(trades), "candidates": [{k: v for k, v in c.items() if k != "_ids"} for c in cands], "ab": None,
           "limit": "A filter chosen from past trades always looks better on those same trades. Only new trades after the filter is frozen can prove it. BT-02 is NOT running and changing a rule needs your OK."}
    if not cands:
        res["status"] = "NO CANDIDATE"
        res["lines"] = ["No filter candidate yet: no group has %d+ closed paper trades and a loss in both halves of its history (%d closed trades so far)." % (RV.MIN_N, len(trades))]
        return res
    x = ab(trades, cands, now - now % DAY)
    res["ab"] = x
    A, Bb = x["A"], x["B"]
    better = Bb["net_usdt"] > A["net_usdt"] and Bb["newer_net"] > A["newer_net"]
    against = any(c["holdout"]["status"] == "AGAINST" for c in cands)
    res["status"] = "LOOKS BETTER ON PAST TRADES (not proven)" if better and not against else "HOLDOUT AGAINST" if against else "NOT BETTER"
    res["lines"] = ["%d filter candidate(s). Rule: %s." % (len(cands), " / ".join(c["rule"] for c in cands)),
                    "On the same %d closed trades: A (BT-01) net %+.2f USDT, B (BT-02 candidate) net %+.2f USDT, %d trades skipped." % (A["n"], A["net_usdt"], Bb["net_usdt"], x["skipped"]),
                    "Holdout check: %s." % ", ".join("%s: %s (%d newest trades, net %+.2f)" % (c["label"], c["holdout"]["status"], c["holdout"]["n"], c["holdout"]["net_usdt"]) for c in cands),
                    "Status: %s. %s" % (res["status"], res["limit"])]
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="PAPER", choices=B.SOURCES)
    a = ap.parse_args(argv)
    print("\n".join(build(a.data, a.source)["lines"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
