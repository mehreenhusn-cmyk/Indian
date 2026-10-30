"""Part 21 test: do the lines the app DRAWS (EMA 30 / EMA 50, SD ladder, Z-score, TSI) match what the bot CALCULATES?
Dart: frontend/lib/widgets/candle_chart.dart (computeEma, computeSdLevels, computeSdSeries) + special_master.dart (_ema, _roll, _zOf, TSI chain).
Bot : backend/recovered_bot/strategy.py (_compute_ema, _rolling_mean_std, generate_signal) + india_indicators.py (ema, tsi).
FOUND by the audit: the Dart EMA started from the FIRST close, the bot (and Pine) start from the average of the first N closes; Special Master _ema did the same. Both fixed in Part 21.
HONEST LIMIT: Dart cannot be compiled in the build sandbox. The Dart functions are mirrored line by line in Python below and checked against the REAL backend code;
static checks pin the Dart source (the mirrored lines exist, nothing else in the two files changed). The owner's own APK build is the compile proof.
Offline, writes nothing. Run:  python3 test/test_v2_chart_parity.py"""
import hashlib
import math
import os
import random
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import india_indicators as II     # noqa: E402
from recovered_bot.strategy import ABCDStrategy      # noqa: E402

WID = os.path.join(ROOT, "frontend", "lib", "widgets")
CHART = open(os.path.join(WID, "candle_chart.dart"), encoding="utf-8").read()
SM = open(os.path.join(WID, "special_master.dart"), encoding="utf-8").read()
BOT = open(os.path.join(ROOT, "backend", "recovered_bot", "strategy.py"), encoding="utf-8").read()
IND = open(os.path.join(ROOT, "backend", "recovered_bot", "india_indicators.py"), encoding="utf-8").read()
# fingerprints (first 16 hex of sha256): the rest of each Dart file as it was BEFORE Part 21 (the changed function cut out), and the two backend references
CHART_REST, SM_REST = "34754276a0278d3c", "5dd8a48af6c7e5d1"
# the two NEW Dart functions (with their comments): the Python mirrors above copy exactly this text, so any later edit must update the mirrors and these two
CHART_NEW, SM_NEW = "b7ec8919454800f2", "05ac6350749c9a82"
BOT_REF, IND_REF = "500128d7e040b930", "b69294c3147c2eb6"


def fp(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def cut(src, a, b):
    return src[:src.index(a)] + src[src.index(b):]


def fixture(n, seed=21):
    rnd, p, out = random.Random(seed), 100.0, []
    for i in range(n):
        o = p
        p = p * (1 + (rnd.random() - 0.5) * 0.02)
        out.append({"timestamp": i * 300000, "open": o, "high": max(o, p) * (1 + rnd.random() * 0.002),
                    "low": min(o, p) * (1 - rnd.random() * 0.002), "close": p, "volume": 100.0 + rnd.random() * 50})
    return out


def closes_of(cs):
    return [c["close"] for c in cs]


# ---- Python mirrors of the Dart code (line by line) ----
def dart_ema_new(closes, length):                    # candle_chart.dart computeEma (Part 21)
    if not closes:
        return []
    ln = max(length, 1)
    alpha, out, s = 2 / (ln + 1), [], 0.0
    for i in range(min(len(closes), ln)):
        s += closes[i]
        out.append(s / (i + 1))
    for i in range(ln, len(closes)):
        out.append(alpha * closes[i] + (1 - alpha) * out[i - 1])
    return out


def dart_ema_old(closes, length):                    # computeEma BEFORE Part 21 (seed = first close)
    alpha, out = 2 / (length + 1), [closes[0]]
    for i in range(1, len(closes)):
        out.append(alpha * closes[i] + (1 - alpha) * out[i - 1])
    return out


def dart_sd_levels(closes, lookback=200):            # computeSdLevels (unchanged)
    w = closes[max(0, len(closes) - lookback):]
    mean = sum(w) / len(w)
    return mean, math.sqrt(sum((x - mean) ** 2 for x in w) / len(w))


def dart_sd_series(closes, lookback=200):            # computeSdSeries (unchanged)
    out = [None] * len(closes)
    for i in range(lookback - 1, len(closes)):
        w = closes[i - lookback + 1:i + 1]
        m = sum(w) / lookback
        out[i] = (m, math.sqrt(sum((x - m) ** 2 for x in w) / lookback))
    return out


def sm_ema_new(v, n):                                # special_master.dart _ema (Part 21)
    out, k, prev, cnt, s = [None] * len(v), 2.0 / (n + 1), None, 0, 0.0
    for i, x in enumerate(v):
        if x is None:
            continue
        if prev is None:
            s += x
            cnt += 1
            if cnt >= n:
                prev = s / n
                out[i] = prev
        else:
            prev = x * k + prev * (1.0 - k)
            out[i] = prev
    return out


def sm_ema_old(v, n):                                # _ema BEFORE Part 21 (seed = first valid value)
    out, k = [None] * len(v), 2.0 / (n + 1)
    st = next((i for i, x in enumerate(v) if x is not None), None)
    if st is None:
        return out
    prev = out[st] = v[st]
    for i in range(st + 1, len(v)):
        if v[i] is not None:
            prev = v[i] * k + prev * (1.0 - k)
            out[i] = prev
    return out


def sm_z(closes, ln):                                # _roll + _zOf (unchanged)
    out = [None] * len(closes)
    for i in range(ln - 1, len(closes)):
        w = closes[i - ln + 1:i + 1]
        m = sum(w) / ln
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / ln)
        if sd > 0:
            out[i] = (closes[i] - m) / sd
    return out


