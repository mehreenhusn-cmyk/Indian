"""v2_bt_playbook.py - Part 88c: BRAIN TRADER INDICATOR PLAYBOOK + WHAT-IF EXPLORER (backend, read-only, COUNTERFACTUAL).
Both parts use the CLOSED paper trades of ONE source (PAPER by default, sources are never mixed) and the group labels of Part 88a (lines_of / grade are reused, nothing is re-invented).
1) PLAYBOOK = 'what the Brain is learning', one block per indicator of the owner's chart: EMA50 + SD bands, TSI, Z + Z-SMA, histogram (red storm), TSI + Z together, volume.
   Per block: which chart states are USE (30+ trades, net above 0 in BOTH halves of their history), which are AVOID (same, below 0), which are MIXED, and how many states are still too thin
   (the 3 nearest to 30 trades are named with 'needs N more'). Every USE / AVOID row also gets the HOLDOUT check of Part 88b (newest trades, needs 10: CONFIRMS / AGAINST / NOT ENOUGH YET).
   The luck note says how many states were checked at once: when many states are checked, some look good by pure luck, so only NEW trades after a rule is frozen can prove anything.
2) WHAT-IF = the owner picks states by hand: skip = ['dim:label', ...] drops every trade that matches ANY of them, only = ['dim:label', ...] keeps only trades that match ALL of them.
   Answer: A (all closed trades = BT-01 as it ran) vs B (what is left), the skipped trades on their own, today's net for both, status. At most 4 rules. Nothing is saved or changed.
   HONEST LIMIT (said on the screen): a filter chosen by looking at past trades always looks better on those same trades, and every what-if you try is one more look. Only new trades can prove it.
   The status is never more than 'LOOKS BETTER ON PAST TRADES (not proven)'. BT-02 is NOT running; changing a rule needs the owner's OK.
Trades made before Part 86a have no storm / clash tag: they are left out of those groups, never guessed. No win rate, no forecast, no advice to open a trade.
Reads v2_brain_trader.db read-only. No network, no write, no trading import.
Run (Termux, optional):  python3 backend/v2_bt_playbook.py [--source PAPER] [--skip "SD zone:ZONE_X|TSI vs the trade:TSI against the trade"] [--only "..."]  -> the plain lines."""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_filter as FL
import v2_bt_review as RV
import v2_bt_store as B

VERSION = "v2_bt_playbook 1 (Part 88c)"
DAY, MAX_RULES, NEAR = 86400, 4, 3
TITLES = dict(RV.DIMS)
SECTIONS = (("EMA50 + SD bands", ("state", "zone", "width")), ("TSI", ("tsi",)), ("Z-score + Z-SMA", ("z",)), ("Histogram (red storm)", ("storm",)),
            ("TSI + Z together", ("agree", "clash")), ("Volume", ("volume",)))
LIMIT = ("A filter chosen from past trades always looks better on those same trades, and every what-if you try is one more look at the same trades. "
         "Only new trades after a rule is frozen can prove it. BT-02 is NOT running and changing a rule needs your OK.")


def _items(ts):
    return [(t["ts"], t["net"]) for t in ts]


