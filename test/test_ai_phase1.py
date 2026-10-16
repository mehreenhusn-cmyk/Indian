"""Phase 1 test: new facts (Z average line, divergence, sideways, Z+TSI agreement) and the Insights verdict.
Run:  python3 test/test_ai_phase1.py      Uses made-up candles / made-up signals only (no network, no trading code)."""
import importlib
import math
import os
import random
import sys
import tempfile
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
F = importlib.import_module("recovered_bot.ai_ind_features")
M = importlib.import_module("recovered_bot.ai_ab_board")
L = importlib.import_module("recovered_bot.ai_shadow_lab")
RC = importlib.import_module("recovered_bot.ai_rowcache")


def candles(n, seed=3):
    rnd = random.Random(seed)
    px, out = 100.0, []
    for i in range(n):
        o = px
        px = max(1.0, px * (1 + rnd.gauss(0, 0.004) + 0.0004 * math.sin(i / 40)))
        out.append({"timestamp": i * 180000, "open": o, "high": max(o, px) * 1.001, "low": min(o, px) * 0.999, "close": px})
    return out


class Facts(unittest.TestCase):
    def test_new_numbers_and_labels(self):
        S = F.build(candles(520))
        ind = F.own_features(S, 510)
        for k in ("zgap", "dvg", "rng30", "es10"):
            self.assertIn(k, ind)
        self.assertIn(ind["dvg"], (-1, 0, 1))
        buy, sell = F.labels("BUY", ind, None), F.labels("SELL", ind, None)
        for k in ("zma_vs_trade", "z_div", "move", "z_tsi"):
            self.assertIn(k, buy)
            self.assertIn(k, sell)
        # direction aware: a SELL reads the same chart the other way round
        self.assertNotEqual(buy["z_tsi"], sell["z_tsi"]) if ind["z"] and ind["dif"] else None

    def test_zsma_is_plain_average_of_z(self):
        S = F.build(candles(520))
        i = 500
        zs = [S["z"][j] for j in range(i - F.ZMA_LEN + 1, i + 1)]
        self.assertAlmostEqual(S["zsma"][i], sum(zs) / F.ZMA_LEN, places=9)

    def test_divergence_bearish(self):
        S = F.build(candles(520))
        i = 505
        # force: price makes a higher high in the last 10 candles while Z makes a lower high
        for j in range(i - 19, i - 9):
            S["c"][j], S["z"][j] = 100.0, 1.5
        for j in range(i - 9, i + 1):
            S["c"][j], S["z"][j] = 101.0, 1.0
        self.assertEqual(F._extra_numbers(S, i)["dvg"], -1)
        buy = F.labels("BUY", {"dvg": -1}, None)
        sell = F.labels("SELL", {"dvg": -1}, None)
        self.assertEqual(buy["z_div"], "Z divergence AGAINST trade")
        self.assertEqual(sell["z_div"], "Z divergence WITH trade")


class Insight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        L._dir = self.tmp
        L._loaded = True
        self.rows = []
        L._read_rows = lambda: list(self.rows)
        RC.set_source(lambda: list(self.rows))
        L._ensure_loaded = lambda: None
        L._cfg = lambda name, default: {"leverage": 10, "fee_roi_pct": 1.0, "timeframe": "3m"}.get(name, default)
        M._recs_cache.update(key=None, v=[])
        M._out_cache.clear()

    def _make(self, tf, n, start_ms):
        RC.reset()
        rnd = random.Random(5)
        for i in range(n):
            bad = rnd.random() < 0.4
            t = start_ms - 400 * 3600_000 + i * 3600_000 if i < 220 else start_ms + (i - 220) * 1800_000
            ret = rnd.gauss(-0.9, 0.5) if bad else rnd.gauss(0.35, 0.5)
            ind = {"z": 1.0, "zd3": 0.0, "tsi": 5.0, "tsl": 4.0, "dd1": 1.0, "wd": 0, "wu": 0, "zgap": 0.2 if not bad else -0.5,
                   "dvg": -1 if bad else 0, "rng30": 3.0, "es10": 0.5, "wr50": 1.0, "wrel": 1.0, "run20": 0.0,
                   "zp3": 0.2, "zm3": 0.0, "zs3": 0.0, "zp10": 0.2, "zm10": 0.0, "zs10": 0.0, "zmax20": 1.0}
            w = "SL" if ret < -0.4 else "TP"
            self.rows.append({"k": f"{tf}|{i}|{t}", "s": "C%d" % (i % 4), "tf": tf, "ind": ind, "a": "BUY", "t": t, "ctx": {}, "sig": {},
                              "o": {"T4": [ret, w, 5], "T1": [ret, w, 5]}})

    def test_verdict_and_checklist(self):
        now = int(time.time() * 1000)
        start = now - 3 * 86_400_000
        M._save_state({"ver": M.STATE_VER, "start_ms": start, "rules": {}})
        for tf in ("3m", "5m"):
            self._make(tf, 420, start)
        out = M.build("3m")
        ins = out["insight"]
        self.assertIn(ins["status"], ("READY", "NO", "MORE_DATA"))
        self.assertEqual(len(ins["lines"]), 3)
        self.assertGreaterEqual(len(ins["checks"]), 7)
        self.assertEqual(ins["ticks"], sum(1 for c in ins["checks"] if c["ok"]))
        self.assertTrue(ins["stage"]["allowed"] in (1, 2))
        if ins["status"] != "READY":
            self.assertEqual(ins["stage"]["allowed"], 1)     # a stage is allowed only when every check is green

    def test_no_data_never_raises(self):
        out = M.build("3m")
        self.assertTrue("insight" in out or "error" in out)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
