"""Part 1B: Strategy Doctor engine. Run: python3 test/test_strategy_doctor.py"""
import os, sys, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import strategy_doctor as D

ZONES = D.ZONES


def make(n, seed, leak=None, sd_leak=False, fade_leak=False):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        act = rnd.choice(["BUY", "SELL"])
        zi = rnd.randrange(8)
        adx = rnd.uniform(8, 40)
        roi = rnd.gauss(0.4, 5.0)
        if leak == "adx" and adx < 16:
            roi -= 4.0
        if fade_leak and adx < 16 and i < int(n * 0.6):
            roi -= 4.0
        counter = (act == "BUY" and zi < 4) or (act == "SELL" and zi >= 4)
        if sd_leak and counter:
            roi -= 3.0
        out.append({
            "action": act, "roi_pct": roi, "pnl_usdt": roi * 0.5, "opened_at_ts": 1_700_000_000 + i * 600,
            "entry_zone": ZONES[zi], "adx": adx, "ema_gap_atr": rnd.uniform(0.1, 3), "htf_trend": rnd.choice(["up", "down", "flat"]),
            "regime_cross_n": rnd.randrange(0, 8), "atr_pct": rnd.uniform(0.1, 1.5), "sd_width_pct": rnd.uniform(0.2, 2),
            "volume_ratio": rnd.uniform(0.3, 3), "ema_slope_pct": rnd.gauss(0, 0.3), "ema_turn": rnd.choice(["flat", "steady up", "turning up"]),
            "timeframe": rnd.choice(["3m", "5m"]), "quality_tag": "clean", "peak_roi_pct": max(0.0, rnd.gauss(2, 3)),
            "tp_hit_levels": [], "invest_usdt": 100.0, "fee_roi_pct": 1.0,
        })
    return out


def test_empty_and_tiny():
    assert D.build_from([])["sample"] == 0
    r = D.build_from(make(15, 1))
    assert r["enough"] is False and r["avoid"] == [] and "Not enough data" in " ".join(r["headline"])


def test_planted_leak_is_found_and_confirmed():
    r = D.build_from(make(500, 3, leak="adx"))
    assert r["enough"]
    top = r["avoid"][0]
    assert top["feature"] == "adx" and top["label"].startswith("Low") and top["status"] == "confirmed", top
    assert r["final"]["delta_usdt"] > 0 and r["final"]["confirmed_rules"] >= 1


def test_leak_that_stopped_is_rarely_confirmed():
    # the leak exists only in the first 60% of trades; across many random histories the new-30% check
    # should usually refuse it (a lucky noisy test window can still let one through)
    seeds = range(200, 220)
    hits = 0
    for s in seeds:
        r = D.build_from(make(500, s, fade_leak=True))
        hits += any(a["feature"] == "adx" and a["status"] == "confirmed" for a in r["avoid"])
    print("faded leak confirmed in", hits, "of 20 histories")
    assert hits <= 6


def test_sd_rule_good_and_wrong_direction():
    good = D.build_from(make(400, 5, sd_leak=True))["sd_rules"][0]
    assert good["blocked"]["sum"] < 0 and good["verdict"].startswith("Good rule")
    flat = D.build_from(make(400, 6))["sd_rules"][0]
    assert flat["blocked"]["n"] > 50  # rule table is filled even with no leak


def test_noise_rarely_confirms():
    hits = sum(1 for s in range(20) if D.build_from(make(400, 100 + s))["final"]["confirmed_rules"] > 0)
    print("noise seeds with a confirmed rule:", hits, "of 20")
    assert hits <= 4    # luck-rules still slip through now and then; the screen warns about that


def test_excluded_trades_and_bad_rows():
    rows = make(60, 7)
    rows[0]["quality_tag"] = "outdated"
    rows[1]["clean_exit_reason"] = "MANUAL"
    rows[2]["roi_pct"] = None
    rows.append({"action": "HOLD"})
    rows.append({})
    r = D.build_from(rows)
    assert r["sample"] == 57


def test_old_trades_without_new_fields():
    rows = make(100, 8)
    for t in rows:
        for k in ("adx", "ema_gap_atr", "htf_trend"):
            t.pop(k)
    r = D.build_from(rows)
    assert r["data_ready"]["adx"] == 0 and all(m["feature"] not in ("adx", "gap", "htf") for m in r["mistakes"])


def test_loss_story_and_final_keys():
    r = D.build_from(make(200, 9))
    ls = r["loss_story"]
    assert ls["green_then_lost"] + ls["never_green"] == ls["known"]
    assert "net_pnl" in r["final"] and "fee_total" in r["final"]


def test_post_exit_section_and_build_never_raises():
    import tempfile, json
    from recovered_bot import ai_post_exit
    ai_post_exit.init(tempfile.mkdtemp())
    assert "still" in " ".join(D._post_exit()["lines"]).lower() or "started" in " ".join(D._post_exit()["lines"]).lower()
    with open(ai_post_exit._file, "w") as f:
        for i in range(30):
            f.write(json.dumps({"reason": "SL", "samples": 20, "at60": 3.0 if i % 2 else -2.0, "best_after": 4.0, "worst_after": -1.0}) + "\n")
            f.write(json.dumps({"reason": "TP4", "samples": 20, "best_after": 6.0, "worst_after": -2.0, "back_to_entry": i % 3 == 0}) + "\n")
    p = D._post_exit()
    assert p["enough"] and p["stop_back_pct"] == 50 and p["profit_median_best_after"] == 6.0
    r = D.build()                     # trade_store not initialised here: must still return a dict, never raise
    assert isinstance(r, dict) and "headline" in r


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); n += 1; print("ok", name)
    print(n, "tests passed")