def playbook(trades):
    """One block per indicator. Rows only for groups with 30+ trades; thinner groups are counted, the nearest ones named."""
    blocks, checked = [], 0
    for title, dims in SECTIONS:
        rows, thin = [], []
        for dim in dims:
            for lab, ts in RV.groups(trades, dim).items():
                checked += 1
                g = RV.grade(_items(ts))
                g.update({"dim": dim, "dim_title": TITLES[dim], "label": lab})
                if g["n"] < RV.MIN_N:
                    thin.append({"dim_title": TITLES[dim], "label": lab, "n": g["n"], "needs": RV.MIN_N - g["n"]})
                    continue
                g["holdout"] = FL._holdout(ts) if g["verdict"] in ("USE", "AVOID") else None
                rows.append(g)
        rows.sort(key=lambda r: -r["net_usdt"])
        thin.sort(key=lambda r: r["needs"])
        use, avoid = [r for r in rows if r["verdict"] == "USE"], [r for r in rows if r["verdict"] == "AVOID"]
        mixed = [r for r in rows if r["verdict"] == "MIXED"]
        lines = []
        for r in use:
            lines.append("USE when %s is %s: %d trades, net %+.2f USDT, both halves positive." % (r["dim_title"], r["label"], r["n"], r["net_usdt"]))
        for r in avoid:
            lines.append("AVOID when %s is %s: %d trades, net %+.2f USDT, both halves negative." % (r["dim_title"], r["label"], r["n"], r["net_usdt"]))
        if mixed:
            lines.append("%d state(s) have 30+ trades but the older and newer half disagree: MIXED, no verdict." % len(mixed))
        if not rows:
            lines.append("Nothing proven yet for %s: %s." % (title, ("no state has 30 trades yet" if thin else "no tagged trades yet")))
        blocks.append({"title": title, "use": use, "avoid": avoid, "mixed": mixed, "thin_count": len(thin), "nearest": thin[:NEAR], "lines": lines})
    return blocks, checked


def parse_rules(text):
    """'dim:label|dim:label' (or a list) -> [(dim, label)]. The dim is the short key (zone) or its title (SD zone); the label is split off at the FIRST colon only."""
    if not text:
        return []
    parts = text if isinstance(text, (list, tuple)) else str(text).split("|")
    keys = {k: k for k, _ in RV.DIMS}
    keys.update({t.lower(): k for k, t in RV.DIMS})
    out = []
    for p in parts:
        p = str(p).strip()
        if not p:
            continue
        d, sep, lab = p.partition(":")
        k = keys.get(d.strip()) or keys.get(d.strip().lower())
        if not sep or not k or not lab.strip():
            raise ValueError("a rule must look like zone:LABEL (dim, a colon, the group label)")
        out.append((k, lab.strip()))
    return out


def _match(t, rule):
    return t["lines"].get(rule[0]) == rule[1]


def whatif(trades, skip, only, day_start):
    if len(skip) + len(only) > MAX_RULES:
        raise ValueError("at most %d rules" % MAX_RULES)
    unknown = [("%s:%s" % (TITLES[d], lab)) for d, lab in skip + only if not any(_match(t, (d, lab)) for t in trades)]
    kept, dropped = [], []
    for t in trades:
        out = any(_match(t, r) for r in skip) or not all(_match(t, r) for r in only)
        (dropped if out else kept).append(t)
    a, b, s = RV.grade(_items(trades)), RV.grade(_items(kept)), RV.grade(_items(dropped))
    td = lambda xs: round(sum(t["net"] for t in xs if t["ts"] >= day_start), 2)
    share = round(len(dropped) / len(trades), 2) if trades else 0.0
    ho = FL._holdout(dropped)
    if not trades or not (skip or only):
        st = "NO RULE PICKED"
    elif unknown:
        st = "NO TRADE HAS THAT STATE"
    elif b["n"] < RV.MIN_N:
        st = "TOO FEW TRADES LEFT"
    elif ho["status"] == "AGAINST":
        st = "HOLDOUT AGAINST"
    else:
        st = "LOOKS BETTER ON PAST TRADES (not proven)" if b["net_usdt"] > a["net_usdt"] and b["newer_net"] > a["newer_net"] else "NOT BETTER"
    return {"A": dict(a, name="All closed trades (BT-01 as it ran)"), "B": dict(b, name="What is left after your rules (NOT running)"), "dropped": dict(s, share=share, holdout=ho),
            "today_A_net": td(trades), "today_B_net": td(kept), "unknown": unknown, "status": st}


def choices(trades):
    return [{"dim": d, "title": t, "labels": sorted(({"label": lab, "n": len(ts)} for lab, ts in RV.groups(trades, d).items()), key=lambda x: -x["n"])} for d, t in RV.DIMS]