def sm_tsi(closes, ema, long=25, short=13, signal=13):   # compute(): Pine ta.tsi, long smoothing first
    pc = [None] + [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    apc = [None] + [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    nu, de = ema(ema(pc, long), short), ema(ema(apc, long), short)
    t = [100.0 * a / b if a is not None and b is not None and b != 0 else None for a, b in zip(nu, de)]
    return t, ema(t, signal)


def maxdiff(a, b, start=0):
    return max(abs(x - y) for x, y in list(zip(a, b))[start:])


class EmaParity(unittest.TestCase):
    def test_new_dart_ema_equals_bot_ema_from_the_seed(self):
        for n in (60, 120, 260, 600):
            cl = closes_of(fixture(n))
            for ln in (50, 30):
                bot = ABCDStrategy(ema_length=ln)._compute_ema(cl)
                self.assertLess(maxdiff(dart_ema_new(cl, ln), bot, ln - 1), 1e-9, (n, ln))
                self.assertEqual(bot[ln - 2], None)                      # the bot has NO value before the seed (Pine: na)

    def test_new_dart_ema_equals_india_ema(self):
        cl = closes_of(fixture(300))
        self.assertLess(maxdiff(dart_ema_new(cl, 50), II.ema(cl, 50), 49), 1e-9)

    def test_warmup_before_the_seed_is_the_running_average(self):
        cl = closes_of(fixture(80))
        d = dart_ema_new(cl, 50)
        self.assertEqual(len(d), 80)
        for i in (0, 10, 48):
            self.assertAlmostEqual(d[i], sum(cl[:i + 1]) / (i + 1), 12)
        self.assertEqual(len(dart_ema_new(cl[:20], 50)), 20)             # shorter than the length: still one value per candle
        self.assertEqual(dart_ema_new([], 50), [])
        self.assertEqual(dart_ema_new([5.0, 6.0], 1), [5.0, 6.0])        # length 1 = the close itself

    def test_the_old_seed_was_wrong_on_short_series_and_fine_on_long_ones(self):
        cl = closes_of(fixture(60))
        bot = ABCDStrategy()._compute_ema(cl)
        self.assertGreater(abs(dart_ema_old(cl, 50)[-1] - bot[-1]), 0.05)    # about 0.1 price units on a price of 100 after 60 candles
        cl = closes_of(fixture(600))
        bot = ABCDStrategy()._compute_ema(cl)
        self.assertLess(abs(dart_ema_old(cl, 50)[-1] - bot[-1]), 1e-6)       # converged: the last candle was always fine

    def test_chart_cross_agrees_with_every_bot_signal(self):
        cs, bot, hits = fixture(520), ABCDStrategy(), 0
        cl = closes_of(cs)
        for e in range(202, len(cs) + 1):
            sig = bot.generate_signal(cs[:e], "TESTUSDT", 5)
            e50 = dart_ema_new(cl[:e], 50)
            up = cl[e - 2] <= e50[-2] and cl[e - 1] > e50[-1]
            dn = cl[e - 2] >= e50[-2] and cl[e - 1] < e50[-1]
            self.assertEqual(sig.action if sig else None, "BUY" if up else ("SELL" if dn else None), e)
            hits += sig is not None
        self.assertGreaterEqual(hits, 8)                                 # the fixture really produces signals


class SdAndZParity(unittest.TestCase):
    def test_sd_levels_equal_the_strategy_window(self):
        cl = closes_of(fixture(450))
        m, s = ABCDStrategy()._rolling_mean_std(cl)
        dm, ds = dart_sd_levels(cl)
        self.assertAlmostEqual(dm, m, 9)
        self.assertAlmostEqual(ds, s, 9)

    def test_sd_series_last_point_equals_levels_and_every_point_equals_the_bot_window(self):
        cl = closes_of(fixture(330))
        ser = dart_sd_series(cl)
        self.assertEqual([i for i, x in enumerate(ser) if x is None], list(range(199)))     # na before a full window, like Pine
        for i in (199, 250, 329):
            m, s = ABCDStrategy()._rolling_mean_std(cl[:i + 1])
            self.assertAlmostEqual(ser[i][0], m, 9)
            self.assertAlmostEqual(ser[i][1], s, 9)
        self.assertAlmostEqual(ser[-1][0], dart_sd_levels(cl)[0], 9)

    def test_z_score_uses_the_same_window_as_the_sd_ladder(self):
        cl = closes_of(fixture(400))
        m, s = ABCDStrategy()._rolling_mean_std(cl)
        self.assertAlmostEqual(sm_z(cl, 200)[-1], (cl[-1] - m) / s, 9)   # Z pane and SD bands tell the same story on the last candle
        self.assertTrue(all(x is None for x in sm_z(cl, 200)[:199]))


class TsiParity(unittest.TestCase):
    def test_new_tsi_chain_equals_the_backend_tsi(self):
        cl = closes_of(fixture(400))
        t, sg = sm_tsi(cl, sm_ema_new)
        bt, bs = II.tsi(cl, 25, 13, 13)
        for mine, ref in ((t, bt), (sg, bs)):
            self.assertEqual([x is None for x in mine], [x is None for x in ref])        # same na positions
            self.assertLess(max(abs(a - b) for a, b in zip(mine, ref) if a is not None), 1e-9)
        self.assertEqual(next(i for i, x in enumerate(t) if x is not None), 37)           # 1 + 24 (EMA 25) + 12 (EMA 13)
        self.assertEqual(next(i for i, x in enumerate(sg) if x is not None), 49)          # + 12 (signal EMA 13)

    def test_old_tsi_seed_differed_early_and_converged_late(self):
        cl = closes_of(fixture(400))
        old, _ = sm_tsi(cl, sm_ema_old)
        bt, _ = II.tsi(cl, 25, 13, 13)
        self.assertGreater(abs(old[40] - bt[40]), 0.5)                   # TSI points, on the -100..100 scale
        self.assertLess(abs(old[-1] - bt[-1]), 1e-4)

    def test_null_gaps_are_skipped_after_the_seed_and_seed_waits_for_n_values(self):
        v = [None, None, 1.0, 2.0, None, 3.0, 4.0, 5.0]
        out = sm_ema_new(v, 3)
        self.assertEqual(out[:5], [None, None, None, None, None])        # needs 3 real values first
        self.assertAlmostEqual(out[5], 2.0)                              # (1 + 2 + 3) / 3
        self.assertAlmostEqual(out[6], 4 * 0.5 + 2.0 * 0.5)
        self.assertEqual(sm_ema_new([None, None], 3), [None, None])
        self.assertEqual(sm_ema_new([2.0, 4.0], 1), [2.0, 4.0])          # n = 1: alpha is 1, the value itself (same as the old one)


class DartSourceIsPinned(unittest.TestCase):
    def test_changed_functions_have_the_seed_code(self):
        for token in ("sum += closes[i];", "out.add(sum / (i + 1));", "final len = length < 1 ? 1 : length;",
                      "out.add(alpha * closes[i] + (1 - alpha) * out[i - 1]);"):
            self.assertIn(token, CHART)
        for token in ("double? prev;", "if (cnt >= n) {", "prev = sum / n;", "prev = x * k + prev * (1.0 - k);"):
            self.assertIn(token, SM)
        self.assertNotIn("seeded with the first close", CHART)
        self.assertNotIn("final out = <double>[closes[0]];", CHART)
        self.assertNotIn("var prev = v[start]!;", SM)

    def test_nothing_else_in_the_two_dart_files_changed(self):
        self.assertEqual(fp(cut(CHART, "/// Pine-style EMA, SMA-seeded", "/// SD colour family")), CHART_REST)
        self.assertEqual(fp(cut(SM, "  /// Pine ta.ema: SMA-seeded", "  static int _firstValid")), SM_REST)

    def test_the_new_dart_functions_are_exactly_what_the_mirrors_copy(self):
        a, b = CHART.index("/// Pine-style EMA, SMA-seeded"), CHART.index("/// SD colour family")
        self.assertEqual(fp(CHART[a:b]), CHART_NEW)
        a, b = SM.index("  /// Pine ta.ema: SMA-seeded"), SM.index("  static int _firstValid")
        self.assertEqual(fp(SM[a:b]), SM_NEW)

    def test_no_new_import(self):
        for src, want in ((CHART, ["dart:async", "dart:math", "../utils/format.dart"]), (SM, None)):
            imps = re.findall(r"^import '([^']+)'", src, re.M)
            if want:
                self.assertTrue(all(w in imps for w in want))
            self.assertFalse([i for i in imps if i.startswith("dart:io") or "http" in i])

    def test_backend_reference_code_is_unchanged(self):
        self.assertEqual(fp(BOT[BOT.index("    def _compute_ema"):BOT.index("    def calculate_tp_levels")]), BOT_REF)
        self.assertEqual(fp(IND[IND.index("def ema("):IND.index("def _ema_opt")]), IND_REF)


if __name__ == "__main__":
    unittest.main(verbosity=1)
