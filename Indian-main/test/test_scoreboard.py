"""Final Scoreboard test (no internet, fake replay + fake saved trades).
Run from the repo root:  python3 test/test_scoreboard.py"""
import os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import scoreboard as SB


def fake_trades(n=200, seed=1):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        act = "BUY" if rnd.random() < 0.5 else "SELL"
        weak = rnd.random() < 0.4                      # weak trades (low ADX) lose more
        adx = rnd.uniform(8, 19) if weak else rnd.uniform(21, 40)
        roi = rnd.gauss(-9 if weak else -1, 6)
        t = {"adx": adx, "htf_trend": "up" if act == "BUY" else "down", "ema_slope_pct": 0.1 if act == "BUY" else -0.1,
             "volume_ratio": 1.3, "ema_gap_atr": 0.4, "regime_cross_n": 1, "entry_zone": "mean..+1sd" if act == "BUY" else "-1sd..mean"}
        if i % 10 == 0:
            t.pop("adx")                              # some trades have no ADX saved
        rows.append({"t": t, "act": act, "roi": roi, "pnl": roi})
    return rows


def fake_replay(adx_verdicts=("better", "better", "better")):
    tfs = {}
    for tf, vd in zip(("3m", "5m", "15m"), adx_verdicts):
        tfs[tf] = {"ok": True, "state": "done", "bot": {"n": 500, "net": -300.0, "win": 11.0}, "rows": [
            {"group": "Outside suggestion (4 points)", "key": "o_adx", "title": "ADX 20 or more", "taken": 200, "vs_bot": 120.0, "verdict": vd},
            {"group": "Bollinger (skip signals)", "key": "bb_sq", "title": "Skip squeeze", "taken": 300, "vs_bot": -40.0, "verdict": "worse"},
            {"group": "Exit and stop-loss", "key": "sl_prev1", "title": "Wider SL", "taken": 500, "vs_bot": 10.0, "verdict": "unclear"},
        ]}
    return {"running": False, "tfs": tfs}