def _closed(data_dir, source):
    con = B.open_ro(data_dir)
    if con is None:
        return None
    try:
        return RV.closed_trades(con, source)
    finally:
        con.close()


def _src(source):
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")


def build_playbook(data_dir, source="PAPER", now=None):
    _src(source)
    trades = _closed(data_dir, source)
    if trades is None:
        return {"ready": False, "source": source, "lines": ["No Brain Trader file yet. Run the Brain tick or a replay first."], "note": "no Brain Trader file yet"}
    blocks, checked = playbook(trades)
    n_ok = sum(len(b["use"]) + len(b["avoid"]) for b in blocks)
    lines = ["%s: %d closed paper trades. %d chart states checked, %d have a USE or AVOID verdict (30+ trades, same sign in both halves)." % (source, len(trades), checked, n_ok)]
    if len(trades) < RV.MIN_N:
        lines.append("Too few closed trades to learn anything yet (a state needs %d). The Brain keeps exploring and says USE or AVOID only with evidence." % RV.MIN_N)
    if checked > 10 and n_ok:
        lines.append("Luck note: %d states were checked at once, so a few can look good by pure luck. Trust a row more when its holdout CONFIRMS." % checked)
    return {"ready": True, "framework": VERSION, "source": source, "total_closed": len(trades), "checked": checked, "blocks": blocks, "lines": lines, "limit": LIMIT,
            "note": "Closed paper trades only, net of fee + slippage. Words and numbers, not an order; it never changes the live bot."}


def build_whatif(data_dir, source="PAPER", skip=None, only=None, now=None):
    _src(source)
    now = int(time.time() if now is None else now)
    sk, on = parse_rules(skip), parse_rules(only)
    trades = _closed(data_dir, source)
    if trades is None:
        return {"ready": False, "source": source, "lines": ["No Brain Trader file yet. Run the Brain tick or a replay first."], "note": "no Brain Trader file yet"}
    x = whatif(trades, sk, on, now - now % DAY)
    A, Bb, D = x["A"], x["B"], x["dropped"]
    lines = ["What-if on the same %d closed %s trades. Skip: %s. Only: %s." % (len(trades), source, " / ".join("%s = %s" % (TITLES[d], l) for d, l in sk) or "nothing", " / ".join("%s = %s" % (TITLES[d], l) for d, l in on) or "nothing")]
    if x["unknown"]:
        lines.append("No closed trade has this state: %s." % ", ".join(x["unknown"]))
    elif sk or on:
        lines.append("A (all) net %+.2f USDT in %d trades. B (what is left) net %+.2f USDT in %d trades. The %d dropped trades net %+.2f USDT." % (A["net_usdt"], A["n"], Bb["net_usdt"], Bb["n"], D["n"], D["net_usdt"]))
        if D["share"] > FL.MAX_SKIP_SHARE:
            lines.append("Warning: your rules drop %d%% of all trades. That is not a filter, that is a different strategy." % round(D["share"] * 100))
        lines.append("Holdout check of the dropped trades: %s (%d newest trades, net %+.2f)." % (D["holdout"]["status"], D["holdout"]["n"], D["holdout"]["net_usdt"]))
    lines.append("Status: %s. %s" % (x["status"], LIMIT))
    return {"ready": True, "framework": VERSION, "source": source, "total_closed": len(trades), "skip": [list(r) for r in sk], "only": [list(r) for r in on], "result": x, "choices": choices(trades), "lines": lines, "limit": LIMIT}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="PAPER", choices=B.SOURCES)
    ap.add_argument("--skip", default="")
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    r = build_whatif(a.data, a.source, a.skip, a.only) if (a.skip or a.only) else build_playbook(a.data, a.source)
    print("\n".join(r["lines"] + ([l for b in r.get("blocks", []) for l in ["[%s]" % b["title"]] + b["lines"]] if "blocks" in r else [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
