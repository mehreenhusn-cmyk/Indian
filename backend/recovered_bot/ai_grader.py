"""
ai_grader.py - evidence-based setup grade. Not a fixed indicator checklist.

A candidate has tags (SD zone, TSI state, Z vs price, regime ...). The grader looks at ALL resolved candidates (ai_candidates:
taken, skipped and missed alike, results in R after fees) and asks: how did setups with these tags (single and pairs) really do?
A pattern only counts when it holds on the OLDER 60% AND the NEWER 40% in the same direction.
  A  proven edge (confirmed patterns average +0.25R or better)
  B  data exists but no proven edge for this combination (not traded)
  C  proven to lose (not traded)
  U  unproven - fewer than 40 resolved setups so far (traded at half risk only while learning, if the owner allows it)
"""
from . import ai_candidates as AC

MIN_N = 12
MIN_TOTAL = 40
MIN_OLD, MIN_NEW = 8, 4


def _split(rows):
    rows = sorted(rows, key=lambda r: r["t"])
    cut = rows[int(len(rows) * 0.6)]["t"] if rows else 0
    return rows, cut


def grade(tokens, rows=None):
    rows = AC.resolved() if rows is None else rows
    total = len(rows)
    if total < MIN_TOTAL:
        return {"grade": "U", "exp_r": None, "n": total, "why": f"Unproven: only {total} observed setups so far (needs {MIN_TOTAL}+)."}
    rows, cut = _split(rows)
    sets = [(r["t"], r["r"], set(r["tk"])) for r in rows]
    toks = sorted(set(tokens))[:18]
    cands = [(k,) for k in toks]
    for a in range(len(toks)):
        for b in range(a + 1, len(toks)):
            if toks[a].split("=")[0] != toks[b].split("=")[0]:
                cands.append((toks[a], toks[b]))
    good = []
    for c in cands:
        old = [r for t, r, s in sets if t < cut and all(k in s for k in c)]
        new = [r for t, r, s in sets if t >= cut and all(k in s for k in c)]
        if len(old) < MIN_OLD or len(new) < MIN_NEW or len(old) + len(new) < MIN_N:
            continue
        ao, an = sum(old) / len(old), sum(new) / len(new)
        if ao * an > 0 and min(abs(ao), abs(an)) >= 0.08:
            n = len(old) + len(new)
            good.append({"p": " + ".join(c), "n": n, "avg": round((sum(old) + sum(new)) / n, 3)})
    if not good:
        return {"grade": "B", "exp_r": None, "n": total, "why": "No proven edge for this combination yet."}
    good.sort(key=lambda x: -x["n"])
    wn = sum(g["n"] for g in good)
    exp = sum(g["avg"] * g["n"] for g in good) / wn
    veto = any(g["avg"] <= -0.3 and g["n"] >= 15 for g in good)
    g = "C" if (veto or exp < 0) else ("A" if (exp >= 0.25 and wn >= 20) else "B")
    top = ", ".join(f"{x['p']} ({x['avg']:+.2f}R, n={x['n']})" for x in good[:2])
    return {"grade": g, "exp_r": round(exp, 3), "n": total, "why": f"Proven on old and new data: {top}."}
