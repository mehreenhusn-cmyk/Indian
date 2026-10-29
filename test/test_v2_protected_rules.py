"""Part 4 test A: PINS the owner's strategy rules exactly as the code does them today (30 Oct 2026). Records, never changes.
 - entry = EMA50 cross on the last CLOSED candle (up = BUY, down = SELL), entry price = that candle's close
 - stop loss = signal candle LOW (BUY) / HIGH (SELL)
 - TP1..TP4 = the next SD levels around the entry price
 - paper exits: TP4 (or the owner's chosen target) closes the trade; SL wins when SL and a target touch in one candle;
   after TP1 the stop moves to entry (break-even) from the NEXT candle; trail_mode step1 / step2 move it further
If one of these tests fails after some later change, a protected rule was changed: stop and ask the owner.
Offline, no network, writes nothing. Run:  python3 test/test_v2_protected_rules.py"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import paper_trader as P          # noqa: E402
from recovered_bot import settings_store             # noqa: E402
from recovered_bot.strategy import ABCDStrategy      # noqa: E402

STEP_MS = P.exchange.GRANULARITY_MIN * 60000


def candle(i, o, h, l, c, v=100.0):
    return {"timestamp": i * 300000, "open": o, "high": h, "low": l, "close": c, "volume": v}


def series(n, start, end):
    """n candles whose close moves in a straight line start -> end (small wicks)."""
    out = []
    for i in range(n):
        c = start + (end - start) * i / (n - 1.0)
        out.append(candle(i, c, c + 0.05, c - 0.05, c))
    return out


class StrategyEntry(unittest.TestCase):
    S = ABCDStrategy()

    def falling_then(self, last):
        """250 candles drifting down (close sits below its EMA50), then one signal candle `last` = (o, h, l, c)."""
        cs = series(250, 130.0, 100.0)
        cs.append(candle(250, *last))
        return cs

    def rising_then(self, last):
        cs = series(250, 100.0, 130.0)
        cs.append(candle(250, *last))
        return cs

    def test_cross_up_gives_buy_with_close_as_entry_and_candle_low_as_stop(self):
        cs = self.falling_then((100.0, 106.5, 99.2, 106.0))
        ema = self.S._compute_ema([c["close"] for c in cs])
        self.assertLessEqual(cs[-2]["close"], ema[-2])                       # precondition: was below
        self.assertGreater(cs[-1]["close"], ema[-1])                         # precondition: closes above
        s = self.S.generate_signal(cs, "TESTUSDT", 5)
        self.assertEqual(s.action, "BUY")
        self.assertEqual(s.entry_price, 106.0)
        self.assertEqual(s.stop_loss, 99.2)                                  # signal candle LOW
        self.assertLess(s.stop_loss, s.entry_price)
        self.assertEqual(s.candle_index, len(cs) - 1)

    def test_cross_down_gives_sell_with_close_as_entry_and_candle_high_as_stop(self):
        cs = self.rising_then((130.0, 130.4, 123.0, 124.0))
        ema = self.S._compute_ema([c["close"] for c in cs])
        self.assertGreaterEqual(cs[-2]["close"], ema[-2])
        self.assertLess(cs[-1]["close"], ema[-1])
        s = self.S.generate_signal(cs, "TESTUSDT", 5)
        self.assertEqual(s.action, "SELL")
        self.assertEqual(s.entry_price, 124.0)
        self.assertEqual(s.stop_loss, 130.4)                                 # signal candle HIGH
        self.assertGreater(s.stop_loss, s.entry_price)

    def test_no_cross_no_signal(self):
        self.assertIsNone(self.S.generate_signal(series(260, 100.0, 130.0), "TESTUSDT", 5))   # steady rise, never crosses
        cs = self.falling_then((100.0, 100.3, 99.7, 100.0))                  # stays below the EMA
        self.assertIsNone(self.S.generate_signal(cs, "TESTUSDT", 5))

    def test_too_few_candles_no_signal(self):
        cs = self.falling_then((100.0, 106.5, 99.2, 106.0))
        self.assertIsNone(self.S.generate_signal(cs[-150:], "TESTUSDT", 5))
        self.assertIsNone(self.S.generate_signal(cs[-201:], "TESTUSDT", 5))   # needs max(200, 50) + 2 = 202
        self.assertIsNotNone(self.S.generate_signal(cs[-202:], "TESTUSDT", 5))

    def test_settings_of_the_engine_are_lookback_200_ema_50(self):
        self.assertEqual((self.S.lookback_len, self.S.ema_length), (200, 50))

    def test_signal_time_is_the_candle_close_time(self):
        cs = self.falling_then((100.0, 106.5, 99.2, 106.0))
        s = self.S.generate_signal(cs, "TESTUSDT", 5)
        self.assertRegex(s.signal_time, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        # candle 250 opens at 250*300 s = 75000 s; it closes 299 s later: 75000 + 299 = 75299 s = 20:54:59 UTC
        self.assertEqual(s.signal_time, "1970-01-01 20:54:59")


class TpLadder(unittest.TestCase):
    S = ABCDStrategy()
    L = {"zero_price": 100.0, "onesd": 110.0, "twosd": 120.0, "threesd": 130.0,
         "neg_onesd": 90.0, "neg_twosd": 80.0, "neg_threesd": 70.0}

    def test_long_ladder_for_each_zone(self):
        f = lambda e: self.S.calculate_tp_levels(e, True, self.L)
        self.assertEqual(f(60.0), (70.0, 80.0, 90.0, 100.0))
        self.assertEqual(f(75.0), (80.0, 90.0, 100.0, 110.0))
        self.assertEqual(f(85.0), (90.0, 100.0, 110.0, 120.0))
        self.assertEqual(f(95.0), (100.0, 110.0, 120.0, 130.0))
        self.assertEqual(f(105.0), (110.0, 120.0, 130.0, 130.0))
        self.assertEqual(f(115.0), (120.0, 130.0, 130.0, 130.0))
        self.assertEqual(f(125.0), (130.0, 130.0, 130.0, 130.0))

    def test_short_ladder_for_each_zone(self):
        f = lambda e: self.S.calculate_tp_levels(e, False, self.L)
        self.assertEqual(f(135.0), (130.0, 120.0, 110.0, 100.0))
        self.assertEqual(f(125.0), (120.0, 110.0, 100.0, 90.0))
        self.assertEqual(f(115.0), (110.0, 100.0, 90.0, 80.0))
        self.assertEqual(f(105.0), (100.0, 90.0, 80.0, 70.0))
        self.assertEqual(f(95.0), (90.0, 80.0, 70.0, 70.0))
        self.assertEqual(f(85.0), (80.0, 70.0, 70.0, 70.0))

    def test_long_targets_never_go_backwards(self):
        for e in range(55, 140, 5):
            t = self.S.calculate_tp_levels(float(e), True, self.L)
            self.assertEqual(list(t), sorted(t), e)
            self.assertGreaterEqual(t[0], min(e, 130.0) if e < 130 else 130.0)
            t = self.S.calculate_tp_levels(float(e), False, self.L)
            self.assertEqual(list(t), sorted(t, reverse=True), e)


class PaperExits(unittest.TestCase):
    """_evaluate_candles walks closed candles oldest -> newest (the same walk the live monitor does after a gap)."""

    def setUp(self):
        self._get = settings_store.get
        self.mode = {"trail_mode": "off"}
        settings_store.get = lambda k, d=None: self.mode.get(k, d)
        self.addCleanup(setattr, settings_store, "get", self._get)

    @staticmethod
    def long_pos(**kw):
        p = {"entry_price": 100.0, "action": "BUY", "leverage": 10, "opened_at_ts": 0, "signal_stop_loss": 99.0,
             "signal_tp1": 101.0, "signal_tp2": 102.0, "signal_tp3": 103.0, "signal_tp4": 104.0,
             "breakeven_auto_shifted": False, "tp_hit_levels": []}
        p.update(kw)
        return p

    @staticmethod
    def short_pos(**kw):
        p = {"entry_price": 100.0, "action": "SELL", "leverage": 10, "opened_at_ts": 0, "signal_stop_loss": 101.0,
             "signal_tp1": 99.0, "signal_tp2": 98.0, "signal_tp3": 97.0, "signal_tp4": 96.0,
             "breakeven_auto_shifted": False, "tp_hit_levels": []}
        p.update(kw)
        return p

    @staticmethod
    def walk(pos, rows):
        cs = [candle(i + 1, 100.0, h, l, 100.0) for i, (h, l) in enumerate(rows)]
        return P._evaluate_candles(pos, cs, 0, 0)

    def test_default_target_is_tp4_and_full_exit_there(self):
        out, hits, best, worst, _x = self.walk(self.long_pos(), [(104.2, 100.5)])
        self.assertEqual((out["reason"], out["exit_price"]), ("TP4", 104.0))
        self.assertEqual(hits, [1, 2, 3, 4])

    def test_owner_chosen_target_replaces_tp4(self):
        out = self.walk(self.long_pos(user_target_tp=2), [(102.3, 100.5)])[0]
        self.assertEqual((out["reason"], out["exit_price"]), ("TP2_TARGET", 102.0))

    def test_stop_is_the_signal_candle_low_and_exits_at_it(self):
        out = self.walk(self.long_pos(), [(100.6, 98.9)])[0]
        self.assertEqual((out["reason"], out["exit_price"]), ("SL", 99.0))
        out = self.walk(self.short_pos(), [(101.1, 99.4)])[0]
        self.assertEqual((out["reason"], out["exit_price"]), ("SL", 101.0))

    def test_stop_and_target_in_one_candle_counts_as_stop(self):
        out = self.walk(self.long_pos(), [(104.5, 98.5)])[0]
        self.assertEqual(out["reason"], "SL")
        self.assertIn("conservative", out["note"])

    def test_tp1_moves_stop_to_entry_from_the_next_candle_long(self):
        rows = [(101.3, 99.5),            # touches TP1, dips to 99.5 but above the 99.0 stop: still open
                (100.8, 99.9)]            # next candle: stop is now at entry 100.0 -> stopped at entry
        out, hits, _b, _w, x = self.walk(self.long_pos(), rows)
        self.assertEqual((out["reason"], out["exit_price"]), ("SL", 100.0))
        self.assertIn("breakeven stop", out["note"])
        self.assertEqual(hits, [1])
        self.assertTrue(x["be_shift"])

    def test_tp1_moves_stop_to_entry_from_the_next_candle_short(self):
        out = self.walk(self.short_pos(), [(100.5, 98.7), (100.1, 99.2)])[0]
        self.assertEqual((out["reason"], out["exit_price"]), ("SL", 100.0))
        self.assertIn("breakeven stop", out["note"])

    def test_same_candle_as_tp1_still_uses_the_original_stop(self):
        out, hits, _b, _w, x = self.walk(self.long_pos(), [(101.3, 99.5)])
        self.assertIsNone(out)
        self.assertEqual(hits, [1])
        self.assertTrue(x["be_shift"])                                   # shift is queued for the next candle

    def test_without_tp1_the_stop_stays_at_signal_candle_low(self):
        out = self.walk(self.long_pos(), [(100.9, 99.6), (100.9, 99.4)])[0]
        self.assertIsNone(out)                                           # 99.4 is still above the 99.0 stop

    def test_trail_off_keeps_stop_at_entry_after_tp2(self):
        out = self.walk(self.long_pos(), [(102.5, 99.5), (101.5, 100.9)])[0]
        self.assertIsNone(out)                                           # stop is entry 100.0, low 100.9 stays above

    def test_trail_step1_tp2_moves_stop_to_tp1(self):
        self.mode["trail_mode"] = "step1"
        out = self.walk(self.long_pos(), [(102.5, 99.5), (101.5, 100.9)])[0]
        self.assertEqual((out["reason"], out["exit_price"]), ("SL", 101.0))
        self.assertIn("trailing stop", out["note"])

    def test_trail_step2_needs_tp2_for_entry_and_tp3_for_tp1(self):
        self.mode["trail_mode"] = "step2"
        out = self.walk(self.long_pos(), [(101.5, 99.5), (100.8, 99.9)])[0]
        self.assertIsNone(out)                                           # TP1 alone moves nothing in step2
        out = self.walk(self.long_pos(), [(102.5, 99.5), (100.8, 99.9)])[0]
        self.assertEqual((out["reason"], out["exit_price"]), ("SL", 100.0))

    def test_trail_never_loosens_a_stop(self):
        self.mode["trail_mode"] = "step1"
        pos = self.long_pos(trailed_sl=100.5)                            # the owner already trailed tighter than entry
        out = self.walk(pos, [(101.4, 100.6), (101.2, 100.4)])[0]
        self.assertEqual((out["reason"], out["exit_price"]), ("SL", 100.5))

    def test_percent_positions_get_tp1_half_and_tp2_full(self):
        pos = {"entry_price": 100.0, "action": "BUY", "leverage": 10, "opened_at_ts": 0, "tp_value": 2.0,
               "sl_value": 1.0, "tp_hit_levels": [], "breakeven_auto_shifted": False}
        sl, tps = P._effective_levels(pos)
        self.assertEqual((sl, tps[1], tps[2], tps[3], tps[4]), (99.0, 101.0, 102.0, None, None))

    def test_roi_is_price_move_times_leverage(self):
        self.assertAlmostEqual(P._calc_roi(self.long_pos(), 101.0), 10.0)
        self.assertAlmostEqual(P._calc_roi(self.short_pos(), 99.0), 10.0)
        self.assertAlmostEqual(P._calc_roi(self.long_pos(), 99.0), -10.0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
