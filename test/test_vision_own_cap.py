"""Vision own-scan: daily loss cap 0 really means no cap; own prompt states the goal. No network.
Run: python3 test/test_vision_own_cap.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def main():
    from recovered_bot import ai_vision as V, ai_vision_own as O

    vals = {}
    O._cfg = lambda name, default: vals.get(name, default)          # fake settings
    assert O._num("vision_own_daily_loss_cap", 15.0) == 15.0         # unset -> default as before
    vals["vision_own_daily_loss_cap"] = 0
    assert O._num("vision_own_daily_loss_cap", 15.0) == 0.0          # 0 stays 0 (was turned into 15)
    vals["vision_own_daily_loss_cap"] = "25"
    assert O._num("vision_own_daily_loss_cap", 15.0) == 25.0
    vals["vision_own_daily_loss_cap"] = "abc"
    assert O._num("vision_own_daily_loss_cap", 15.0) == 15.0
    vals["vision_own_max_calls_hour"] = 0
    assert O._num("vision_own_max_calls_hour", 12) == 0.0

    # tick() must not stop on "daily own loss cap" when the cap is 0, even with a big loss today
    vals.update({"vision_own_enabled": True, "vision_own_daily_loss_cap": 0, "vision_own_max_calls_hour": 0, "vision_own_max_open": 3})
    O._own_day_net = lambda v: -500.0
    O._own_open_count = lambda v: 0
    O._watchlist = lambda: []                                         # stop right after the cap checks
    fakeV = type("FV", (), {"enabled": staticmethod(lambda: True), "quota_resume_at": staticmethod(lambda: 0)})
    O.tick(fakeV)
    assert O.scan_stats()["err"] == "empty watchlist", O.scan_stats()
    vals["vision_own_daily_loss_cap"] = 15                            # default behaviour is unchanged
    O.tick(fakeV)
    assert "daily own loss cap" in O.scan_stats()["err"], O.scan_stats()

    lv = {"close": 110.0, "e30": 109.0, "e50": 108.0, "mean": 108.5, "sd": 1.0, "p1": 109.5, "p2": 110.5, "p3": 111.5,
          "m1": 107.5, "m2": 106.5, "m3": 105.5, "tsi": 12.0, "tsl": 8.0, "z": 1.2, "zsma": 0.4,
          "low12": 100.0, "high12": 112.0, "avg_range": 0.5}
    base = {"symbol": "BTCUSDT", "side": "BUY", "tf_min": 15, "sig_price": 110.0, "feat": {}}
    own = V._signal_prompt(dict(base, source="own"), lv, 110.0)
    bot = V._signal_prompt(dict(base, source="bot"), lv, 110.0)
    assert "as few trades as possible" in own and "no daily loss limit" in own and "A bot signal just fired" not in own
    assert bot.startswith("A bot signal just fired.") and "as few trades" not in bot
    print("PASS test_vision_own_cap")


if __name__ == "__main__":
    main()
