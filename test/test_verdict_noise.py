"""Honesty check: on pure-noise trades the Doctor Verdict must almost never call a group 'confirmed'.
Run: python3 test/test_verdict_noise.py"""
import os, sys, random
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from recovered_bot import india_doctor as ID, doctor_verdict as V
IST = timezone(timedelta(hours=5, minutes=30))
SLOTS = [(9, 20), (10, 40), (12, 10), (13, 40)]


def trades(n_days, seed, bad_open=False):
    rnd, out, d = random.Random(seed), [], 0
    while len(out) < n_days * 4:
        day = datetime(2026, 6, 1, tzinfo=IST) + timedelta(days=d); d += 1
        if day.weekday() >= 5: continue
        for si, (h, m) in enumerate(SLOTS):
            o = day.replace(hour=h, minute=m); roi = rnd.gauss(0.8, 6.0) - (7.0 if bad_open and si == 0 else 0)
            cost = 5020.0
            out.append({"action": "LONG" if rnd.random() < .5 else "SHORT", "entry_premium": 100.0, "qty": 50, "buy_fee": 20.0,
                        "pnl": roi / 100 * cost, "fees": 40.0, "opened_at": o.isoformat(),
                        "closed_at": (o + timedelta(minutes=rnd.uniform(8, 25))).isoformat(), "reason": "TP" if roi > 0 else "SL",
                        "tags": {"timeframe": "5m"}, "mfe_pct": max(roi, 0) + abs(rnd.gauss(0, 2)), "mae_pct": -2.0,
                        "tp_hit": 0, "contract": {"type": "CE"}, "underlying": "NIFTY"})
    return out


def confirmed(v):
    c = t = 0
    for tab in v.values():
        if isinstance(tab, list) and tab and isinstance(tab[0], dict):
            for r in tab:
                s = str(r.get("status") or "")
                t += bool(s) and s != "too_few"; c += s.startswith("confirmed")
    return c, t


def test_noise_almost_never_confirms_and_planted_leak_is_found():
    hits = tot = 0
    for shift in (0.0, -1.5):
        for s in range(300, 330):
            rows = ID.rows(trades(60, s))
            for r in rows: r["roi_pct"] += shift; r["pnl_usdt"] += shift * 50
            c, t = confirmed(V.build(rows, unit="Rs")); hits += c; tot += t
    print("noise: confirmed", hits, "of", tot, "judged groups")
    assert hits <= 0.03 * max(1, tot)
    v = V.build(ID.rows(trades(60, 3, bad_open=True)), unit="Rs")
    assert [x for x in v["time_of_day"] if x["label"].startswith("09:15")][0]["status"] == "confirmed_bad"


if __name__ == "__main__":
    test_noise_almost_never_confirms_and_planted_leak_is_found(); print("PASS")
