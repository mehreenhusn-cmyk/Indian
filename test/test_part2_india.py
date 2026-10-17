"""Part 2 (India): SL type, MFE/MAE, tags, stats, India Doctor, tick-driven check. Run: python3 test/test_part2_india.py"""
import os, sys, random, threading, time
from datetime import datetime, date, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import india_stats, india_doctor, strategy_doctor as D
from recovered_bot.india_paper import IndiaPaperEngine, SL_TYPES


class FakeProv:
    """Minimal provider: spot / premium / candle are set by hand."""
    def __init__(self):
        self.t = datetime(2026, 10, 15, 10, 0)
        self.spot, self.ltp = 100.0, 50.0
        self.candle = {"o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0}
    def now(self): return self.t
    def get_spot(self, u): return self.spot
    def get_last_candle(self, u): return dict(self.candle)
    def get_option_ltp(self, c, spot=None): return self.ltp


def engine(**s):
    p = FakeProv()
    e = IndiaPaperEngine(p, {"capital": 1e7, **s})
    contract = {"underlying": "NIFTY", "expiry": date(2026, 10, 29), "strike": 100, "type": "CE", "lot": 50, "key": "K1"}
    return p, e, contract


def open_long(p, e, c, tags=None):
    e.select = lambda u, ot, spot, now: (c, p.ltp, "t", "")
    e._entry_ok = lambda now: (True, "")
    r = e.on_signal("NIFTY", "BUY", 95.0, 110.0, tps=[110, 115, 120, 125], tags=tags)
    assert r["ok"], r
    p.t += timedelta(minutes=1)
    return r["trade"]


def test_settings_defaults_and_choices():
    assert SL_TYPES == ("index", "premium", "both")
    p, e, c = engine()
    assert e.s["sl_type"] == "index" and e.s["premium_sl_pct"] == 30.0


def test_index_mode_ignores_premium_drop_default_unchanged():
    p, e, c = engine()
    open_long(p, e, c)
    p.ltp = 20.0                                  # premium -60 %, index SL not touched
    assert e.on_tick() == [] and len(e.open) == 1


def test_premium_mode_exits_on_premium_drop_only():
    p, e, c = engine(sl_type="premium", premium_sl_pct=30.0)
    open_long(p, e, c)
    p.candle.update(c=90.0, o=96.0, l=90.0)       # index closes below SL - premium mode must NOT use it
    p.spot, p.ltp = 90.0, 40.0                    # premium -20 % only
    assert e.on_tick() == []
    p.ltp = 33.0                                  # -34 %
    done = e.on_tick()
    assert len(done) == 1 and done[0]["reason"] == "PSL"


def test_both_mode_whichever_first():
    p, e, c = engine(sl_type="both", premium_sl_pct=30.0)
    open_long(p, e, c)
    p.candle.update(c=94.0, o=99.0, l=94.0); p.spot = 94.0
    done = e.on_tick()
    assert len(done) == 1 and done[0]["reason"] in ("SL", "SL(GAP)")


def test_mfe_mae_tracked_and_saved_on_close():
    p, e, c = engine()
    pos = open_long(p, e, c, tags={"entry_zone": "mean..+1sd", "adx": 22.0})
    p.ltp, p.spot = 60.0, 103.0; e.on_tick()
    p.ltp, p.spot = 45.0, 99.0; e.on_tick()
    pos = list(e.open.values())[0]
    assert pos["mfe_pct"] > 15 and pos["mae_pct"] < -5 and pos["mfe_spot"] > 2 and pos["mae_spot"] < 0
    rec = e.close_one(pos["id"])
    assert rec["tags"]["adx"] == 22.0 and rec["mfe_pct"] > 15


def test_tick_check_does_not_write_disk_every_call():
    p, e, c = engine()
    e.state_path = None
    saves = []
    def fake_save():
        saves.append(1)
        e._saved_at = time.time()      # what the real _save does
    e._save = fake_save
    open_long(p, e, c)
    saves.clear()
    for _ in range(50):
        e.on_tick()
    assert len(saves) <= 1


def _closed(n, seed, leak=False):
    rnd = random.Random(seed)
    out = []
    t0 = datetime(2026, 9, 1, 10, 0)
    for i in range(n):
        long_ = rnd.random() < 0.5
        adx = rnd.uniform(8, 40)
        pnl = rnd.gauss(100, 900) - (1500 if (leak and adx < 16) else 0)
        out.append({"id": i + 1, "underlying": rnd.choice(["NIFTY", "BANKNIFTY"]), "action": "LONG" if long_ else "SHORT",
                    "contract": {"type": "CE" if long_ else "PE"}, "qty": 50, "entry_premium": 100.0, "buy_fee": 30.0,
                    "pnl": pnl, "fees": 70.0, "reason": rnd.choice(["SL", "TP4", "TSL"]), "tp_hit": rnd.randrange(3),
                    "opened_at": t0 + timedelta(minutes=30 * i), "closed_at": t0 + timedelta(minutes=30 * i + 20),
                    "mfe_pct": max(0.0, rnd.gauss(8, 8)), "mae_pct": -abs(rnd.gauss(8, 6)),
                    "tags": {"entry_zone": rnd.choice(D.ZONES), "adx": adx, "timeframe": "5m", "ema_gap_atr": rnd.uniform(0, 3),
                             "htf_trend": rnd.choice(["up", "down", "flat"]), "regime_cross_n": rnd.randrange(0, 6),
                             "atr_pct": rnd.uniform(0.05, 0.4), "sd_width_pct": rnd.uniform(0.3, 1.5), "volume_ratio": rnd.uniform(0.4, 2.5),
                             "ema_slope_pct": rnd.gauss(0, 0.1), "ema_turn": "flat"}})
    return out


def test_stats_numbers():
    s = india_stats.build(_closed(80, 1), 200000)
    assert s["trades"] == 80 and s["wins"] + s["losses"] <= 80
    assert s["max_drawdown"] >= 0 and len(s["curve"]) <= 160 and s["curve"][-1]["v"] == round(200000 + s["net_pnl"], 2)
    assert s["rr"] is None or s["rr"] > 0
    assert india_stats.build([], 1000)["trades"] == 0


def test_stats_hand_checked():
    tr = [{"pnl": 300, "fees": 10, "closed_at": "2026-10-01 10:00", "underlying": "NIFTY", "action": "LONG", "reason": "TP4"},
          {"pnl": -100, "fees": 10, "closed_at": "2026-10-01 11:00", "underlying": "NIFTY", "action": "SHORT", "reason": "SL"},
          {"pnl": -200, "fees": 10, "closed_at": "2026-10-01 12:00", "underlying": "NIFTY", "action": "LONG", "reason": "SL"},
          {"pnl": 100, "fees": 10, "closed_at": "2026-10-01 13:00", "underlying": "NIFTY", "action": "LONG", "reason": "TP4"}]
    s = india_stats.build(tr, 1000)
    assert s["win_rate"] == 50.0 and s["avg_win"] == 200 and s["avg_loss"] == -150 and s["rr"] == 1.33
    assert s["expectancy"] == 25.0 and s["profit_factor"] == 1.33 and s["max_drawdown"] == 300 and s["net_pnl"] == 100


def test_india_doctor_runs_uses_rs_and_ce_pe_and_finds_leak():
    r = india_doctor.build(_closed(500, 3, leak=True))
    assert r["ok"] and r["unit"] == "Rs" and r["side_names"]["BUY"] == "CE (call)"
    assert "Rs" in r["headline"][0] and "USDT" not in " ".join(r["headline"])
    top = r["avoid"][0]
    assert top["feature"] == "adx" and top["label"].startswith("Low") and top["status"] == "confirmed", top
    assert any(m["feature"] == "und" for m in r["mistakes"])


def test_india_doctor_few_trades_and_old_trades_without_tags():
    assert "Not enough" in " ".join(india_doctor.build(_closed(10, 4))["headline"])
    old = _closed(60, 5)
    for t in old:
        t.pop("tags"); t.pop("mfe_pct"); t.pop("mae_pct")
    r = india_doctor.build(old)
    assert r["ok"] and r["sample"] == 60


def test_crypto_doctor_unchanged_defaults():
    from test_strategy_doctor import make
    r = D.build_from(make(300, 11))
    assert r["unit"] == "USDT" and "USDT" in r["headline"][0] and r["side_names"]["BUY"] == "BUY"


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); n += 1; print("ok", name)
    print(n, "tests passed")
