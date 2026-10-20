"""Recipe + shared row cache tests on FAKE data (no network, no bot). Run: python3 test/test_ai_recipe.py"""
import json, os, random, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from recovered_bot import ai_recipe as R, ai_exit_study as X, ai_advice as A, ai_rowcache as RC, ai_shadow_lab as L, ai_ind_features as F

RULES = ("T1", "T2", "T3", "T4", "T4n")
NOW = 1_700_000_000_000


def fake_rows(n, edge, seed=1):
    """edge=True: 'not sideways + Z and TSI both WITH' really wins; edge=False: outcomes are pure noise."""
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        side = rnd.random() < 0.35
        both = (not side) and rnd.random() < 0.5
        lab = {"move": "sideways (small range, flat EMA)" if side else "trending WITH trade",
               "z_tsi": "Z and TSI both WITH trade" if both else "Z WITH but TSI AGAINST",
               "sd_shape": rnd.choice(["SD expanding", "SD steady", "SD shrinking"])}
        if edge:
            v = rnd.gauss(2.5, 1.0) if both else rnd.gauss(-1.5, 1.0)
        else:
            v = rnd.gauss(-1.0, 2.0)
        w = "TP" if v > 0 else "SL"
        rows.append({"k": f"S{i}|3m|{i}|B", "s": f"C{i % 5}", "tf": "3m", "a": "BUY", "t": NOW + i * 180_000,
                     "ind": {"x": 1}, "ctx": lab, "o": {r: [v, w, 4] for r in RULES}})
    return rows


class T(unittest.TestCase):
    def setUp(self):
        F.labels = lambda a, ind, ctx, sig=None: dict(ctx)
        X._cfg = lambda n, d: {"leverage": 1, "fee_roi_pct": 0.0, "timeframe": "3m"}.get(n, d)
        R._cache.clear()
        R.CACHE_MIN_AGE_S = 0

    def feed(self, rows):
        RC.set_source(lambda: rows)
        R._cache.clear()

    def test_found_when_edge_is_real(self):
        self.feed(fake_rows(600, True))
        out = R.build("3m")
        self.assertEqual(out["verdict"], "FOUND", out["headline"])
        self.assertIn("Z and TSI both WITH trade", out["recipe"]["when_human"])
        self.assertGreater(out["recipe"]["test"]["avg"], 0)
        self.assertLess(out["recipe"]["luck_pct"], 10)
        self.assertGreater(out["recipe"]["test"]["avg"], out["recipe"]["base_test"]["avg"] + 1)

    def test_not_found_on_noise(self):
        self.feed(fake_rows(600, False, seed=3))
        out = R.build("3m")
        self.assertNotEqual(out["verdict"], "FOUND", out["headline"])
        self.assertTrue(out["steps"])

    def test_too_few(self):
        self.feed(fake_rows(60, True))
        self.assertEqual(R.build("3m")["verdict"], "TOO_FEW")

    def test_advice_recipe_flag(self):
        self.feed(fake_rows(600, True))
        R.build("3m")
        when = R.build("3m")["recipe"]["when"]
        good = {t.split("=", 1)[0]: t.split("=", 1)[1] for t in when}
        self.assertTrue(R.match_for("3m", good))
        bad = dict(good)
        bad[when[0].split("=", 1)[0]] = "something else"
        self.assertFalse(R.match_for("3m", bad))

    def test_rowcache_file_incremental(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "rows.jsonl")
        rows = fake_rows(50, True)
        with open(path, "w") as f:
            for r in rows[:30]:
                f.write(json.dumps(r) + "\n")
            f.write('{"k": "half')                       # half-written last line must be ignored
        RC.set_source(None)
        L._rows_file = path
        RC.MIN_GAP_S = 0
        RC.reset()
        self.assertEqual(len(RC.rows("3m")), 30)
        with open(path, "w") as f:                       # complete the file + more rows
            for r in rows:
                f.write(json.dumps(r) + "\n")
        os.replace(path, path)                           # same file, grown
        RC.reset()
        self.assertEqual(len(RC.rows("3m")), 50)
        with open(path, "a") as f:                       # append only -> only new lines are read
            r = dict(rows[0]); r["k"] = "new1"; r["t"] = NOW + 99_999_999
            f.write(json.dumps(r) + "\n")
        self.assertEqual(len(RC.rows("3m")), 51)
        tmp = path + ".tmp"                              # compaction = new inode, fewer rows
        with open(tmp, "w") as f:
            for r in rows[:10]:
                f.write(json.dumps(r) + "\n")
        os.replace(tmp, path)
        self.assertEqual(len(RC.rows("3m")), 10)


if __name__ == "__main__":
    unittest.main()