def main():
    rows = fake_trades()
    out = SB.build_from(fake_replay(), rows)
    assert out["ok"] and out["groups"], "no groups"
    by = {r["key"]: r for g in out["groups"] for r in g["rows"]}
    assert by["o_adx"]["verdict"] == "helps", by["o_adx"]            # both sources agree it helps
    assert by["o_adx"]["saved"]["state"] == "ok" and by["o_adx"]["saved"]["vs_bot"] > 0
    assert by["bb_sq"]["verdict"] == "replay_down", by["bb_sq"]       # replay only, saved trades have no Bollinger data
    assert by["sl_prev1"]["verdict"] == "unclear"
    assert any("Safe to try" in h for h in out["headline"]), out["headline"]
    assert out["by_tf"] and out["by_tf"][0]["best"]["title"] == "ADX 20 or more"
    assert out["by_tf"][0]["worst"]["title"] == "Skip squeeze"

    # replay disagrees by timeframe -> MIXED, never "helps"
    out2 = SB.build_from(fake_replay(("better", "worse", "unclear")), rows)
    assert {r["key"]: r for g in out2["groups"] for r in g["rows"]}["o_adx"]["verdict"] == "mixed"

    # replay says better, saved trades say the opposite -> MIXED
    rev = fake_trades(seed=2)
    for r in rev:
        r["roi"] = -r["roi"] if r["t"].get("adx", 30) < 20 else r["roi"]
        r["roi"] = abs(r["roi"]) * (1 if r["t"].get("adx", 30) < 20 else -1)   # weak trades now win, strong ones lose
    out3 = SB.build_from(fake_replay(), rev)
    assert {r["key"]: r for g in out3["groups"] for r in g["rows"]}["o_adx"]["verdict"] == "mixed"

    # no replay yet: saved half still shows, nothing crashes
    out4 = SB.build_from({"tfs": {}, "running": False}, rows)
    assert out4["groups"] and out4["replay_tfs"] == []
    # no trades and no replay: empty but valid
    out5 = SB.build_from({"tfs": {}}, [])
    assert out5["ok"] and out5["groups"] == []
    # too few saved trades -> "no_data", not a made-up verdict
    out6 = SB.build_from(fake_replay(), fake_trades(n=20))
    assert {r["key"]: r for g in out6["groups"] for r in g["rows"]}["o_adx"]["saved"]["state"] == "no_data"
    # extras: plain description, top list, profit flag, SD length block
    assert by["o_adx"]["desc"] and by["bb_sq"]["desc"].startswith("Bollinger")
    assert out["top"] and out["top"][0]["key"] == "o_adx" and len(out["top"]) <= 5
    assert by["o_adx"]["still_losing"] is True and by["o_adx"]["profit_tfs"] == []
    assert any("No idea makes a profit" in h for h in out["headline"]), out["headline"]
    blk = SB.sd_block({"answer": ["x"], "tfs": [{"tf": "15m", "rows": [
        {"label": "SD 200 (bot)", "n": 9, "avg": -1.1, "verdict": "bot"}, {"label": "SD 100", "n": 9, "avg": -1.0, "verdict": "unclear"},
        {"label": "SD 200 + rule", "n": 5, "avg": -1.3, "verdict": "better"}]}]})
    assert blk["tfs"][0]["plain"][0]["len"] == 200 and blk["tfs"][0]["rule"][0]["avg"] == -1.3
    assert SB.sd_block(None) is None

    # simple view: idea's own result, answer words, day by day
    assert out["answer_box"]["kind"] == "none" and "Change nothing" in out["answer_box"]["text"], out["answer_box"]
    assert by["o_adx"]["answer"] == "LOSING" and out["profit_ideas"] == [] and out["closest"]
    rp = fake_replay()
    for tf in rp["tfs"].values():
        for r in tf["rows"]:
            if r["key"] == "o_adx":
                r["net"] = 55.0                          # this idea alone ends above zero
            else:
                r["net"] = -20.0
    dated = fake_trades()
    for i, r in enumerate(dated):
        r["ts"] = 1792000000 + i * 3 * 3600
    o7 = SB.build_from(rp, dated)
    assert o7["answer_box"]["kind"] == "profit" and o7["profit_ideas"][0]["key"] == "o_adx", o7["answer_box"]
    b7 = {r["key"]: r for g in o7["groups"] for r in g["rows"]}
    assert b7["o_adx"]["answer"] == "PROFIT" and b7["bb_sq"]["answer"] == "LOSING"
    assert len(o7["bot_by_day"]) == 7 and o7["bot_by_day"][0]["bot_n"] > 0
    d0 = b7["o_adx"]["saved"]["by_day"][0]
    assert d0["idea_n"] <= d0["bot_n"] and "day" in d0
    assert SB.build_from({"tfs": {}}, [])["answer_box"]["kind"] == "wait"
    # table data: total, counts per group, bot row, short names
    assert out["total"] == 3 and sum(c["n"] for c in out["counts"]) == 3, out["counts"]
    assert out["bot_row"]["replay"]["15m"] == -300.0 and out["bot_row"]["saved_n"] == len(rows)
    assert by["o_adx"]["short"] == "ADX 20+" and by["o_adx"]["vshort"] == "HELPS"
    kim = [c for c in out["counts"] if c["title"] == "Kim's ideas"][0]
    assert kim["better"] == 1 and kim["worse"] == 0
    assert all(len(r["short"]) <= 26 for g in out["groups"] for r in g["rows"])
    import variant_lab as _VL
    assert all(x[1] in SB.SHORT and x[1] in SB.DESC for x in _VL.SCENARIOS), "every Strategy Lab idea needs a short name and a plain line"
    # the API calls build(5000) through _swr(key, ttl, fn, 5000): build must accept that one argument (this was the TypeError in the app)
    r = SB.build(5000)
    assert isinstance(r, dict) and "groups" in r, r
    print("test_scoreboard OK")


if __name__ == "__main__":
    main()
