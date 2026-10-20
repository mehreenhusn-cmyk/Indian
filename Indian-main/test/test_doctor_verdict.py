import os, random, sys, time
from datetime import datetime, timedelta, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
sys.path.insert(0, os.path.join(HERE, "..", "backend", "recovered_bot"))
from recovered_bot import india_doctor, doctor_verdict

IST = timezone(timedelta(hours=5, minutes=30))


def fake(n, seed=1, plant=True):
    random.seed(seed)
    out, t = [], datetime(2026, 9, 1, 9, 20, tzinfo=IST)
    for i in range(n):
        t += timedelta(hours=random.choice([1, 3, 20]))
        if t.hour >= 15 or t.hour < 9:
            t = t.replace(hour=9, minute=30) + timedelta(days=1)
        lunch = 12 <= t.hour < 13                               # planted: lunch entries always lose
        win = (not lunch) and random.random() < 0.55
        prem, qty = 100.0, 50
        pnl = random.uniform(400, 1500) if win else -random.uniform(500, 1200)
        hold = random.choice([3, 10, 25, 45, 90])
        out.append({"action": "LONG" if i % 2 else "SHORT", "entry_premium": prem, "qty": qty, "buy_fee": 20,
                    "pnl": pnl, "fees": 40, "opened_at": t, "closed_at": t + timedelta(minutes=hold),
                    "reason": "SL", "tp_hit": 1 if (not win and i % 5 == 0) else 0,
                    "mfe_pct": random.uniform(5, 40) if not win else random.uniform(20, 60), "mae_pct": -10,
                    "underlying": "NIFTY" if i % 3 else "BANKNIFTY", "contract": {"type": "CE"},
                    "tags": {"timeframe": 5, "entry_zone": "mid" if i % 2 else "upper"}})
    return out


def test_small_sample_says_not_enough():
    v = doctor_verdict.build(india_doctor.rows(fake(10)))
    assert v["ok"] and not v["enough"] and "Not enough data" in " ".join(v["lines"])


def test_planted_lunch_leak_found_and_confirmed():
    v = doctor_verdict.build(india_doctor.rows(fake(400)))
    assert v["enough"]
    lunch = [t for t in v["time_of_day"] if "lunch" in t["label"]][0]
    assert lunch["status"] == "confirmed_bad", lunch
    assert any("lunch" in l for l in v["lines"]), v["lines"]
    assert v["leakage"]["tp1_then_loss_n"] > 0 and len(v["hold"]) >= 4


def test_never_raises_and_old_trades_ok():
    assert doctor_verdict.build([{"junk": 1}, None])["enough"] is False
    old = fake(60)
    for t in old: t.pop("mfe_pct"); t.pop("tags")
    assert doctor_verdict.build(india_doctor.rows(old))["ok"]


def test_tsi_tables_and_planted_tsi_leak():
    tr = fake(400)
    for i, t in enumerate(tr):
        against = i % 3 == 0
        t["tags"].update({"tsi_with_trade": "against" if against else "with", "tsi_band": "tsi>25", "z_band": "z -1..1"})
        if against:
            t["pnl"] = -abs(t["pnl"])
    v = doctor_verdict.build(india_doctor.rows(tr))
    bad = [x for x in v["tsi_vs_trade"] if "against" in x["label"]][0]
    assert bad["status"] == "confirmed_bad" and v["tsi_x_zone"]
    assert any("TSI" in l for l in v["lines"]), v["lines"]


def test_indicator_tags_record_only_and_safe():
    from recovered_bot import india_bridge
    from datetime import datetime
    cs = [{"t": datetime(2026, 9, 1, 9, 15) + timedelta(minutes=5 * i), "o": 100 + i * .1, "h": 101 + i * .1,
           "l": 99 + i * .1, "c": 100 + (i % 7) * .3 + i * .05, "v": 1} for i in range(300)]
    tg = india_bridge.indicator_tags(cs, "BUY")
    assert {"z", "tsi", "tsi_band", "z_band", "tsi_with_trade"} <= set(tg), tg
    assert india_bridge.indicator_tags(cs[:5], "BUY") == {}          # too little history: just nothing, no error
    assert india_bridge.indicator_tags(None, "BUY") == {}


def test_crypto_verdict_path_and_studies_never_raise():
    rows = [{"action": "BUY" if i % 2 else "SELL", "roi_pct": 5.0 if i % 3 else -6.0, "pnl_usdt": 5.0 if i % 3 else -6.0,
             "opened_at_ts": 1.78e9 + i * 3600, "closed_at_ts": 1.78e9 + i * 3600 + 600, "symbol": "BTCUSDT"} for i in range(80)]
    v = doctor_verdict.build(rows, unit="USDT", studies=True)
    assert v["ok"] and v["enough"] and isinstance(v.get("studies"), list) and v["hold"]


def test_attached_to_doctor_report_fast():
    t0 = time.time(); rep = india_doctor.build(fake(1500)); dt = time.time() - t0
    assert "verdict" in rep and dt < 1.0, dt
    assert "headline" in rep and "sd_zones" in rep            # existing report untouched


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
    print("verdict tests passed")
